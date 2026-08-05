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
    """Every fenced block — the parts a reader is meant to run."""
    return re.findall(r"```[^\n]*\n(.*?)```", text, re.DOTALL)


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
    return sorted((repo_root() / "scripts").glob("*.sh"))


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
