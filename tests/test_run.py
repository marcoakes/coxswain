"""`wring run` — the repair loop, driven by scripted workers.

Every "worker" here is a shell one-liner. The loop's contract is about what
it does with a worker's *effects*, not about intelligence, so nothing in this
file needs an LLM — and a test suite that needed one would be untestable in
CI and expensive everywhere else.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import flat

from wringer import cli, evidence, loop

# A gate that passes only once calc.py has been fixed.
CHECKS = """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
run:
  worker: {worker}
  max_iterations: {max_iterations}
"""


def write_loop_config(repo: Path, worker: str, max_iterations: int = 3) -> None:
    # json.dumps gives a double-quoted YAML scalar, so a worker like `true`
    # stays the *string* "true" rather than becoming a boolean.
    (repo / ".wringer.yaml").write_text(
        CHECKS.format(worker=json.dumps(worker), max_iterations=max_iterations),
        encoding="utf-8",
    )


def broken(repo: Path) -> None:
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")


def only_loop(repo: Path) -> Path:
    loops = sorted((repo / loop.LOOPS_DIRNAME).iterdir())
    assert len(loops) == 1, loops
    return loops[0]


def events(loop_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (loop_dir / loop.EVENTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def types(loop_dir: Path) -> list[str]:
    return [event["type"] for event in events(loop_dir)]


def manifest(loop_dir: Path) -> dict:
    return json.loads((loop_dir / loop.MANIFEST_FILENAME).read_text(encoding="utf-8"))


def test_the_fingerprint_ignores_wringers_own_evidence(repo):
    """Every verify writes a bundle. If Wringer's own output counted as a
    change, the tree would look different on every lap and no worker would
    ever be found idle."""
    before = loop.fingerprint(repo)

    written = repo / evidence.RUNS_DIRNAME / "20260731-000000-aaaa"
    written.mkdir(parents=True)
    (written / "manifest.json").write_text("{}", encoding="utf-8")

    assert loop.fingerprint(repo) == before


def test_the_fingerprint_notices_what_a_worker_would_change(repo):
    before = loop.fingerprint(repo)

    (repo / "calc.py").write_text("the worker was here\n", encoding="utf-8")

    assert loop.fingerprint(repo) != before


def test_a_worker_that_fixes_it_converges(repo, monkeypatch, capsys):
    broken(repo)
    write_loop_config(repo, "echo FIXED > calc.py")
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_OK

    loop_dir = only_loop(repo)
    assert manifest(loop_dir)["result"] == {
        "status": "converged",
        "reason": "converged",
        "iterations": 2,
        "final_run": manifest(loop_dir)["result"]["final_run"],
    }
    assert types(loop_dir) == [
        "loop.started",
        "iteration.started",
        "verify.finished",
        "worker.started",
        "worker.finished",
        "iteration.started",
        "verify.finished",
        "loop.finished",
    ]
    # a real verify bundle per iteration, indistinguishable from a manual one
    assert len(list((repo / evidence.RUNS_DIRNAME).iterdir())) == 2
    assert "Converged in 2 iterations." in capsys.readouterr().out


def test_a_worker_that_never_fixes_it_runs_out_of_iterations(
    repo, monkeypatch, capsys
):
    broken(repo)
    # The gate echoes the file, so each lap fails *differently* and the
    # breaker (which stops repeated failure shapes) stays out of the way —
    # this test is about the iteration budget, not about oscillation.
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

    loop_dir = only_loop(repo)
    result = manifest(loop_dir)["result"]
    assert result["status"] == "stopped"
    assert result["reason"] == "max_iterations"
    assert result["iterations"] == 3
    assert types(loop_dir).count("verify.finished") == 3
    # the last iteration is not briefed or worked — the budget is spent
    assert types(loop_dir).count("worker.finished") == 2
    assert "the budget ran out" in capsys.readouterr().out


def test_a_worker_that_changes_nothing_stops_without_a_second_verify(
    repo, monkeypatch, capsys
):
    """An identical tree gives an identical result; running the gates again
    to prove it would be theatre."""
    broken(repo)
    write_loop_config(repo, "true", max_iterations=5)
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_GATE_FAILED

    loop_dir = only_loop(repo)
    result = manifest(loop_dir)["result"]
    assert result["reason"] == "no_progress"
    # exactly two verifications: the first, and the one that caught the
    # unchanged tree. Not five.
    assert types(loop_dir).count("verify.finished") == 2
    assert types(loop_dir).count("worker.finished") == 1
    assert "changed nothing" in capsys.readouterr().out


def test_the_evidence_decides_not_the_workers_exit_code(repo, monkeypatch, capsys):
    """A worker that fixed the bug and then fell over has still fixed the
    bug. Its opinion of itself is not evidence."""
    broken(repo)
    write_loop_config(repo, "echo FIXED > calc.py; exit 7")
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_OK

    loop_dir = only_loop(repo)
    assert manifest(loop_dir)["result"]["status"] == "converged"
    finished = [e for e in events(loop_dir) if e["type"] == "worker.finished"]
    assert finished[0]["exit_code"] == 7  # recorded, not acted on
    capsys.readouterr()


def test_a_worker_that_overruns_is_killed_and_the_loop_continues(
    repo, monkeypatch, capsys
):
    broken(repo)
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
run:
  worker: "sleep 30"
  max_iterations: 2
  worker_timeout: 1
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    started = time.monotonic()
    assert cli.main(["run"]) == cli.EXIT_GATE_FAILED
    elapsed = time.monotonic() - started

    assert elapsed < 25, f"the worker's timeout did not stick ({elapsed:.1f}s)"
    loop_dir = only_loop(repo)
    finished = [e for e in events(loop_dir) if e["type"] == "worker.finished"]
    assert finished and finished[0]["timed_out"] is True
    # it slept rather than editing, so the tree is unchanged
    assert manifest(loop_dir)["result"]["reason"] == "no_progress"
    assert "timed out" in capsys.readouterr().out


def test_a_missing_run_section_is_a_config_error(
    repo, write_config, monkeypatch, capsys
):
    write_config(
        repo,
        """\
