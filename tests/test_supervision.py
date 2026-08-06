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


def test_the_normalizer_strips_the_noise_that_actually_appears_in_logs():
    """A unit test, because the loop-level one only catches this when two
    laps happen to straddle a second boundary — which is how a bare clock
    time survived the first cut and only failed on a slower machine."""
    pairs = [
        ("failed at 10:24:30 after 123ms", "failed at 10:24:31 after 987ms"),
        ("boom 2026-07-31T10:24:30.123 x", "boom 2026-07-31T11:59:59.999 x"),
        ("run 20260731-102430-ab12 died", "run 20260731-115959-ff99 died"),
        ("at 0xdeadbeef in frame", "at 0x0badcafe in frame"),
        ("took 1.5s to fail", "took 92.25s to fail"),
        ("wrote /tmp/pytest-abc/x", "wrote /tmp/pytest-zzz/y"),
        ("worker pid=4821 exited", "worker pid=99 exited"),
    ]
    for a, b in pairs:
        assert loop._normalize(a) == loop._normalize(b), f"{a!r} vs {b!r}"


def test_the_normalizer_still_tells_different_failures_apart():
    """The false-positive guard: stripping noise must not erase the message."""
    assert loop._normalize("AssertionError: expected 3") != loop._normalize(
        "AssertionError: expected 4"
    )
    assert loop._normalize("ModuleNotFoundError: no module x") != loop._normalize(
        "SyntaxError: invalid syntax"
    )


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


# --- resume: a supervisor holds no state that is not on disk ---


RESUMABLE = """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
run:
  worker: "echo $$ > worker.pid; sleep 30"
  max_iterations: 5
  worker_timeout: 60
"""


