"""`wring start` — the guided launch (SPEC_START_V0.md).

The program's first interactive surface, and the machinery that makes it
testable: everything here is a pure function of the answers it was given, so
the whole wizard runs with no terminal at all. `cli.py` owns the prompting,
the printing and the exit codes, exactly as it does for every other command.

**There is no config WRITER anywhere else in the program** — `config.py`
parses and never emits, and `wring init` writes a template rather than a
config it composed. So `emit` below is new machinery, and it carries the two
rulings that make writing a config safe (§3d):

1. **An existing `.wringer.yaml` is read, never replaced.** Additions are
   appended as text, so every byte the user wrote — comments included —
   survives verbatim. A load-and-dump round trip would silently delete the
   commented template `wring init` ships, which is most of what a new user
   has to read.
2. **Every emitted config round-trips through `config.parse` before it is
   written.** A wizard that writes a config the parser rejects is a wizard
   that bricks the repo it was pointed at, and it would do it to the least
   technical user this program has.
"""

from __future__ import annotations

import getpass
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from wringer import config, detect

# The width this command keeps its console inside.
#
# 80 is the classic terminal floor, and it is also exactly the canvas
# `scripts/demo_render.py` draws on — a fixed 80 columns with no wrapping,
# clipping or truncation. Bounding the OUTPUT rather than the picture is the
# honest direction: the cast is evidence and the SVG only draws it, so a
# renderer that cropped would be hiding what the command said. A real launch
# produced lines of 124, 145 and 223 columns before this existed.
CONSOLE_WIDTH = 80

# What a human runs to have the variable set next time. Printed, never run —
# and it is `SETUP.md`'s own line, because the route a credential takes from a
# person's head into a process should be the one route this project documents.
# `read -rs` keeps it off the terminal and out of shell history.
#
# It is a COMMAND, so it is never elided to fit the console the way a path is
# — a shortened command is one that does not run. `SETUP.md`'s prompt text
# ("API key: " rather than the variable's own name) is kept for that reason
# too: it is shorter, and it is the line this project already documents.
PERSIST_HINT = 'read -rs -p "API key: " {name} && export {name}'


def fit(text: str, width: int = CONSOLE_WIDTH) -> str:
    """One line, bounded — the middle elided when it does not fit.

    The middle rather than the tail, because what overflows here is almost
    always a path, and a path with its head kept and its filename dropped is
    the half nobody needed. `…` is visible on purpose: `gates.truncate` and
    `_print_tail` both already say what they dropped, and a bounded line that
    reads as complete is worse than one that admits it is not.
    """
    if len(text) <= width:
        return text
    keep = width - 1
    head = keep // 2
    return f"{text[:head]}…{text[len(text) - (keep - head):]}"


def wrap(text: str, indent: str = "") -> str:
    """Prose, wrapped to the console width. `textwrap`, so stdlib only."""
    import textwrap

    return textwrap.fill(
        text,
        width=CONSOLE_WIDTH,
        subsequent_indent=indent,
        break_long_words=False,
        break_on_hyphens=False,
    )


class StartError(Exception):
    """The launch cannot proceed: config or environment (CLI exit code 2)."""


class Refused(Exception):
    """A precondition this command will not overwrite or guess past (exit 3)."""


@dataclass(frozen=True)
class Emission:
    """The config `wring start` would write, and what changed in it.

    Nothing here has touched the disk. `emit` is deliberately pure so that the
    round-trip guarantee is structural rather than remembered: the text is
    proven to parse before any caller can write it, and a refusal leaves no
    half-written file behind because there was never a write to abandon.
    """

    path: Path
    text: str
    # Sections this adds, in the order they were appended.
    added: tuple[str, ...] = ()
    # Sections the config already declared with exactly the value asked for.
    # Re-running the launch is idempotent (§1), and saying "already declared"
    # is different from saying "written".
    already: tuple[str, ...] = ()
    created: bool = False

    @property
    def changed(self) -> bool:
        return self.created or bool(self.added)

    def write(self) -> None:
        if self.changed:
            self.path.write_text(self.text, encoding="utf-8")


