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
    offenders = [
        line.strip()
        for block in bash_blocks(text)
        for line in block.splitlines()
        if re.search(r"ls\s+-[a-zA-Z]*a[a-zA-Z]*\s+/Applications/Docker\.app", line)
    ]
    assert not offenders, (
        f"{name} inspects the Docker.app stub with `ls -la`, which the stub's "
        "own stripped permissions defeat (field report 2026-08-05, R2-02). "
        f"Use `ls -ld`. Offending lines: {offenders}"
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
    """A guard over an empty glob passes and means nothing."""
    assert script_files(), "no scripts/*.sh found — this guard is not guarding"


@pytest.mark.parametrize("pattern", _DEVELOPER_PATHS, ids=lambda p: p.pattern)
def test_no_script_hardcodes_one_developers_machine(pattern: re.Pattern[str]):
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