def test_a_killed_loop_resumes_from_its_ledger(repo):
    """Really SIGKILL a running loop mid-worker, then really resume it.

    Invariant 7: everything is resumable from the ledger. A supervisor that
    kept state anywhere else could not survive its own death.
    """
    import os
    import signal
    import subprocess
    import sys

    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(RESUMABLE, encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, "-m", "wringer", "run"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    pid_file = repo / "worker.pid"
    deadline = time.monotonic() + 30
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert pid_file.exists(), "the worker never started"

    # SIGKILL, not SIGINT: the loop gets no chance to write loop.finished.
    # wait() rather than communicate(), because the orphaned worker still
    # holds the inherited pipe — waiting for EOF here would hang the test for
    # the orphan's lifetime, which is the same trap gates._drain exists for.
    worker_pid = int(pid_file.read_text(encoding="utf-8").strip())
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=30)
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            stream.close()

    loop_dir = only_loop(repo)
    recorded = [e["type"] for e in events(repo)]
    assert "loop.finished" not in recorded, "the kill was too gentle to test this"
    assert loop.inspect_for_resume(loop_dir) is not None

    (repo / ".wringer.yaml").write_text(
        RESUMABLE.replace(
            'worker: "echo $$ > worker.pid; sleep 30"',
            'worker: "echo FIXED > calc.py"',
        ),
        encoding="utf-8",
    )
    resumed = subprocess.run(
        [sys.executable, "-m", "wringer", "resume"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert resumed.returncode == cli.EXIT_OK, resumed.stderr

    after = events(repo)
    kinds = [e["type"] for e in after]
    # one resumed marker between the two lives, and a finish this time
    assert kinds.count("loop.resumed") == 1
    assert kinds[-1] == "loop.finished"
    assert result(repo)["status"] == "converged"
    # numbering continued rather than restarting
    resumed_event = next(e for e in after if e["type"] == "loop.resumed")
    iterations = [e["iteration"] for e in after if e["type"] == "iteration.started"]
    assert iterations == sorted(iterations) and len(set(iterations)) == len(iterations)
    assert resumed_event["iterations_done"] >= 1

    try:
        os.kill(worker_pid, 0)
        os.kill(worker_pid, signal.SIGKILL)  # tidy up if reaping missed it
    except ProcessLookupError:
        pass


def test_a_finished_loop_is_not_resumable(repo, monkeypatch, capsys):
    """Converged, stopped, or interrupted by hand — all over. Only a loop
    that was killed leaves a ledger that simply stops."""
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
run:
  worker: "echo FIXED > calc.py"
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)
    assert cli.main(["run"]) == cli.EXIT_OK
    capsys.readouterr()

    assert loop.inspect_for_resume(only_loop(repo)) is None
    assert cli.main(["resume"]) == cli.EXIT_CONFIG
    assert "nothing to resume" in capsys.readouterr().err


def test_resume_rebuilds_the_breakers_memory(tmp_path):
    """The signatures are on the ledger precisely so a resumed loop does not
    start blind and re-spend the budget the first life already proved wasted."""
    loop_dir = tmp_path / "20260731-101500-abcd"
    loop_dir.mkdir()
    (loop_dir / loop.EVENTS_FILENAME).write_text(
        "\n".join(
            json.dumps(e)
            for e in [
                {"type": "loop.started", "ts": "t", "loop_id": loop_dir.name},
                {"type": "iteration.started", "ts": "t", "iteration": 1},
                {"type": "verify.finished", "ts": "t", "iteration": 1,
                 "status": "failed", "failure_signature": "aaa",
                 "evidence_dir": "x"},
                {"type": "worker.started", "ts": "t", "iteration": 1,
                 "command": "c"},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    # the pgid is an operational file, not an event: written the instant the
    # worker exists so a SIGKILL still leaves something to reap
    iteration_dir = loop_dir / loop.ITERATIONS_DIRNAME / "001"
    iteration_dir.mkdir(parents=True)
    (iteration_dir / loop.PGID_FILENAME).write_text("4242", encoding="utf-8")

    state = loop.inspect_for_resume(loop_dir)

    assert state is not None
    assert state.iterations_done == 1
    assert state.seen_signatures == frozenset({"aaa"})
    assert state.orphan_pgids == (4242,)


def test_reaping_never_signals_our_own_process_group():
    """A pgid of our own group would kill this very process and its parent.
    The guard is the difference between reaping an orphan and suicide."""
    import os

    mine = os.getpgid(0)

    assert loop.reap_orphans((mine,)) == []
    assert loop.reap_orphans((0, 1)) == []


def test_a_ledger_truncated_mid_write_is_still_readable(tmp_path):
    """A SIGKILL can cut a line in half. Every whole line before it is still
    a fact, and dropping the partial one is the honest recovery."""
    loop_dir = tmp_path / "20260731-101500-abcd"
    loop_dir.mkdir()
    (loop_dir / loop.EVENTS_FILENAME).write_text(
        json.dumps({"type": "loop.started", "ts": "t", "loop_id": "x"})
        + "\n"
        + '{"type": "verify.finished", "iterat',  # killed mid-write
        encoding="utf-8",
    )

    state = loop.inspect_for_resume(loop_dir)

    assert state is not None
    assert state.iterations_done == 0


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


# --- E1: an ACP worker is a worker, including when it is orphaned ----------
#
# `_run_worker` writes `worker.pgid` the instant the shell worker exists, so a
# SIGKILL of the loop still leaves `wring resume` a group to reap.
# `_run_acp_worker` wrote nothing, so an orphaned ACP agent — a real agent
# process, holding a real session, editing a real repo — survived its
# supervisor with nothing recording that it existed. The whole point of
# `wring resume` is the loop that was killed; that is exactly the case where
# the ACP path left no trace.


ACP_HANG = """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
run:
  worker:
    acp:
      command: {command}
      args: [{agent}, "hang"]
  max_iterations: 2
  worker_timeout: 45
"""


def test_an_orphaned_acp_worker_leaves_a_pgid_to_reap(repo):
    """Really SIGKILL a loop whose ACP agent is mid-turn, then check the
    supervisor left something to clean up with."""
    import json as _json
    import os
    import signal
    import subprocess
    import sys

    agent = Path(__file__).resolve().parent / "fake_acp_agent.py"
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        ACP_HANG.format(
            command=_json.dumps(sys.executable), agent=_json.dumps(str(agent))
        ),
        encoding="utf-8",
    )

    proc = subprocess.Popen(
        [sys.executable, "-m", "wringer", "run"],
        cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    # wait for the agent to be mid-turn: the pgid file is written the instant
    # the process exists, which is the property under test
    deadline = time.monotonic() + 30
    written: Path | None = None
    while time.monotonic() < deadline:
        found = sorted(
            (repo / loop.LOOPS_DIRNAME).glob(f"*/iterations/*/{loop.PGID_FILENAME}")
        )
        if found:
            written = found[0]
            break
        time.sleep(0.05)

    try:
        assert written is not None, (
            "an ACP worker was running and the loop recorded no process group "
            "for it — a SIGKILL here leaves an orphaned agent nothing can reap"
        )
        pgid = int(written.read_text(encoding="utf-8").strip())
        assert pgid > 0

        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=30)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()

        resumable = loop.inspect_for_resume(only_loop(repo))
        assert resumable is not None
        assert pgid in resumable.orphan_pgids, (
            f"{pgid} is not in {resumable.orphan_pgids}"
        )
        loop.reap_orphans(resumable.orphan_pgids)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        if written is not None and written.exists():
            try:
                os.killpg(
                    int(written.read_text(encoding="utf-8").strip()), signal.SIGKILL
                )
            except (OSError, ValueError):
                pass


def test_a_finished_acp_worker_leaves_no_stale_pgid(repo, monkeypatch, capsys):
    """The other half of the shell worker's contract: the file goes when the
    worker does, because a stale pgid names a process the OS may since have
    given to somebody else."""
    import json as _json
    import sys

    agent = Path(__file__).resolve().parent / "fake_acp_agent.py"
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        ACP_HANG.format(
            command=_json.dumps(sys.executable), agent=_json.dumps(str(agent))
        ).replace('"hang"', '"fix"'),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_OK
    capsys.readouterr()

    left = sorted(
        (repo / loop.LOOPS_DIRNAME).glob(f"*/iterations/*/{loop.PGID_FILENAME}")
    )
    assert left == [], f"stale pgid files: {left}"
