"""Guards on the documents and scripts that are meant to be run literally.

`SETUP.md` is not prose about how installation might go — it is a runbook an
agent is instructed to follow verbatim, one command at a time. A wrong
command in it is a defect of the same class as a wrong line of code, and it
is one that no unit test, review or type checker ever catches: the only thing
that finds it is a human or an agent running the runbook on a real machine.

Two field runs have now done exactly that (`docs/field-report-2026-08-04` in
history, `docs/field-report-2026-08-05.md` in the repo), and both reported
the same shape of finding: *a step whose gate had never been executed*. These
tests are the cheap half of the answer. They cannot prove a command works —
that needs the machine, and `docs/MANUAL_CHECKS.md` records those — but they
can prove a command that was measured to be wrong never comes back.

The field reports themselves are excluded from every guard here. They are
preserved verbatim as primary evidence, and their transcripts of the broken
commands are the whole point of keeping them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def require_checkout(*needed: str) -> None:
    """Skip when a repo-only artifact is absent.

    The sdist ships the package and its suite, not the repository's scripts,
    workflows or runbooks. Guards over those are meaningful in a checkout and
    meaningless in a tarball, and failing there would tell a packager their
    download is broken when it is not.
    """
    for relative in needed:
        if not (repo_root() / relative).exists():
            pytest.skip(f"{relative} is not part of the distribution")


RUNBOOKS = ("SETUP.md", "QUICKSTART.md", "README.md")


def runbook_text(name: str) -> str | None:
    path = repo_root() / name
    return path.read_text(encoding="utf-8") if path.is_file() else None


def code_blocks(text: str) -> list[str]:
    """Every fenced block, whatever its language tag."""
    return re.findall(r"```[^\n]*\n(.*?)```", text, re.DOTALL)


def bash_blocks(text: str) -> list[str]:
    """Only the ```bash blocks — the lines a reader is told to type.

    These runbooks use the tag deliberately: a ```bash fence is an
    instruction, and an untagged fence is a transcript of what happened when
    someone ran one. The distinction matters to these guards, because
    documenting a command that fails means *showing* it failing, and a guard
    that cannot tell the two apart forbids explaining the bug it enforces.
    """
    return re.findall(r"```bash\s*\n(.*?)```", text, re.DOTALL)


# --- AC-01: `container images` is not a subcommand ------------------------
#
# Apple `container` 1.2.0 names it `image`, singular (alias `i`). The plural
# fails two different ways, and the second is the dangerous one:
#
#   container images pull …   → Error: Plugin 'container-images' not found.
#                               exit 64, and the error sends the reader
#                               hunting for a missing plugin — wrong diagnosis
#   container images list | grep wringer
#                             → exit 1, NO output and NO error, because the
#                               error went to stderr and the pipe ate the
#                               difference between "not pulled" and "wrong
#                               command"
#
# That silence is why this needs a test rather than a careful proofreader: an
# agent following the runbook cannot tell the two apart, and the runbook's own
# stop condition ("stop if output does not match") never fires.


@pytest.mark.parametrize("name", RUNBOOKS)
def test_no_runbook_tells_you_to_run_container_images(name: str):
    """The plural, in a block a reader is meant to type. Prose may still
    *name* it — the corrected runbook warns about it on purpose, and a
    warning that cannot spell the wrong command is not a warning."""
    text = runbook_text(name)
    if text is None:
        pytest.skip(f"{name} is not in this repo")
    offenders = [
        line.strip()
        for block in code_blocks(text)
        for line in block.splitlines()
        if "container images" in line
    ]
    assert not offenders, (
        f"{name} tells a reader to run `container images`, which is not a "
        "subcommand — Apple `container` spells it `image`, singular. "
        f"Offending lines: {offenders}"
    )


@pytest.mark.parametrize("name", RUNBOOKS)
def test_no_runbook_spells_the_two_measured_failures_anywhere(name: str):
    """The two exact forms a field run watched fail, in prose or in code.
    There is no context in which either is the right thing to write down."""
    text = runbook_text(name)
    if text is None:
        pytest.skip(f"{name} is not in this repo")
    for wrong in ("container images pull", "container images list"):
        assert wrong not in text, (
            f"{name} contains `{wrong}`, measured to fail on Apple "
            "`container` 1.2.0 (field report 2026-08-05, AC-01). The "
            "subcommand is `image`, singular."
        )


# --- R2-02: `ls -la` cannot show the thing it was sent to look at ---------
#
# SETUP.md told the reader to check for a stripped Docker.app stub with
# `ls -la`. On the machine that has the stub, that is precisely the command
# the stub defeats:
#
#   $ ls -la /Applications/Docker.app  →  ls: Permission denied
#   $ ls -ld /Applications/Docker.app  →  d---------  2 root  admin  64 ...
#
# A diagnostic that fails in exactly the case it diagnoses is worse than no
# diagnostic: the reader concludes something is wrong with their permissions
# rather than reading the answer, which is right there under -d.


@pytest.mark.parametrize("name", RUNBOOKS)
def test_no_runbook_inspects_docker_app_with_ls_la(name: str):
    text = runbook_text(name)
    if text is None:
        pytest.skip(f"{name} is not in this repo")
    # Any `ls` at all on that path, then judged on its flags — rather than
    # matching the literal `-la`, which `ls -l -a` and `ls -al` both escape.
    # `-d` is what makes the listing work; an `a` is what makes it fail.
    offenders = []
    for block in bash_blocks(text):
        for line in block.splitlines():
            match = re.search(
                r"\bls\s+((?:-\S+\s+)*)/Applications/Docker\.app", line
            )
            if match is None:
                continue
            flags = match.group(1)
            if "a" in flags or "d" not in flags:
                offenders.append(line.strip())
    assert not offenders, (
        f"{name} inspects the Docker.app stub with a listing its own stripped "
        "permissions defeat (field report 2026-08-05, R2-02). Only `ls -ld` "
        f"can show it. Offending lines: {offenders}"
    )


@pytest.mark.parametrize("name", RUNBOOKS)
def test_a_runbook_that_mentions_the_docker_stub_shows_how_to_see_it(name: str):
    """The positive half. Forbidding `ls -la` is only half a fix if the
    replacement quietly disappears in a later edit."""
    text = runbook_text(name)
    if text is None or "/Applications/Docker.app" not in text:
        pytest.skip(f"{name} does not discuss the Docker.app stub")
    assert "ls -ld /Applications/Docker.app" in text, (
        f"{name} discusses the Docker.app stub but never shows `ls -ld "
        "/Applications/Docker.app`, the only listing the stub's stripped "
        "permissions do not defeat."
    )


# --- R2-05: no script may be addressed to one developer's machine ---------
#
# Five scripts in scripts/ defaulted their scratch tree to
# /private/tmp/claude-501/-Users-marc-Claude/… — a sandbox path named after
# one machine and one user — and three of them point `rm -rf` or `find
# -delete` at it. On any other machine that either fails or, worse, deletes
# something that happens to be there.
#
# This is the cheapest possible test against the most embarrassing possible
# regression, and it is permanent: the next hardcoded sandbox path cannot
# reach main.

# The sandbox this repo is developed in, in both spellings it appears as.
_DEVELOPER_PATHS = (
    re.compile(r"claude-50[0-9]"),
    re.compile(r"-Users-[A-Za-z0-9]+-"),
    re.compile(r"/Users/(?!you\b)[A-Za-z0-9._-]+/"),
)


def script_files() -> list[Path]:
    """Every script, not just the shell ones — scripts/ holds Python too, and
    a hardcoded path is no less hardcoded for being in a .py file."""
    scripts = repo_root() / "scripts"
    return sorted([*scripts.glob("*.sh"), *scripts.glob("*.py")])


def test_scripts_exist_to_be_guarded():
    """A guard over an empty glob passes and means nothing.

    Skipped rather than failed when scripts/ is absent entirely: the sdist
    does not ship the repository's shell scripts, and a packager running the
    packed suite must not fail over a developer tool that was never in their
    tarball. In a checkout the directory is always there.
    """
    if not (repo_root() / "scripts").is_dir():
        pytest.skip("scripts/ is not part of the distribution")
    assert script_files(), "no scripts/*.sh found — this guard is not guarding"


@pytest.mark.parametrize("pattern", _DEVELOPER_PATHS, ids=lambda p: p.pattern)
def test_no_script_hardcodes_one_developers_machine(pattern: re.Pattern[str]):
    require_checkout("scripts")
    """`/Users/you/` is allowed: it is the documentation placeholder, and it
    is obviously not a real path. Any other home directory is a real one."""
    offenders = [
        f"{path.name}:{number}: {line.strip()}"
        for path in script_files()
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if pattern.search(line)
    ]
    assert not offenders, (
        "scripts must work on any machine — these name one developer's:\n  "
        + "\n  ".join(offenders)
        + "\nUse scripts/scratch.sh, which defaults to $TMPDIR."
    )


# --- R2-03/R2-04: the selftest must test the runbook, not a paraphrase -----
#
# scripts/setup-selftest.sh keeps its own copy of SETUP.md step 7H so it can
# run it twice. Nothing structurally couples the two, so the runbook could
# regress to `git add -A` while the selftest stayed green against its fixed
# copy — a guard that no longer guards the thing it names. These assertions
# are the coupling: the three tokens R2-03 and R2-04 turn on must be present
# in both files, and the token they replaced must be in neither.


def step_7h_block(text: str) -> str:
    """SETUP.md's step 7H command block."""
    after = text.split("## Step 7H", 1)
    assert len(after) == 2, "SETUP.md has no step 7H"
    blocks = bash_blocks(after[1])
    assert blocks, "step 7H has no command block"
    return blocks[0]


