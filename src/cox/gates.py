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
from cox.redact import Redactor

# How long a gate that overran its timeout gets between SIGTERM and SIGKILL.
KILL_GRACE_SECONDS = 2

# The most any single captured stream may contribute to a bundle. A runaway
# gate should not fill the disk, and nobody reads the middle of a 4 GB log.
# The tail is kept, because that is where a failure announces itself.
MAX_LOG_BYTES = 1_048_576

# v0.1 targets macOS and Linux (see pyproject's classifiers). Process groups
# are the mechanism that makes a timeout stick, and they are POSIX-only.
_POSIX = os.name == "posix"

# What wait() reports for a process killed by SIGKILL on POSIX.
_KILLED = -9


@dataclass(frozen=True)
class GateResult:
    gate: Gate
    exit_code: int
    duration_ms: int
    timed_out: bool
    stdout_path: Path
    stderr_path: Path
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    @property
    def truncated(self) -> bool:
        return self.stdout_truncated or self.stderr_truncated

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def status(self) -> str:
        return "passed" if self.passed else "failed"


def run(
    gate: Gate,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    redactor: Redactor | None = None,
) -> GateResult:
    """Run `gate.run` through the shell in `cwd`, capturing its streams.

    `shell=True` is deliberate: gate commands are project-authored shell
    strings (`make lint`, `pytest -q && ruff check .`), not argv vectors.
    Coxswain runs what the repo's own `.cox.yaml` declares — no more
    privilege than the developer typing it.

    The gate gets its own process group (`start_new_session`) so that a
    timeout kills the shell *and* everything it spawned. Killing only the
    shell would leave the real work running against the repo.

    Output travels through a pipe rather than straight to the log file so
    that secrets can be removed *before* anything is written — the spec's
    rule 5. The cost is that a gate's output is held in memory until it
    exits; a gate that emits gigabytes would be a problem, and streaming
    redaction is the v0.2 answer if one ever appears.
    """
    redactor = redactor or Redactor()
    started = time.monotonic()
    proc = subprocess.Popen(
        gate.run,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=_POSIX,
    )
    timed_out = False
    try:
        out, err = proc.communicate(timeout=gate.timeout)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = _terminate(proc)
        # Drain whatever the gate managed to say before it was stopped —
        # the last lines before a hang are usually the interesting ones.
        out, err = proc.communicate()
    except KeyboardInterrupt:
        # The gate runs in its own process group, so Ctrl-C reached cox and
        # not the gate: stopping it is our job, or it outlives the verifier.
        _terminate(proc)
        out, err = proc.communicate()
        _write_logs(stdout_path, stderr_path, out, err, redactor)
        raise

    out_cut, err_cut = _write_logs(stdout_path, stderr_path, out, err, redactor)

    return GateResult(
        gate=gate,
        exit_code=exit_code,
        duration_ms=int((time.monotonic() - started) * 1000),
        timed_out=timed_out,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        stdout_truncated=out_cut,
        stderr_truncated=err_cut,
    )


def _write_logs(
    stdout_path: Path,
    stderr_path: Path,
    out: bytes,
    err: bytes,
    redactor: Redactor,
) -> tuple[bool, bool]:
    """Scrub, bound, write. In that order: truncation must never be what
    saves a secret, and the limit applies to the redacted text."""
    out_data, out_cut = truncate(redactor.scrub_bytes(out), MAX_LOG_BYTES)
    err_data, err_cut = truncate(redactor.scrub_bytes(err), MAX_LOG_BYTES)
    stdout_path.write_bytes(out_data)
    stderr_path.write_bytes(err_data)
    return out_cut, err_cut


def truncate(data: bytes, limit: int) -> tuple[bytes, bool]:
    """Keep the last `limit` bytes, announcing what was dropped.

    The note goes in the file itself: a reader must never mistake a bounded
    log for a complete one, and a bundle that quietly loses evidence is
    worse than one that admits it.
    """
    if len(data) <= limit:
        return data, False
    dropped = len(data) - limit
    note = f"[cox: {dropped} earlier bytes dropped, keeping the last {limit}]\n"
    return note.encode() + data[-limit:], True


def _terminate(proc: subprocess.Popen) -> int:
    """Ask the gate to stop, then make it stop.

    Returns the wait status — negative when a signal ended the process,
    which is the honest thing to record next to `timed_out: true`.
    """
    for hard in (False, True):
        try:
            _stop(proc, hard=hard)
        except (ProcessLookupError, PermissionError):
            pass  # already gone, but still needs reaping
        try:
            return proc.wait(timeout=KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            continue
    # Unreapable even after a hard kill: report it rather than hang the
    # verifier waiting on a process the OS will not surrender.
    return proc.returncode if proc.returncode is not None else _KILLED


def _stop(proc: subprocess.Popen, hard: bool) -> None:
    """Signal the gate — its whole process group where the OS has them.

    Off POSIX there is no group to signal, so a gate that spawned children
    can leave them behind after a timeout. That is a v0.2 problem, and a
    declared one: v0.1 supports macOS and Linux.
    """
    if not _POSIX:
        if hard:
            proc.kill()
        else:
            proc.terminate()
        return
    os.killpg(
        os.getpgid(proc.pid), signal.SIGKILL if hard else signal.SIGTERM
    )
