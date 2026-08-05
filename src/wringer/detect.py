"""What `wring init` writes, and how it guesses.

The spec's ruling is the design: *if detection is uncertain, generate
comments rather than being clever*. So detection here is deliberately
literal. It reports commands the repository has already written down —
a `pyproject.toml` that configures ruff, a `package.json` with a `test`
script, a `Makefile` with a `lint` target — and never invents one. When it
finds nothing it says so and hands over a commented template, because a
wrong gate is worse than an absent one: it would make `wring verify` prove
something nobody asked for.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # only for a type; detect stays free of runtime coupling
    from wringer.config import Gate

CONFIG_FILENAME = ".wringer.yaml"

# The gate the blank template ships, and the two values `wring verify` reads
# to recognise it. It passes, so `wring init && wring verify` exits 0 in a
# repo nobody has configured yet — a red first run reads as "this tool is
# broken" rather than "you have not configured it yet".
#
# But a gate that always passes proves nothing, and a bundle whose status is
# `passed` because of it is exactly the vacuous evidence this project exists
# to make impossible (SPEC_VACUITY_V0.md). So the green exit is bought back
# with a sentence: `wring verify` says so on the terminal and in `summary.md`
# for as long as the placeholder is all there is. Detecting that by comparing
# against these constants — rather than by a flag written into the bundle —
# is deliberate: `wringer.evidence.v1` is frozen and cannot grow a field.
PLACEHOLDER_GATE_ID = "placeholder"
PLACEHOLDER_GATE_RUN = "true"

TEMPLATE_WARNING = (
    "This config is still a template: the only gate is the placeholder, so "
    "this run proved nothing about your code. Replace it with the commands "
    "that prove your change is mergeable."
)

# Gates are declared cheapest first (spec §Config design, rule 1), so the
# feedback a developer waits for arrives in the order they can act on.
_ORDER = ["format", "lint", "typecheck", "build", "test"]

# Makefile targets worth turning into gates, and the id each becomes.
_MAKE_TARGETS = {
    "format-check": "format",
    "fmt-check": "format",
    "lint": "lint",
    "typecheck": "typecheck",
    "types": "typecheck",
    "build": "build",
    "test": "test",
}

# package.json scripts, likewise.
_NPM_SCRIPTS = {
    "format:check": "format",
    "format-check": "format",
    "lint": "lint",
    "typecheck": "typecheck",
    "type-check": "typecheck",
    "build": "build",
    "test": "test",
}

_MAKE_TARGET_LINE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?!=)")

_SLOW = {"test", "build", "typecheck"}


@dataclass(frozen=True)
class Candidate:
    id: str
    run: str
    timeout: int = 120
    optional: bool = False


@dataclass(frozen=True)
class Detection:
    candidates: tuple[Candidate, ...] = ()
    sources: tuple[str, ...] = ()
    # What was on disk, whether or not it yielded a gate. Detection does not
    # use this — the message does. Telling a Python developer "no
    # pyproject.toml" while they are looking at theirs is how a correct
    # refusal to guess gets read as a broken detector.
    seen: tuple[str, ...] = ()

    @property
    def found(self) -> bool:
        return bool(self.candidates)


def detect(root: Path) -> Detection:
    """Look for commands this repository already declares."""
    found: list[Candidate] = []
    sources: list[str] = []

    for probe in (_detect_python, _detect_npm, _detect_make):
        candidates, source = probe(root)
        if candidates:
            found.extend(candidates)
            sources.append(source)

    return Detection(
        candidates=tuple(_ordered(_deduplicated(found))),
        sources=tuple(sources),
        seen=_seen(root),
    )


def _seen(root: Path) -> tuple[str, ...]:
    """The build-config files that are actually here.

    `Makefile` and `makefile` count once, not twice: on a case-insensitive
    filesystem — the macOS default — both spellings stat the same file, and
    "Found Makefile, makefile" reads like a bug in the thing reporting it.
    """
    seen = [
        name for name in ("pyproject.toml", "package.json") if (root / name).is_file()
    ]
    makefile = next(
        (name for name in ("Makefile", "makefile") if (root / name).is_file()), None
    )
    if makefile is not None:
        seen.append(makefile)
    return tuple(seen)


def is_untouched_template(gates: Iterable[Gate]) -> bool:
    """Whether these gates are still nothing but the shipped placeholder.

    Judged on the REQUIRED gates, because they are the ones whose passing is
    the run's verdict. Someone who added their real gates and left the
    placeholder behind as `optional: true` has configured this repo; someone
    whose only required gate is `true` has not, whatever the run says.

    The exception is a config with no required gates at all. `wring verify`
    exits 0 there having proven nothing whatsoever — a stronger version of
    the same vacuity — so if what is left is only placeholders, that still
    counts as untouched rather than as a configured repo.
    """
    gates = list(gates)
    required = [gate for gate in gates if not gate.optional]
    judged = required or gates
    return bool(judged) and all(
        gate.id == PLACEHOLDER_GATE_ID and gate.run.strip() == PLACEHOLDER_GATE_RUN
        for gate in judged
    )


def template(detection: Detection | None = None) -> str:
    """Render the `.wringer.yaml` to write."""
    if detection is None or not detection.found:
        return _blank_template(detection)

    lines = [
        f"# {CONFIG_FILENAME} — the gates Wringer runs to prove a change is"
        " mergeable.",
        f"# Detected from: {', '.join(detection.sources)}.",
        "#",
        "# These are commands this repository already declares. Check they are",
        "# the ones you want proven, and edit freely — they run in the repo",
        "# root, in this order, cheapest first. A failing required gate fails",
        "# the run (exit 1); `optional: true` records a failure without",
        "# failing the run.",
        "version: 1",
        "",
        "gates:",
    ]
    for candidate in detection.candidates:
        lines.append(f"  - id: {candidate.id}")
        lines.append(f"    run: {candidate.run}")
        lines.append(f"    timeout: {candidate.timeout}")
        if candidate.optional:
            lines.append("    optional: true")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _timeout_for(gate_id: str) -> int:
    return 300 if gate_id in _SLOW else 120


def _deduplicated(candidates: list[Candidate]) -> list[Candidate]:
    """Two ecosystems can both offer a `lint`, but ids name directories, so
    they have to stay unique."""
    seen: set[str] = set()
    unique: list[Candidate] = []
    for candidate in candidates:
        if candidate.id not in seen:
            seen.add(candidate.id)
            unique.append(candidate)
            continue
        suffix = 2
        while f"{candidate.id}-{suffix}" in seen:
            suffix += 1
        renamed = f"{candidate.id}-{suffix}"
        seen.add(renamed)
        unique.append(
            Candidate(
                id=renamed,
                run=candidate.run,
                timeout=candidate.timeout,
                optional=candidate.optional,
            )
        )
    return unique


def _ordered(candidates: list[Candidate]) -> list[Candidate]:
    def rank(candidate: Candidate) -> tuple[int, str]:
        base = candidate.id.split("-")[0]
        return (_ORDER.index(base) if base in _ORDER else len(_ORDER), candidate.id)

    return sorted(candidates, key=rank)


def _detect_python(root: Path) -> tuple[list[Candidate], str]:
    pyproject = root / "pyproject.toml"
    data: dict = {}
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
            data = {}

    declared = _python_dependency_names(data)
    tool = data.get("tool")
    tools = tool if isinstance(tool, dict) else {}
    candidates: list[Candidate] = []

    if "ruff" in tools or (root / ".ruff.toml").is_file() or "ruff" in declared:
        candidates.append(Candidate("lint", "ruff check .", _timeout_for("lint")))
    if "mypy" in tools or (root / "mypy.ini").is_file() or "mypy" in declared:
        candidates.append(Candidate("typecheck", "mypy .", _timeout_for("typecheck")))
    if "pytest" in tools or "pytest" in declared or _has_python_tests(root):
        candidates.append(Candidate("test", "pytest -q", _timeout_for("test")))

    if not candidates:
        return [], ""
    return candidates, "pyproject.toml" if pyproject.is_file() else "a Python layout"


def _has_python_tests(root: Path) -> bool:
    """Whether this repo has Python tests — not merely somewhere to put them.

    A `tests/` directory is not evidence of Python. Make, Go, Node and shell
    projects have one too, and treating the bare directory as a pytest
    declaration is exactly the cleverness the spec forbids: it invents
    `pytest -q` for a repo with no Python in it, which then fails `wring
    verify` with "no tests ran" on a perfectly healthy tree. Python *files*
    are the evidence.
    """
    if any(root.glob("test_*.py")):
        return True
    tests = root / "tests"
    return tests.is_dir() and any(tests.rglob("*.py"))


def _python_dependency_names(data: dict) -> set[str]:
    """Every requirement a pyproject mentions, reduced to bare names."""
    project = data.get("project")
    if not isinstance(project, dict):
        return set()
    requirements: list[str] = []
    if isinstance(project.get("dependencies"), list):
        requirements += [str(item) for item in project["dependencies"]]
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        for group in optional.values():
            if isinstance(group, list):
                requirements += [str(item) for item in group]
    return {
        re.split(r"[^A-Za-z0-9_.-]", item, maxsplit=1)[0].lower()
        for item in requirements
    }


def _detect_npm(root: Path) -> tuple[list[Candidate], str]:
    package = root / "package.json"
    if not package.is_file():
        return [], ""
    try:
        data = json.loads(package.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return [], ""

    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return [], ""

    candidates = [
        Candidate(
            _NPM_SCRIPTS[name],
            "npm test" if name == "test" else f"npm run {name}",
            _timeout_for(_NPM_SCRIPTS[name]),
        )
        for name in scripts
        if name in _NPM_SCRIPTS
    ]
    return candidates, "package.json" if candidates else ""


def _detect_make(root: Path) -> tuple[list[Candidate], str]:
    makefile = next(
        (root / name for name in ("Makefile", "makefile") if (root / name).is_file()),
        None,
    )
    if makefile is None:
        return [], ""
    try:
        text = makefile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], ""

    targets = {
        match.group(1)
        for line in text.splitlines()
        if (match := _MAKE_TARGET_LINE.match(line))
    }
    candidates = [
        Candidate(
            _MAKE_TARGETS[target],
            f"make {target}",
            _timeout_for(_MAKE_TARGETS[target]),
        )
        for target in sorted(targets)
        if target in _MAKE_TARGETS
    ]
    return candidates, "Makefile" if candidates else ""


_BLANK_HEAD = f"""\
# {CONFIG_FILENAME} — the gates Wringer runs to prove a change is mergeable.
# Spec: https://github.com/marcoakes/wringer/blob/main/SPEC_VERIFY_V0.md
#
"""

_BLANK_TAIL = f"""\
#
# Rules: gates run in order, cheapest first. A failing required gate fails
# the run (exit 1). Mark a gate `optional: true` to record its failure
# without failing the run.
version: 1