REQUIRED_7H_TOKENS = (
    ".gitignore",  # R2-03: the probe must not commit its own evidence
    "[ -d .git ]",  # R2-04: no re-init warning on a second run
    "git diff --cached --quiet",  # the && chain must survive a second run
)


def test_step_7h_and_its_selftest_agree():
    require_checkout("SETUP.md", "scripts/setup-selftest.sh")
    setup = step_7h_block((repo_root() / "SETUP.md").read_text(encoding="utf-8"))
    selftest = (repo_root() / "scripts" / "setup-selftest.sh").read_text(
        encoding="utf-8"
    )

    for token in REQUIRED_7H_TOKENS:
        assert token in setup, f"SETUP.md step 7H lost `{token}`"
        assert token in selftest, f"setup-selftest.sh's 7H copy lost `{token}`"

    assert "git add -A" not in setup, (
        "SETUP.md step 7H is back to `git add -A`, which stages the previous "
        "run's .wringer/ and commits raw gate output into the probe repo "
        "(field report 2026-08-05, R2-03)"
    )
    # Commands only. The script's own comment explains the R2-03 defect and
    # has to be able to name it, the same way SETUP.md's warning has to be
    # able to spell `container images`.
    commands = [
        line for line in selftest.splitlines() if not line.lstrip().startswith("#")
    ]
    offenders = [line.strip() for line in commands if "git add -A" in line]
    assert not offenders, (
        "setup-selftest.sh's 7H copy is back to `git add -A`, so it would "
        f"pass while the runbook it stands for is broken: {offenders}"
    )