version: 1
gates:
  - id: test
    run: "true"
""",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_CONFIG

    err = flat(capsys.readouterr().err)
    assert "no 'run:' section" in err
    assert "never one it guessed" in err
    assert not (repo / loop.LOOPS_DIRNAME).exists()


def test_run_outside_a_repository_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert cli.main(["run"]) == cli.EXIT_CONFIG

    assert "not a git repository" in capsys.readouterr().err


def test_run_refuses_mid_merge(repo, git_run, monkeypatch, capsys):
    broken(repo)
    write_loop_config(repo, "true")
    git_run(repo, "add", "-A")
    git_run(repo, "commit", "-q", "-m", "base")
    git_run(repo, "checkout", "-q", "-b", "other")
    (repo / "calc.py").write_text("THEIRS\n", encoding="utf-8")
    git_run(repo, "commit", "-qam", "theirs")
    git_run(repo, "checkout", "-q", "main")
    (repo / "calc.py").write_text("OURS\n", encoding="utf-8")
    git_run(repo, "commit", "-qam", "ours")
    git_run(repo, "merge", "other", check=False)
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_REFUSED

    assert "in the middle of a merge" in capsys.readouterr().err


@pytest.mark.parametrize(
    "worker, expected_status, expected_reason",
    [
        ("echo FIXED > calc.py", "converged", "converged"),
        ("true", "stopped", "no_progress"),
    ],
)
def test_json_keys_are_stable(
    repo, monkeypatch, capfd, worker, expected_status, expected_reason
):
    broken(repo)
    write_loop_config(repo, worker)
    monkeypatch.chdir(repo)

    cli.main(["run", "--json"])

    payload = json.loads(capfd.readouterr().out)
    assert set(payload) == {"status", "reason", "iterations", "loop_dir", "final"}
    assert payload["status"] == expected_status
    assert payload["reason"] == expected_reason
    assert set(payload["final"]) == {
        "status",
        "failed_gate",
        "rerun",
        "evidence_dir",
    }


def test_max_iterations_can_be_overridden(repo, monkeypatch, capsys):
    broken(repo)
    write_loop_config(repo, "date +%s%N >> calc.py", max_iterations=9)
    monkeypatch.chdir(repo)

    assert cli.main(["run", "--max-iterations", "2"]) == cli.EXIT_GATE_FAILED

    assert manifest(only_loop(repo))["result"]["iterations"] == 2
    capsys.readouterr()


def test_a_secret_never_reaches_the_workers_log(repo, monkeypatch, capsys):
    broken(repo)
    write_loop_config(repo, "echo $MY_TOKEN; echo FIXED > calc.py")
    monkeypatch.setenv("MY_TOKEN", "hushhush12345")
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_OK

    log = (
        only_loop(repo) / loop.ITERATIONS_DIRNAME / "001" / "worker.stdout.log"
    ).read_text(encoding="utf-8")
    assert "hushhush12345" not in log
    assert "[REDACTED]" in log
    capsys.readouterr()


def test_the_brief_carries_the_json_and_the_failing_output(repo, monkeypatch, capsys):
    broken(repo)
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "echo the-planted-failure >&2; grep -q FIXED calc.py"
run:
  worker: "cp {brief} captured-brief.md; echo FIXED > calc.py"
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_OK

    # the worker was handed a real path it could read
    brief = (repo / "captured-brief.md").read_text(encoding="utf-8")
    assert '"failed_gate": "test"' in brief
    assert "the-planted-failure" in brief
    assert "wring verify --gate test" in brief
    assert "Do not edit anything under `.wringer/`" in brief
    capsys.readouterr()


def test_a_real_sigint_stops_the_loop_and_the_worker(repo):
    """Ctrl-C during a worker's turn: exit 4, the worker's process group
    dies with it, and the bundle admits where it stopped."""
    broken(repo)
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
run:
  worker: "echo $$ > worker.pid; sleep 30"
  worker_timeout: 60
""",
        encoding="utf-8",
    )

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

    proc.send_signal(signal.SIGINT)
    proc.communicate(timeout=30)
    assert proc.returncode == cli.EXIT_INTERRUPTED

    worker_pid = int(pid_file.read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            import os

            os.kill(worker_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"worker {worker_pid} survived the interrupt")

    loop_dir = only_loop(repo)
    result = manifest(loop_dir)["result"]
    assert result["status"] == "interrupted"
    recorded = types(loop_dir)
    # started and never finished — the honest record of a killed worker
    assert recorded.count("worker.started") == 1
    assert recorded.count("worker.finished") == 0
    assert recorded[-1] == "loop.finished"
