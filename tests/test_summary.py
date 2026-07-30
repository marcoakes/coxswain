"""`summary.md` rendering — the human-readable face of a bundle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cox import evidence, summary
from cox.config import Gate
from cox.gates import GateResult
from cox.git import RepoState

NOW = datetime(2026, 7, 30, 8, 6, 1, tzinfo=timezone(timedelta(hours=1)))

LINT = Gate(id="lint", run="make lint")
TEST = Gate(id="test", run="make test")
DEPLOY = Gate(id="deploy", run="make deploy")
FORMAT = Gate(id="format", run="make format-check", optional=True)


@pytest.fixture
def bundle(tmp_path: Path) -> evidence.Bundle:
    return evidence.Bundle.create(tmp_path / ".cox" / "runs", now=NOW)


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
    assert f"# cox verify — {bundle.run_id}" in text
    assert "- repo: **demo** @ `bc0d4c5` (branch `main`, clean)" in text
    assert "- started: 2026-07-30T08:06:01+01:00" in text
    assert "- result: **passed** — all required gates passed" in text
    assert "| lint | passed | 1.8s |" in text
    assert "| test | passed | 9.2s |" in text
    assert "[stdout](gates/001_lint/stdout.log)" in text
    assert "[stderr](gates/002_test/stderr.log)" in text
    # nothing failed, so no rerun instruction
    assert "cox verify --gate" not in text


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
    assert "cox verify --gate test" in text


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
        results=[outcome(bundle, 1, TEST, exit_code=-15, timed_out=True, duration_ms=1000)],
        skipped=[],
        failed_gate="test",
    )

    text = written.read_text(encoding="utf-8")
    assert "| test | timed out | 1.0s |" in text


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