# --- a script may not name a version it is not checking ---------------------
#
# Two of these rotted the same way: a literal `0.2.0` baked into a check that
# would keep passing after 0.3.0 shipped, silently blessing the PREVIOUS
# release. `verify-published.sh` installed `wringer==0.2.0` by default;
# `release-check.sh` grepped CHANGELOG for the literal string, which stays
# true forever once the entry exists.
#
# The rule is not "never write a version" — it is that a script's DEFAULT must
# come from src/wringer/__init__.py, the single source of truth pyproject
# already points at.

# Two parts or three. The pattern required THREE and the literal that
# broke the 0.3.0 release was `^wring 0\\.2` — so the guard would have
# missed it even with the right file on its list.
_VERSION_LITERAL = re.compile(r"\b0\.\d+(?:\.\d+)?\b")


def every_shell_script() -> list[str]:
    """Every script, discovered — not a list maintained beside them.

    The named list was `verify-published.sh`, `release-check.sh`,
    `ci-repro.sh`. `setup-selftest.sh` was not on it, hardcoded `^wring 0\\.2`,
    and failed the release that bumped to 0.3 — in CI only, because a
    developer's `wring` on PATH is often an older tool install while CI's is
    the repo. The guard against stale version literals had itself gone stale,
    in exactly the way it exists to prevent.
    """
    scripts = repo_root() / "scripts"
    return sorted(p.name for p in scripts.glob("*.sh")) if scripts.is_dir() else []


@pytest.mark.parametrize("name", every_shell_script() or ["none"])
def test_no_release_script_hardcodes_a_version_it_checks(name: str):
    require_checkout("scripts")
    path = repo_root() / "scripts" / name
    if not path.is_file():
        pytest.skip(f"{name} is not in this repo")
    offenders = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if _VERSION_LITERAL.search(line) and not line.lstrip().startswith("#")
    ]
    assert not offenders, (
        f"{name} names a version literal in an executable line. A default "
        "that does not come from src/wringer/__init__.py green-lights the "
        f"previous release once the next one ships. Offenders: {offenders}"
    )


# --- a promised image tag must have a workflow that publishes it -----------
#
# SETUP.md promised versioned OCI tags "with the 0.2.0 release". 0.2.0 shipped
# on 2026-08-03 and no workflow published one — only tests.yml pushed an
# image, and only the moving `:main`. The promise was not pending, it was
# false, and nothing in the repo could tell: the doc and the workflow had no
# relationship a test could check.
#
# This is the same coupling the step-7H guard makes between SETUP.md and
# setup-selftest.sh. A claim about CI behaviour is only as good as the CI.


def workflow_text(name: str) -> str:
    path = repo_root() / ".github" / "workflows" / name
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def test_versioned_image_tags_are_promised_and_published_together():
    require_checkout("SETUP.md", ".github/workflows/release.yml")
    setup = runbook_text("SETUP.md")
    if setup is None:
        pytest.skip("SETUP.md is not in this repo")
    promises = "Versioned tags" in setup or ":v0." in setup
    release = workflow_text("release.yml")
    publishes = "ghcr.io" in release and "push: true" in release
    assert promises == publishes, (
        "SETUP.md and release.yml disagree about versioned image tags — "
        f"SETUP promises={promises}, release.yml publishes={publishes}. "
        "Either publish them or stop promising them; a runbook claim the CI "
        "does not keep is the class of defect two field reports found."
    )


