"""The gate runner: stream capture, timing, timeout enforcement."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from cox import gates
from cox.config import Gate


def execute(command: str, where: Path, timeout: int = 120) -> gates.GateResult:
    """Run `command` as a gate, logging into `where`."""
    return gates.run(
        Gate(id="probe", run=command, timeout=timeout),
        cwd=where,
        stdout_path=where / "stdout.log",
        stderr_path=where / "stderr.log",
    )


def test_passing_gate_records_a_clean_result(tmp_path: Path):
    result = execute("true", tmp_path)

    assert result.exit_code == 0
    assert result.passed is True
    assert result.timed_out is False
    assert result.status == "passed"
    # both logs are always created, even when the gate says nothing
    assert result.stdout_path.read_bytes() == b""
    assert result.stderr_path.read_bytes() == b""


def test_failing_gate_keeps_the_real_exit_code(tmp_path: Path):
    result = execute("exit 3", tmp_path)

    assert result.exit_code == 3
    assert result.passed is False
    assert result.status == "failed"


def test_streams_are_captured_to_separate_files(tmp_path: Path):
    result = execute("printf 'to-out\\n'; printf 'to-err\\n' >&2", tmp_path)

    assert result.stdout_path.read_text(encoding="utf-8") == "to-out\n"
    assert result.stderr_path.read_text(encoding="utf-8") == "to-err\n"


def test_gate_output_never_reaches_the_console(tmp_path: Path, capfd):
    execute("echo loud-stdout; echo loud-stderr >&2", tmp_path)

    captured = capfd.readouterr()
    assert "loud-stdout" not in captured.out
    assert "loud-stderr" not in captured.err


def test_gate_runs_in_the_given_directory(tmp_path: Path):
    workdir = tmp_path / "repo"
    workdir.mkdir()

    result = execute("pwd", workdir)

    recorded = result.stdout_path.read_text(encoding="utf-8").strip()
    assert Path(recorded).resolve() == workdir.resolve()


def test_duration_is_recorded_in_milliseconds(tmp_path: Path):
    result = execute("sleep 0.2", tmp_path)

    assert result.duration_ms >= 150
    assert result.duration_ms < 5000


def test_a_short_log_is_written_whole(tmp_path: Path):
    result = execute("echo small", tmp_path)

    assert result.stdout_truncated is False
    assert result.truncated is False
    assert result.stdout_path.read_text(encoding="utf-8") == "small\n"


def test_an_oversized_log_keeps_the_tail_and_says_so(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gates, "MAX_LOG_BYTES", 64)

    result = execute("for i in $(seq 1 200); do echo line-$i; done", tmp_path)

    assert result.stdout_truncated is True
    assert result.truncated is True
    written = result.stdout_path.read_text(encoding="utf-8")
    assert written.startswith("[cox: ")
    assert "earlier bytes dropped" in written
    # the end of the log — where a failure announces itself — survives
    assert "line-200" in written
    assert "line-1\n" not in written


def test_truncate_leaves_short_data_untouched():
    assert gates.truncate(b"short", 64) == (b"short", False)


def test_truncate_reports_what_it_dropped():
    data, cut = gates.truncate(b"0123456789", 4)

    assert cut is True
    assert data.endswith(b"6789")
    assert b"6 earlier bytes dropped" in data


def test_timeout_stops_the_gate_and_is_recorded(tmp_path: Path):
    result = execute("sleep 30", tmp_path, timeout=1)

    assert result.timed_out is True
    assert result.passed is False
    assert result.status == "failed"
    # ended by a signal, not by finishing
    assert result.exit_code < 0
    # waited for the timeout, not for the command
    assert 1000 <= result.duration_ms < 10_000


def test_timeout_kills_what_the_gate_spawned(tmp_path: Path):
    """The shell gets its own process group so children die with it.

    Killing only the shell would leave the real work running against the
    repo after `cox verify` has already reported.
    """
    marker = tmp_path / "child.pid"
    result = execute(f"sleep 30 & echo $! > {marker}; wait", tmp_path, timeout=1)

    assert result.timed_out is True
    child = int(marker.read_text(encoding="utf-8").strip())

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            return  # reaped — the whole group went down
        time.sleep(0.05)
    pytest.fail(f"spawned process {child} survived the gate timeout")