_WORKSPACE_NOTE = (
    "# Where `wring get` clones. There is no default: Wringer does not choose\n"
    "# where to put your code.\n"
)

_RUN_NOTE = (
    "# The agent that drives the repair loop, and the NAME of the variable\n"
    "# holding its credential — never the value. Wringer will not read a\n"
    "# credential out of a config file, and never writes one here.\n"
)


def emit(
    root: Path,
    *,
    workspace: str | None = None,
    worker: config.AcpWorker | None = None,
) -> Emission:
    """Compose the `.wringer.yaml` this launch needs, or refuse to.

    Adds only absent sections. A section the user already wrote with a
    different value is a refusal (§3d), not a rewrite — and a section they
    wrote with the *same* value is neither, because a launch that cannot be
    re-run is not idempotent.
    """
    path = root / config.CONFIG_FILENAME
    created = not path.is_file()

    if created:
        # `wring init`'s own bytes, not a second renderer. §7 forbids
        # replacing `wring init`: the wizard calls its machinery.
        base = detect.template(detect.detect(root))
        current = _parse(base, path.name)
    else:
        base = path.read_text(encoding="utf-8")
        try:
            current = config.load(path)
        except config.ConfigError as exc:
            # Their file, already broken. That is a config error to report,
            # not a section clash to refuse — and appending to it would make
            # the message worse rather than better.
            raise StartError(str(exc)) from exc

    # Which keys the user WROTE, read from the bytes rather than from the
    # parsed config. The two answer different questions and the difference is
    # a defect: an empty `run:` parses as absent, so appending a second one
    # left the file with two top-level `run:` keys. PyYAML keeps the last —
    # ours — so the round-trip check passed and the user's own line was
    # silently overridden, which is exactly what exit 3 exists to prevent.
    written = _declared_keys(base)

    added: list[str] = []
    already: list[str] = []
    text = base

    if workspace is not None:
        wanted = workspace.strip()
        if "workspace" not in written:
            text = _append(text, _WORKSPACE_NOTE, _render({"workspace": wanted}))
            added.append("workspace")
        elif current.workspace == wanted:
            already.append("workspace")
        elif current.workspace is None:
            raise Refused(
                f"{path.name} has a 'workspace:' line with nothing after it. "
                "That is yours, so this command will not write over it or "
                "around it — fill it in, or delete the line and run again"
            )
        else:
            raise Refused(
                f"{path.name} already declares 'workspace: {current.workspace}' "
                f"and you asked for {wanted!r}. This command adds absent "
                "sections; it does not rewrite one you wrote. Edit the file, or "
                "run again with the workspace it already names"
            )

    if worker is not None:
        if "run" not in written:
            text = _append(text, _RUN_NOTE, worker_stanza(worker))
            added.append("run")
        elif current.run is not None and current.run.worker == worker:
            already.append("run")
        elif current.run is None:
            raise Refused(
                f"{path.name} has a 'run:' line with nothing under it. That is "
                "yours, so this command will not write over it or around it — "
                "fill it in, or delete the line and run again"
            )
        else:
            raise Refused(
                f"{path.name} already declares a 'run:' section with a worker "
                "of its own. This command adds absent sections; it does not "
                "rewrite one you wrote — the loop's worker is the thing that "
                "edits your code, so replacing it quietly is not a thing to do"
            )

    # The round trip, before anything can write these bytes. A `ConfigError`
    # here is a defect in this function, not in the user's file — so it is
    # reported as the refusal it is rather than as their problem.
    try:
        _parse(text, path.name)
    except StartError as exc:
        raise Refused(
            f"refusing to write {path.name}: the result would not parse "
            f"({exc}). Nothing was changed"
        ) from exc

    # And that it says each thing once. Parsing is not enough: a duplicated
    # top-level key parses fine and means whatever the reader's parser decides,
    # so a config with one is a config that lies to somebody.
    repeated = _repeated_keys(text)
    if repeated:
        raise Refused(
            f"refusing to write {path.name}: it would declare "
            f"{', '.join(repeated)} more than once. Nothing was changed"
        )

    return Emission(
        path=path,
        text=text,
        added=tuple(added),
        already=tuple(already),
        created=created,
    )