def test_nothing_promises_a_latest_image_tag():
    require_checkout(".github/workflows/release.yml")
    """`:latest` is deliberately absent — a tag that follows the newest
    release is the opposite of a pinned one. If it ever starts being
    published, the docs saying it does not exist become the lie."""
    # Only image-tag lines. `runs-on: ubuntu-latest` is not an image tag, and
    # a guard that cannot tell the difference is one somebody deletes.
    offenders = [
        line.strip()
        for name in ("release.yml", "tests.yml")
        for line in workflow_text(name).splitlines()
        if "ghcr.io" in line and line.strip().rstrip().endswith(":latest")
    ]
    assert not offenders, (
        "a workflow publishes a :latest image tag, which README and SETUP.md "
        f"both say does not exist: {offenders}"
    )


# --- the demo must show the command it ran ---------------------------------
#
# The cast displayed `ls .wringer/runs/<id>/` while what actually ran was
# `ls -1 .wringer/runs/$(ls -1 .wringer/runs | tail -1)`. A viewer typing what
# they saw got columnated output, not the one-per-line listing the recording
# shows — a transcript of a command nobody ran. A review flagged it on
# 2026-08-03 and it was still there two days later, because nothing tested it.


def demo_record_module():
    import importlib.util

    path = repo_root() / "scripts" / "demo_record.py"
    spec = importlib.util.spec_from_file_location("demo_record", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_demos_listing_step_displays_exactly_what_it_executes(tmp_path):
    require_checkout("scripts/demo_record.py")
    runs = tmp_path / ".wringer" / "runs" / "20260805-120000-abcd"
    runs.mkdir(parents=True)

    prompt, command = demo_record_module()._listing_step("wring", tmp_path)

    assert command[:2] == ["sh", "-c"]
    assert command[2] == prompt, (
        "the demo shows one command and runs another — law 8, in the artifact "
        "the README puts at the top of the page"
    )
    assert "<id>" not in prompt, "a placeholder is not a runnable command"
    assert "20260805-120000-abcd" in prompt


def test_the_committed_cast_shows_no_placeholder_command():
    require_checkout("docs/demo.cast.json")
    import json as _json

    cast = _json.loads(
        (repo_root() / "docs" / "demo.cast.json").read_text(encoding="utf-8")
    )
    prompts = [f["text"] for f in cast if f.get("prompt")]
    assert prompts, "the cast has no prompt lines — it is not a demo"
    for prompt in prompts:
        assert "<" not in prompt, (
            f"the committed cast shows a placeholder rather than a real "
            f"command: {prompt!r}"
        )


def test_the_committed_cast_timings_are_quantized():
    """Pacing is presentation and snaps to a grid; captured text is evidence
    and does not. Without this every regeneration rewrote 19 of 20 floats and
    every derived SVG keyframe, so a diff could not be read for whether the
    DEMO had changed."""
    require_checkout("docs/demo.cast.json")
    import json as _json

    module = demo_record_module()
    cast = _json.loads(
        (repo_root() / "docs" / "demo.cast.json").read_text(encoding="utf-8")
    )
    quantum = module.TIMING_QUANTUM
    off_grid = [
        f["at"]
        for f in cast
        if abs(f["at"] / quantum - round(f["at"] / quantum)) > 1e-9
    ]
    assert not off_grid, f"cast timings are not on the {quantum}s grid: {off_grid}"


def test_quantize_never_touches_the_captured_text():
    """The whole safety argument for quantizing: law 8 is about what the
    commands PRINTED, and this function may not edit a character of it."""
    module = demo_record_module()
    original = [
        {"at": 0.0, "text": "$ wring run", "prompt": True},
        {"at": 1.2345, "text": "✓ test passed       0.17s"},
        {"at": 2.9876, "text": ""},
    ]
    snapped = module.quantize(original)

    assert [f["text"] for f in snapped] == [f["text"] for f in original]
    assert [f.get("prompt") for f in snapped] == [f.get("prompt") for f in original]
    assert [f["at"] for f in snapped] == [0.0, 1.2, 3.0]


# --- the launch demo -------------------------------------------------------
#
# `main()` iterates a hardcoded tuple, so a new recorded command REQUIRES a
# new step function. What is banned is new *capability*: teaching the recorder
# to drive a pty or inject keystrokes would put synthesised keystrokes into
# the one file law 8 forbids editing. A step function is not that.

COMMITTED_CASTS = (
    "docs/demo.cast.json",
    "docs/start.cast.json",
    "docs/vacuous.cast.json",
)


def committed_casts() -> list[tuple[str, list[dict]]]:
    import json as _json

    found = []
    for name in COMMITTED_CASTS:
        path = repo_root() / name
        if path.is_file():
            found.append((name, _json.loads(path.read_text(encoding="utf-8"))))
    return found


def test_every_recorded_step_displays_exactly_what_it_executes(tmp_path):
    """`_listing_step` earned this guard the hard way — the cast showed one
    command and ran another for two days because nothing tested it.

    Discovered from `STEP_SETS` rather than a hardcoded list of names, so a
    step added later is guarded the day it is added. That matters more than it
    sounds: the hardcoded version silently stopped covering the two steps
    added for the vacuity recording, which is the same shape of gap as the bug
    it exists to prevent.
    """
    require_checkout("scripts/demo_record.py")
    module = demo_record_module()
    wring = "/somewhere/bin/wring"
    # `_listing_step` reads a real run directory to name the newest run.
    (tmp_path / ".wringer" / "runs" / "20260805-120000-abcd").mkdir(parents=True)

    steps = {step for group in module.STEP_SETS.values() for step in group}
    assert steps, "STEP_SETS is empty — nothing is recorded at all"

    for step in sorted(steps, key=lambda fn: fn.__name__):
        prompt, command = step(wring, tmp_path)
        if command[0] == "sh":
            # The one shell-shaped step: displayed and executed are ONE string.
            assert command[:2] == ["sh", "-c"]
            assert command[2] == prompt, (
                f"{step.__name__} displays {prompt!r} and runs {command[2]!r}"
            )
        else:
            assert command[0] == wring
            assert prompt.split() == ["wring", *command[1:]], (
                f"{step.__name__} displays {prompt!r} and executes {command!r} "
                "— law 8, in the artifact the README puts at the top of the page"
            )
        assert "<" not in prompt, (
            f"{step.__name__} shows a placeholder, not a runnable command"
        )


def test_the_recorded_agent_is_one_the_program_actually_knows():
    """The recorder names an agent id. If it drifts from the table, the
    recording shows a launch nobody could reproduce."""
    require_checkout("scripts/demo_record.py")
    from wringer import agents

    module = demo_record_module()
    assert module.START_AGENT_ID in agents.known()


def test_every_line_of_every_committed_cast_fits_the_renderers_canvas():
    """§8 — `scripts/demo_render.py` draws a FIXED 80-column canvas with no
    wrapping, clipping or truncation, and nothing tested it. The original
    cast's longest line is 51 characters, so the limit had never been
    exercised; the launch is the first flow wide enough to reach it."""
    require_checkout("docs/demo.cast.json")
    casts = committed_casts()
    assert casts, "no committed cast to check"

    too_wide = [
        (name, len(frame["text"]), frame["text"])
        for name, cast in casts
        for frame in cast
        if len(frame["text"]) > 80
    ]
    assert not too_wide, (
        f"{len(too_wide)} recorded line(s) overflow the renderer's 80-column "
        f"canvas: {too_wide[:3]}"
    )


def test_the_docs_say_the_key_step_is_not_in_the_recording():
    """§8 — the docs state IN WORDS that the one step a film cannot honestly
    show is the one where a human types a secret, and why."""
    require_checkout("docs/start.cast.json")
    found = [
        name
        for name in ("QUICKSTART.md", "SETUP.md")
        if (repo_root() / name).is_file()
        and "not in the recording" in (repo_root() / name).read_text("utf-8")
    ]
    assert found, (
        "no document says the key step is absent from the recording. A "
        "transcript that silently omits a step teaches people the step is not "
        "there"
    )


def test_the_docs_say_the_recorded_agent_was_a_stub():
    """§3c — identity is self-reported and Wringer never verifies it, so a
    recording that let a reader assume a real vendor agent ran would be a
    claim the artifact cannot support."""
    require_checkout("docs/start.cast.json")
    found = [
        name
        for name in ("QUICKSTART.md", "SETUP.md")
        if (repo_root() / name).is_file()
        and "stub" in (repo_root() / name).read_text("utf-8")
    ]
    assert found, "no document says the agent in the recording was a stub"


# --- the promise that changes with the capability --------------------------

PROMISE = (
    "Wringer never stores a credential. `wring start` will ask for your API "
    "key so it can hand it to the build it launches; it keeps it in memory "
    "for that session, folds it into the redactor so it cannot reach a "
    "bundle, and writes it nowhere. Your config records the name of an "
    "environment variable, never a key. Nothing else in Wringer ever asks."
)

DOCS_CARRYING_THE_PROMISE = ("README.md", "SECURITY.md", "SETUP.md")


def normalised(text: str) -> str:
    """Whitespace, emphasis and blockquote markers flattened.

    The same paragraph is wrapped three different ways in three documents and
    quoted inside a `>` block in one of them. Verbatim means the words, not
    the markdown around them.
    """
    lines = [line.lstrip("> ").rstrip() for line in text.splitlines()]
    return " ".join(" ".join(lines).replace("*", "").split())


def test_every_public_document_carries_the_promise_wording():
    """Marc approved this paragraph verbatim on 2026-08-06 (spec §6.1), and it
    ships in the SAME COMMIT as the capability — the J2 precedent. Note what
    changed and what did not: "never touches a credential" became "never
    STORES a credential". The narrower claim is the true one now that a
    command prompts for a key, and it is still the strongest claim in this
    category any comparable tool makes."""
    missing = [
        name
        for name in DOCS_CARRYING_THE_PROMISE
        if (repo_root() / name).is_file()
        and normalised(PROMISE) not in normalised(
            (repo_root() / name).read_text(encoding="utf-8")
        )
    ]
    assert not missing, f"the approved promise wording is missing from {missing}"


def test_no_document_still_claims_wringer_never_touches_a_credential():
    """The claim that stopped being true. `wring start` handles one."""
    offenders = [
        name
        for name in DOCS_CARRYING_THE_PROMISE + ("QUICKSTART.md", "AGENTS.md")
        if (repo_root() / name).is_file()
        and "never touches a credential" in (repo_root() / name).read_text("utf-8")
    ]
    assert not offenders, (
        f"{offenders} still claim Wringer never touches a credential. It "
        "prompts for one now; the true claim is that it never STORES one"
    )


# --- enumerations that `wring start` made false ---------------------------


def test_the_network_enumerations_name_wring_start():
    """§3e-i — `SPEC_GET_V0.md` and `AGENTS.md` both enumerate the network
    surface EXACTLY: three SEND commands, two FETCH. Cloning makes
    `wring start` the third fetcher, and both enumerations become false the
    moment it ships. Restated in the same commit as the capability, rather
    than quietly kept."""
    for name in ("SPEC_GET_V0.md", "AGENTS.md"):
        path = repo_root() / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        # The paragraph that does the enumerating, not the whole document.
        assert "wring start" in text, f"{name} never mentions wring start"
        assert "Three commands FETCH" in text or "three FETCH" in text, (
            f"{name} still enumerates two fetching commands; `wring start "
            "--clone` is the third"
        )


def test_setup_no_longer_says_wring_start_is_not_built():
    path = repo_root() / "SETUP.md"
    if not path.is_file():
        pytest.skip("SETUP.md is not in this repo")
    text = path.read_text(encoding="utf-8")
    assert "not built yet" not in text, (
        "SETUP.md still tells a reader `wring start` does not exist"
    )


def test_the_document_hierarchy_lists_every_spec_in_the_repo():
    """AGENTS.md's table listed four specs while the repo had nine, and
    nothing guarded it (operating rule 6). A hierarchy that omits half the
    binding documents is one the next agent reads and trusts."""
    require_checkout("AGENTS.md")
    text = (repo_root() / "AGENTS.md").read_text(encoding="utf-8")
    missing = [
        path.name
        for path in sorted(repo_root().glob("SPEC_*.md"))
        if path.name not in text
    ]
    assert not missing, f"AGENTS.md's document hierarchy omits {missing}"


def test_the_module_map_covers_every_module():
    """Operating rule 6: update this file whenever the module map changes."""
    require_checkout("AGENTS.md")
    text = (repo_root() / "AGENTS.md").read_text(encoding="utf-8")
    missing = [
        path.name
        for path in sorted((repo_root() / "src" / "wringer").glob("*.py"))
        if path.name not in ("__init__.py", "__main__.py")
        and f"`{path.name}`" not in text
    ]
    assert not missing, f"AGENTS.md's module map omits {missing}"


# --- the roadmap must describe the repository that exists ------------------
#
# A roadmap is the easiest document here to lie with: written once, never run,
# and nothing fails when it drifts. These run the picture's own probes, so a
# milestone that stops being true fails the suite instead of ageing quietly.


def roadmap_module():
    import importlib.util
    import sys

    if "roadmap_render" in sys.modules:
        return sys.modules["roadmap_render"]
    path = repo_root() / "scripts" / "roadmap_render.py"
    spec = importlib.util.spec_from_file_location("roadmap_render", path)
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: `@dataclass` resolves annotations through
    # `sys.modules[cls.__module__]`, so a module executed outside it raises
    # AttributeError on the first frozen dataclass it meets.
    sys.modules["roadmap_render"] = module
    spec.loader.exec_module(module)
    return module


def test_every_milestone_the_roadmap_draws_green_is_really_shipped():
    require_checkout("scripts/roadmap_render.py", "docs/roadmap.svg")
    module = roadmap_module()
    root = repo_root()

    drawn = (root / "docs" / "roadmap.svg").read_text(encoding="utf-8")
    wrong = []
    for milestone in module.MILESTONES:
        probed = milestone.done(root)
        # The rendered node carries a ✓ only when its probe passed. Matched on
        # the label's own text element so a caption cannot satisfy it.
        marked = f'>{milestone.label}</text>' in drawn and probed
        if probed != marked:
            wrong.append(f"{milestone.label}: probe={probed} drawn={marked}")
    assert not wrong, (
        "docs/roadmap.svg disagrees with this checkout — regenerate it:\n"
        "  python3 scripts/roadmap_render.py docs/roadmap.svg <YYYY-MM-DD>\n"
        + "; ".join(wrong)
    )


def test_the_roadmaps_probes_read_the_real_parser():
    """A milestone claiming a command must be checked against `wring --help`,
    not against a string that happens to appear in the source."""
    module = roadmap_module()
    from wringer import cli

    registered = {
        name
        for action in cli.build_parser()._actions
        if getattr(action, "choices", None)
        for name in action.choices
    }
    assert module.registered_commands() == frozenset(registered)


def test_every_registered_command_appears_on_some_milestone():
    """The other direction: a command that shipped under no milestone is work
    the roadmap cannot account for. `attest` and `audit` shipped in P5 and
    were missing from QUICKSTART's table for three days because nothing
    checked this."""
    module = roadmap_module()
    claimed = {name for m in module.MILESTONES for name in m.commands}
    missing = sorted(module.registered_commands() - claimed)
    assert not missing, f"no milestone accounts for {missing}"


def test_the_command_table_lists_every_command_that_exists():
    """QUICKSTART's table is what a reader counts. It listed thirteen while
    the parser registered sixteen."""
    require_checkout("QUICKSTART.md")
    text = (repo_root() / "QUICKSTART.md").read_text(encoding="utf-8")
    module = roadmap_module()
    missing = [
        name for name in sorted(module.registered_commands())
        if f"| `{name}` |" not in text
    ]
    assert not missing, f"QUICKSTART's command table omits {missing}"


# --- the flow diagram must describe the program that exists ----------------


def flow_module():
    import importlib.util
    import sys

    if "flow_render" in sys.modules:
        return sys.modules["flow_render"]
    path = repo_root() / "scripts" / "flow_render.py"
    spec = importlib.util.spec_from_file_location("flow_render", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["flow_render"] = module
    spec.loader.exec_module(module)
    return module


def test_every_command_the_flow_diagram_names_is_registered():
    """A diagram is the second easiest document here to lie with, after a
    roadmap: drawn once, never run, and authoritative-looking while it rots.
    Every box names the command that performs it, and this is what keeps that
    honest."""
    require_checkout("scripts/flow_render.py")
    module = flow_module()
    from wringer import cli

    registered = {
        name
        for action in cli.build_parser()._actions
        if getattr(action, "choices", None)
        for name in action.choices
    }
    unknown = sorted(module.commands_named() - registered)
    assert not unknown, f"the flow diagram names commands that do not exist: {unknown}"


def test_the_flow_diagram_keeps_the_human_steps():
    """Two stages name no command on purpose — approving a spec and reviewing
    a merge request are where this program stops and waits. A diagram showing
    only the automated steps would be selling the wrong thing, and deleting
    those boxes is the easiest way to make the picture look slicker."""
    require_checkout("scripts/flow_render.py")
    module = flow_module()

    human = [stage.title for stage in module.STAGES if not stage.commands]
    assert len(human) >= 2, (
        f"only {human} are marked as human steps — approval and review are "
        "both interlocks this program refuses to automate"
    )


def test_the_rendered_flow_matches_the_stages():
    require_checkout("scripts/flow_render.py", "docs/flow.svg")
    module = flow_module()
    drawn = (repo_root() / "docs" / "flow.svg").read_text(encoding="utf-8")

    missing = [s.title for s in module.STAGES if f">{s.title}</text>" not in drawn]
    assert not missing, (
        "docs/flow.svg is out of date — regenerate it:\n"
        "  python3 scripts/flow_render.py docs/flow.svg\n"
        f"missing stages: {missing}"
    )


# --- the Actions recipe must stay runnable ---------------------------------
#
# A workflow committed under `examples/` is never executed by anything, so it
# rots in total silence — the exact failure mode SETUP.md had twice. These
# parse every `wring` line in it against the real CLI.

RECIPE = "examples/github-actions/wringer.yml"


def recipe_wring_lines() -> list[str]:
    """Every `wring …` the recipe would actually execute.

    Both shapes YAML allows — `run: wring verify` on one line, and a bare
    `wring verify` inside a `run: |` block — and comments in neither, since
    the header explains the commands as prose and those are not invocations.
    """
    found = []
    for raw in (repo_root() / RECIPE).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        if line.startswith("run: wring "):
            found.append(line[len("run: "):])
        elif line.startswith("wring "):
            found.append(line)
    return found


def test_every_wring_command_in_the_actions_recipe_parses():
    require_checkout(RECIPE)
    from wringer import cli

    lines = recipe_wring_lines()
    assert lines, f"{RECIPE} invokes wring nowhere — it is not a recipe"

    parser = cli.build_parser()
    for line in lines:
        argv = line.replace("- run:", "").strip().split()
        assert argv[0] == "wring", argv
        # SystemExit here means an unknown subcommand or an unknown flag: the
        # recipe would fail on someone's PR with `invalid choice`.
        parser.parse_args(argv[1:])


def test_the_recipe_never_sends_anything():
    """`--send` is what writes git history and opens merge requests. A recipe
    that ran it would push branches from every pull request, and it would do
    so in the document people copy without reading."""
    require_checkout(RECIPE)
    text = (repo_root() / RECIPE).read_text(encoding="utf-8")
    offenders = [line.strip() for line in text.splitlines()
                 if "--send" in line and not line.strip().startswith("#")]
    assert not offenders, f"the recipe sends: {offenders}"


def test_the_recipe_blocks_the_merge_on_a_vacuous_bundle():
    """The claim the recipe makes in its own header. `wring deliver` is what
    refuses a `gates_vacuous` bundle, so the step has to actually be there —
    a recipe that promised the block and omitted the command would be worse
    than one that never mentioned it."""
    require_checkout(RECIPE)
    assert any(
        line.endswith("wring deliver") for line in recipe_wring_lines()
    ), "the recipe claims to block on vacuous gates but never runs wring deliver"


# --- every bundle-writing command must know every declared credential ------
#
# `config.declared_secret_names` is the single answer to "what does this
# config say holds a credential". Four commands built narrower lists of their
# own, and one — `wring fleet` — passed no extra names at all. That is how a
# credential an AGENT was handed reached `wring deliver`'s patch in cleartext
# while `verify`'s bundle had scrubbed it (fixed 2026-08-07), and the same
# argument applies to every other writer.


def test_every_redactor_reads_the_names_the_config_declares():
    """Structural, because behaviour tests only cover the paths somebody
    thought to exercise — and the two leaks this repo shipped were both write
    paths nobody thought to exercise."""
    import re

    offenders = []
    for path in sorted((repo_root() / "src" / "wringer").glob("*.py")):
        if path.name == "redact.py":  # where from_config is defined
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"Redactor\.from_config\(", text):
            window = text[match.start() : match.start() + 320]
            if "declared_secret_names" not in window:
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line}")
    assert not offenders, (
        "these build a redactor without the names the config declares, so a "
        "credential named in `run.worker.acp.env_passthrough` reaches whatever "
        f"they write: {offenders}"
    )