gates:
  # A gate that passes, so the harness works the moment `wring init` has run.
  # It proves NOTHING about your code, and `wring verify` says so on every
  # run until you replace it.
  - id: {PLACEHOLDER_GATE_ID}
    run: "{PLACEHOLDER_GATE_RUN}"

# Examples. Uncomment what fits, edit it, and delete the placeholder above.
# These are the shapes, not a guess about this repository:
#
#  - id: format
#    run: make format-check
#    optional: true
#
#  - id: lint
#    run: make lint
#
#  - id: test
#    run: make test

evidence:
  include:
    - git.diff
    - git.status
    - env
    - logs
"""


def _blank_template(detection: Detection | None = None) -> str:
    """The template written when nothing was detected — and why.

    The "why" cannot be a constant. A module-level string can only assert
    that all three build-config files are absent, and a field run pointed
    `wring init` at a real Python project with a `pyproject.toml`, a
    `uv.lock` and a `.venv` and got back "no pyproject.toml" (field report
    2026-08-05, R2-07). The *refusal* was right — that project declares no
    ruff, mypy or pytest anywhere, so there is genuinely nothing to gate, and
    inventing `pytest -q` for it is the cleverness this module exists not to
    do. The *sentence* was wrong, and it made a correct refusal look like a
    broken detector.
    """
    seen = detection.seen if detection is not None else ()
    if seen:
        why = (
            f"# Found {', '.join(seen)}, but nothing in it declares a lint, "
            "typecheck or\n# test command Wringer recognises — so this is a "
            "template, not a\n# guess. Wringer reports commands your repo "
            "already writes down;\n# it never invents one.\n"
        )
    else:
        why = (
            "# No pyproject.toml, package.json or Makefile here, so there was\n"
            "# nothing to read commands from — this is a template, not a guess.\n"
        )
    return _BLANK_HEAD + why + _BLANK_TAIL
