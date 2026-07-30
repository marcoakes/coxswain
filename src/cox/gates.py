"""Run a gate's command: timed, timeout-enforced, streams captured.

Every command gets stdout, stderr, an exit code, a duration and a timeout
status (SPEC_COX_VERIFY_V0.md §Config design, rule 4). The streams go to
files, not the console: the bundle is the product, and `cox verify` exists
to replace scrollback rather than reproduce it.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from cox.config import Gate

# How long a gate that overran its timeout gets between SIGTERM and SIGKILL.
KILL_GRACE_SECONDS = 2


@dataclass(frozen=True)
class GateResult:
    gate: Gate
    exit_code: int
    duration_ms: int
    timed_out: bool
    stdout_path: Path
    stderr_path: Path

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def status(self) -> str:
        return "passed" if self.passed else "failed"


def run(
    gate: Gate, cwd: Path, stdout_path: Path, stderr_path: Path
) -> GateResult:
    """Run `gate.run` through the shell in `cwd`, capturing its streams.

    `shell=True` is deliberate: gate commands are project-authored shell
    strings (`make lint`, `pytest -q && ruff check .`), not argv vectors.
    Coxswain runs what the repo's own `.cox.yaml` declares — no more
    privilege than the developer typing it.

    The gate gets its own process group (`start_new_session`) so that a
    timeout kills the shell *and* everything it spawned. Killing only the
    shell would leave the real work running against the repo, still
    writing into a log file we have already closed.
    """
    started = time.monotonic()
    with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
        proc = subprocess.Popen(
            gate.run,
            shell=True,
            cwd=cwd,
            stdout=out,
            stderr=err,
            start_new_session=True,
        )
        timed_out = False
        try:
            exit_code = proc.wait(timeout=gate.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = _terminate(proc)

    return GateResult(
        gate=gate,
        exit_code=exit_code,
        duration_ms=int((time.monotonic() - started) * 1000),
        timed_out=timed_out,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )


def _terminate(proc: subprocess.Popen) -> int:
    """SIGTERM the gate's process group, SIGKILL whatever survives.

    Returns the wait status — negative when a signal ended the process,
    which is the honest thing to record next to `timed_out: true`.
    """
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError):
            pass  # already gone, but still needs reaping
        try:
            return proc.wait(timeout=KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            continue
    # Unreapable even after SIGKILL: report the kill rather than hang the
    # verifier waiting on a process the OS will not surrender.
    return -signal.SIGKILL