# --- enumerations of the network surface, wherever they live ---------------
#
# SPEC_START_V0 §3e-i named two documents that enumerate it exactly and
# required both to be restated when `wring start --clone` made them false.
# README.md carries a THIRD copy of the same sentence and was not on that
# list, so it went on saying "two commands fetch" after there were three.
# Naming the files was the mistake; this finds them.

FETCHERS = ("get", "issue", "start")


def test_no_document_still_says_two_commands_fetch():
    """The claim `wring start --clone` falsified."""
    offenders = []
    for path in sorted(repo_root().glob("*.md")):
        if path.name.startswith("field-report"):
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in ("Two commands fetch", "two commands FETCH",
                       "two commands fetch"):
            if phrase in text:
                offenders.append(f"{path.name}: {phrase!r}")
    assert not offenders, (
        "a document still enumerates two fetching commands; `wring start "
        f"--clone` is the third: {offenders}"
    )


def test_every_fetch_enumeration_names_wring_start():
    """The positive half. Forbidding the old sentence is only half a fix if
    the replacement quietly drops the command that caused it."""
    for name in ("README.md", "AGENTS.md", "SPEC_GET_V0.md"):
        path = repo_root() / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if "fetch" not in text.lower():
            continue
        assert "wring start" in text, (
            f"{name} enumerates what fetches but never names `wring start`, "
            "which opens a socket when the user asks it to clone"
        )


