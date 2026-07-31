"""Supervision invariants — bounded retries, breakers, deadlines.

SPEC_SUPERVISION_V0.md, written from a real incident: 24 agents started, 4
produced results, 20 were retries of a failure that was never transient, and
the whole thing ran for eight hours. Every test here is one sentence of that
post-mortem made impossible.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from wringer import cli, loop


def only_loop(repo: Path) -> Path:
    loops = sorted((repo / loop.LOOPS_DIRNAME).iterdir())
    assert len(loops) == 1, loops
    return loops[0]


def events(repo: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (only_loop(repo) / loop.EVENTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def result(repo: Path) -> dict:
    return json.loads(
        (only_loop(repo) / loop.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )["result"]


# --- the signature: same shape in, same hash out ---


def test_the_same_failure_hashes_the_same_through_the_noise(repo, monkeypatch, capsys):
    """Two laps whose logs differ only by timestamps, durations and run ids
    must produce one signature, or the breaker never fires in practice."""
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "echo \\"failed at $(date +%H:%M:%S) after $((RANDOM))ms\\"; exit 1"
run:
  worker: "date +%s%N >> calc.py"
  max_iterations: 4
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    signatures = [
        e["failure_signature"] for e in events(repo) if e["type"] == "verify.finished"
    ]
    assert len(signatures) == 2, signatures
    assert signatures[0] == signatures[1], "noise defeated the normalizer"
    assert result(repo)["reason"] == "oscillating"


def test_a_worker_going_in_circles_trips_the_breaker(repo, monkeypatch, capsys):
    """A→B→A. The worker changes the tree every lap, so `no_progress` cannot
    catch it — only a memory of failure shapes can."""
    (repo / "state").write_text("A\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "cat state; grep -q DONE state"
run:
  worker: "if grep -q A state; then echo B > state; else echo A > state; fi"
  max_iterations: 9
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    outcome = result(repo)
    assert outcome["reason"] == "oscillating"
    # A, B, then A again — stopped on the third lap, not the ninth
    assert outcome["iterations"] == 3
    assert "not converging" in (only_loop(repo) / loop.SUMMARY_FILENAME).read_text(
        encoding="utf-8"
    )


def test_the_breaker_does_not_fire_on_genuinely_different_failures(
    repo, monkeypatch, capsys
):
    """The false-positive guard: a loop making real progress through
    different failures must be allowed to keep going."""
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "cat calc.py; grep -q FIXED calc.py"
run:
  worker: "date +%s%N >> calc.py"
  max_iterations: 3
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    outcome = result(repo)
    assert outcome["reason"] == "max_iterations"
    assert outcome["iterations"] == 3


def test_no_progress_beats_the_breaker_because_it_says_more(
    repo, monkeypatch, capsys
):
    """A worker that changes nothing satisfies both stop conditions. The
    reason recorded must be the one that tells the operator what to fix."""
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
run:
  worker: "true"
  max_iterations: 5
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    assert result(repo)["reason"] == "no_progress"


# --- deadlines ---


def test_a_wall_clock_stops_the_loop_between_steps(repo, monkeypatch, capsys):
    """Every wait has a deadline. It is checked between steps, so a verify in
    flight finishes rather than being abandoned half-done."""
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "cat calc.py; grep -q FIXED calc.py"
run:
  worker: "sleep 2; date +%s%N >> calc.py"
  max_iterations: 9
  wall_clock: 1
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    started = time.monotonic()
    assert cli.main(["run"]) == cli.EXIT_GATE_FAILED
    elapsed = time.monotonic() - started
    capsys.readouterr()

    outcome = result(repo)
    assert outcome["reason"] == "budget_exhausted"
    # stopped early rather than running all nine laps
    assert outcome["iterations"] < 9
    assert elapsed < 30, f"the wall clock did not bind ({elapsed:.1f}s)"


def test_wall_clock_is_optional_and_absent_by_default(repo, monkeypatch, capsys):
    """The loop is already bounded by iterations x timeout, so a wall clock
    is a second opinion the repo asks for, never one Wringer imposes."""
    from wringer import config

    cfg = config.parse(
        {
            "version": 1,
            "gates": [{"id": "t", "run": "true"}],
            "run": {"worker": "true"},
        }
    )

    assert cfg.run.wall_clock is None


def test_a_zero_wall_clock_is_a_config_error():
    import pytest

    from wringer import config

    with pytest.raises(config.ConfigError, match="wall_clock"):
        config.parse(
            {
                "version": 1,
                "gates": [{"id": "t", "run": "true"}],
                "run": {"worker": "true", "wall_clock": 0},
            }
        )


def test_the_signature_is_recorded_for_every_failure(repo, monkeypatch, capsys):
    """The ledger carries it, so a resumed loop can rebuild the breaker's
    memory rather than starting blind."""
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
run:
  worker: "echo FIXED > calc.py"
  max_iterations: 3
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_OK
    capsys.readouterr()

    verifies = [e for e in events(repo) if e["type"] == "verify.finished"]
    failed, passed = verifies[0], verifies[-1]
    assert failed["status"] == "failed" and "failure_signature" in failed
    # absent when nothing failed — the house convention for optional keys
    assert passed["status"] == "passed" and "failure_signature" not in passed
