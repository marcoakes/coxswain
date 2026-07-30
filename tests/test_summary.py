"""`summary.md` rendering — the human-readable face of a bundle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from wringer import evidence, summary
from wringer.config import Gate
from wringer.gates import GateResult
from wringer.git import RepoState

NOW = datetime(2026, 7, 30, 8, 6, 1, tzinfo=timezone(timedelta(hours=1)))

LINT = Gate(id="lint", run="make lint")
TEST = Gate(id="test", run="make test")
DEPLOY = Gate(id="deploy", run="make deploy")
FORMAT = Gate(id="format", run="make format-check", optional=True)


@pytest.fixture
def bundle(tmp_path: Path) -> evidence.Bundle:
    return evidence.Bundle.create(tmp_path / ".wringer" / "runs", now=NOW)


def state(**overrides) -> RepoState:
    defaults = {
        "root": Path("/tmp/demo"),
        "head_sha": "bc0d4c5d254ec9990bd2ba8251e79ba71b62f2dd",
        "branch": "main",
        "dirty": True,
    }
    return RepoState(**{**defaults, **overrides})


def outcome(
    bundle: evidence.Bundle,
    index: int,
    gate: Gate,
    exit_code: int = 0,
    duration_ms: int = 1800,
    timed_out: bool = False,
) -> GateResult:
    gate_dir = bundle.gate_dir(index, gate.id)
    return GateResult(
        gate=gate,
        exit_code=exit_code,
        duration_ms=duration_ms,
        timed_out=timed_out,
        stdout_path=gate_dir / "stdout.log",
        stderr_path=gate_dir / "stderr.log",
    )


def test_a_passing_run_reads_as_passed(bundle):
    written = summary.write(
        bundle,
        state(dirty=False),
        results=[outcome(bundle, 1, LINT), outcome(bundle, 2, TEST, duration_ms=9231)],
        skipped=[],
        failed_gate=None,
    )

    text = written.read_text(encoding="utf-8")
    assert written.name == "summary.md"
    assert f"# wring verify — {bundle.run_id}" in text
    assert "- repo: **demo** @ `bc0d4c5` (branch `main`, clean)" in text
    assert "- started: 2026-07-30T08:06:01+01:00" in text
    assert "- result: **passed** — all required gates passed" in text
    assert "| lint | passed | 1.8s |" in text
    assert "| test | passed | 9.2s |" in text
    assert "[stdout](gates/001_lint/stdout.log)" in text
    assert "[stderr](gates/002_test/stderr.log)" in text
    # nothing failed, so no rerun instruction
    assert "wring verify --gate" not in text


def test_a_failed_run_names_the_gate_skips_the_rest_and_gives_the_rerun(bundle):
    written = summary.write(
        bundle,
        state(),
        results=[
            outcome(bundle, 1, LINT),
            outcome(bundle, 2, TEST, exit_code=1, duration_ms=9231),
        ],
        skipped=[DEPLOY],
        failed_gate="test",
    )

    text = written.read_text(encoding="utf-8")
    assert "- repo: **demo** @ `bc0d4c5` (branch `main`, dirty)" in text
    assert "- result: **failed** — required gate `test` failed" in text
    assert "| test | failed | 9.2s |" in text
    assert "| deploy | skipped | — | — |" in text
    assert "wring verify --gate test" in text


def test_an_optional_failure_is_labelled_optional(bundle):
    written = summary.write(
        bundle,
        state(),
        results=[outcome(bundle, 1, FORMAT, exit_code=1), outcome(bundle, 2, TEST)],
        skipped=[],
        failed_gate=None,
    )

    text = written.read_text(encoding="utf-8")
    assert "| format | failed (optional) |" in text
    assert "- result: **passed**" in text


def test_a_timeout_says_timed_out(bundle):
    written = summary.write(
        bundle,
        state(),
        results=[
            outcome(bundle, 1, TEST, exit_code=-15, timed_out=True, duration_ms=1000)
        ],
        skipped=[],
        failed_gate="test",
    )

    text = written.read_text(encoding="utf-8")
    assert "| test | timed out | 1.0s |" in text


def test_the_summary_points_at_the_captured_tree(bundle):
    written = summary.write(
        bundle,
        state(changed_files=("calc.py", "test_calc.py"), untracked=("new.py",)),
        results=[outcome(bundle, 1, TEST)],
        skipped=[],
        failed_gate=None,
    )

    text = written.read_text(encoding="utf-8")
    assert (
        "- files: 2 changed, 1 untracked "
        "([diff.patch](diff.patch), [status.txt](status.txt))" in text
    )


def test_with_nothing_untracked_the_summary_says_only_changed(bundle):
    written = summary.write(
        bundle,
        state(changed_files=("calc.py",)),
        results=[outcome(bundle, 1, TEST)],
        skipped=[],
        failed_gate=None,
    )

    assert "- files: 1 changed (" in written.read_text(encoding="utf-8")


def test_outside_a_repo_the_summary_promises_no_capture(bundle):
    written = summary.write(
        bundle,
        state(head_sha=None, branch=None, dirty=False),
        results=[outcome(bundle, 1, TEST)],
        skipped=[],
        failed_gate=None,
    )

    # nothing was captured, so no dangling links to files that do not exist
    assert "diff.patch" not in written.read_text(encoding="utf-8")


def test_outside_a_git_repo_the_summary_says_so(bundle):
    written = summary.write(
        bundle,
        state(head_sha=None, branch=None, dirty=False),
        results=[outcome(bundle, 1, TEST)],
        skipped=[],
        failed_gate=None,
    )

    assert "- repo: **demo** — not a git repository" in written.read_text(
        encoding="utf-8"
    )


def test_detached_head_is_spelled_out(bundle):
    written = summary.write(
        bundle,
        state(branch=None),
        results=[outcome(bundle, 1, TEST)],
        skipped=[],
        failed_gate=None,
    )

    assert "(branch `detached HEAD`, dirty)" in written.read_text(encoding="utf-8")