def _acp(worker: config.AcpWorker) -> dict[str, object]:
    """`run.worker.acp` as a mapping — and only the three keys that exist.

    `config.py:110` is the whole list. An absent key is written as absent
    rather than as an empty list, because `args: []` in a file a human reads
    invites them to wonder what belongs there.
    """
    acp: dict[str, object] = {"command": worker.command}
    if worker.args:
        acp["args"] = list(worker.args)
    if worker.env_passthrough:
        acp["env_passthrough"] = list(worker.env_passthrough)
    return {"acp": acp}


def worker_stanza(worker: config.AcpWorker) -> str:
    """The exact YAML `emit` appends for this worker.

    Public because consent IS the written stanza (§3c): the wizard shows what
    it proposes and does not write until the human accepts. Displayed and
    written come from this one function rather than from two renderers that
    agree today — the `_listing_step` lesson (`tests/test_docs.py:403-416`),
    where a demo showed one command and ran another for two days because
    nothing tied them together.
    """
    return _render({"run": {"worker": _acp(worker)}})


def _render(section: dict[str, object]) -> str:
    """One top-level section as YAML.

    `yaml.safe_dump` rather than hand-rolled text: a workspace path or an agent
    argument that needs quoting must get it, and a wizard that hand-rolls YAML
    escaping is a wizard that eventually writes a file its own parser rejects.
    """
    return yaml.safe_dump(
        section, sort_keys=False, default_flow_style=False, allow_unicode=True
    )


def _append(text: str, note: str, rendered: str) -> str:
    """Add one rendered section to a config, after everything already there."""
    if text and not text.endswith("\n"):
        text += "\n"
    return f"{text}\n{note}{rendered}"


def _top_level_keys(text: str) -> list[str]:
    """Every top-level key in the BYTES, duplicates included.

    `yaml.safe_load` cannot answer this — it silently keeps the last of a
    duplicated key, and a key written with no value comes back
    indistinguishable from one nobody wrote at all.
    """
    try:
        node = yaml.compose(text)
    except yaml.YAMLError:
        return []
    if node is None or not isinstance(getattr(node, "value", None), list):
        return []
    return [key.value for key, _ in node.value if hasattr(key, "value")]


def _declared_keys(text: str) -> set[str]:
    return set(_top_level_keys(text))


def _repeated_keys(text: str) -> list[str]:
    keys = _top_level_keys(text)
    return sorted({key for key in keys if keys.count(key) > 1})


def _parse(text: str, source: str) -> config.Config:
    try:
        return config.parse(yaml.safe_load(text), source=source)
    except yaml.YAMLError as exc:
        raise StartError(f"{source} is not valid YAML: {exc}") from exc
    except config.ConfigError as exc:
        raise StartError(str(exc)) from exc


# --- the credential ---------------------------------------------------------
#
# SPEC_START_V0.md §3a: prompted, held in memory for the process this launches,
# written nowhere. Not to config, not to disk, not to the ledger, not to a
# bundle, not to a process listing.


def has_terminal(stream: object | None = None) -> bool:
    """Whether there is a human to ask. **stdin, not stdout** (§3b).

    A pipeline, a CI job and the demo recorder all present a non-interactive
    stdin while stdout may still be a terminal, so testing the wrong stream
    would make every one of them look answerable.
    """
    stream = stream if stream is not None else sys.stdin
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        # A closed or replaced stdin is not a terminal, and asking it is not
        # an error worth raising here.
        return False