# --- counts a reader counts -----------------------------------------------

NUMBER_WORDS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}


def registered_command_count() -> int:
    from wringer import cli

    return len(
        [
            name
            for action in cli.build_parser()._actions
            if getattr(action, "choices", None)
            for name in action.choices
        ]
    )


def test_the_command_table_heading_counts_the_commands_that_exist():
    """QUICKSTART's heading is where a reader counts, and it said thirteen
    while the parser registered sixteen for three days.

    Only the heading, deliberately. Prose elsewhere says "0.2.0, thirteen
    commands" and that is a true statement about a PUBLISHED release, not a
    claim about this tree — pinning it to the parser would make a fact go
    stale every time main grows a command.
    """
    require_checkout("QUICKSTART.md")
    import re

    text = (repo_root() / "QUICKSTART.md").read_text(encoding="utf-8")
    match = re.search(r"^## The ([a-z]+) commands$", text, re.MULTILINE)
    assert match, "QUICKSTART has no '## The N commands' heading to check"

    claimed = NUMBER_WORDS.get(match.group(1))
    assert claimed is not None, f"unrecognised number word: {match.group(1)!r}"
    assert claimed == registered_command_count(), (
        f"QUICKSTART's heading says {match.group(1)} commands; the parser "
        f"registers {registered_command_count()}"
    )


def test_a_count_tied_to_a_release_says_which_release():
    """The other half. "thirteen commands" is only safe while it sits beside
    the version it describes — on its own it becomes a claim about this tree,
    and a wrong one."""
    import re

    for name in ("README.md", "QUICKSTART.md"):
        path = repo_root() / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.search(r"\b([a-z]+) commands\b", line)
            if not match:
                continue
            claimed = NUMBER_WORDS.get(match.group(1))
            if claimed is None or claimed == registered_command_count():
                continue
            assert re.search(r"\d+\.\d+\.\d+", line), (
                f"{name} claims '{match.group(1)} commands' without naming the "
                f"release it belongs to, and the parser registers "
                f"{registered_command_count()}: {line.strip()!r}"
            )