def key_in_environment(name: str) -> bool:
    """Whether the named variable already carries a value.

    The non-interactive form of the key answer (§3b, row 5), and it is how
    every other command in the program already receives a credential.
    """
    return bool(os.environ.get(name))


# How many times a mistyped answer is asked again before the wizard gives up
# and refuses with the flag to use instead. Bounded on purpose: a wizard that
# loops forever on bad input is a hazard in a script, and one that gives up on
# the first typo is an annoyance to the person it was built for.
MAX_ATTEMPTS = 3


@dataclass
class Prompts:
    """**The one place `wring start` reads anything from a human.**

    An interactive command that could only be exercised by a person is one
    nothing in CI ever runs — and this is the command a new user meets first,
    so it is the last one that should be untested. Every reader is a field, so
    the suite drives the whole wizard with no terminal anywhere.

    `read_secret` defaults to `getpass`, which is **only ever reached behind
    `interactive()`** (§3a-i): `getpass` opens `/dev/tty` rather than stdin, so
    a closed stdin does not stop it — it would block on a terminal nobody is
    watching. `interactive` tests **stdin, not stdout** (§3b): a pipeline, a CI
    job and the demo recorder all present a non-interactive stdin while stdout
    may still be a tty.

    No runtime dependency, no TUI (§7): `input`, `getpass`, and nothing else.
    """

    read: Callable[[str], str] = input
    read_secret: Callable[[str], str] = getpass.getpass
    interactive: Callable[[], bool] = has_terminal

    def confirm(self, question: str) -> bool:
        """Ask a yes/no question. **A bare Enter is not consent.**

        The one prompt that gates running someone's declared commands, so its
        default is the safe answer and the capital in `[y/N]` means it.
        """
        try:
            answer = self.read(f"  {question} [y/N] ")
        except EOFError:
            return False
        return answer.strip().lower() in ("y", "yes")

    def choose(self, question: str, options: Sequence[str]) -> str | None:
        """Ask for one of `options`, or None if the human wanted none of them.

        Returns None for the explicit "none" answer AND for giving up after
        `MAX_ATTEMPTS`; the caller tells those apart by asking again, which is
        why it gets a separate `chose_none` signal instead. Kept simple
        deliberately — see `_ask_agent` in `cli.py`.
        """
        for _ in range(MAX_ATTEMPTS):
            try:
                answer = self.read(f"  {question} ").strip()
            except EOFError:
                return None
            if answer in options or answer == NONE_ANSWER:
                return answer
            print(f"  not one of: {', '.join([*options, NONE_ANSWER])}")
        return None

    def secret(self, name: str) -> str:
        return self.read_secret(f"  {name}: ")


# What a human types to decline every option in a `choose`.
NONE_ANSWER = "none"


def prompts() -> Prompts:
    """The injection point. The suite replaces this to drive the wizard
    without a terminal; `cli.py` calls it once and passes the result down."""
    return Prompts()


def hold(name: str, value: str) -> None:
    """Put the credential where this launch's children will find it.

    In this process's environment and **nowhere else** — so it reaches the ACP
    agent through `run.worker.acp.env_passthrough`, which passes named
    variables and withholds everything else (`acp.py`'s minimal env). It is
    not written to the config, and there is no flag that could have carried
    it: `--key <value>` is a process listing.

    This is exactly what `SETUP.md`'s `read -rs … && export` does today, one
    process narrower and with no shell history to leak into. Every command
    that writes a bundle folds the names in `config.declared_secret_names`
    into its redactor, so the value is scrubbed out of the evidence even if a
    gate or an agent echoes it.
    """
    os.environ[name] = value


def gate_summary(cfg: config.Config) -> str:
    """One line naming what this repo will run, for the confirmation step."""
    return ", ".join(gate.id for gate in cfg.gates)
