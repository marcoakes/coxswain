"""Run a gate's command and time it.

Day 1 runs a single gate with its output streaming straight to the
console. Capturing per-gate `stdout.log`/`stderr.log`, enforcing the
config's `timeout`, and sequencing gates with stop-on-first-required-
failure are the Day-2 bolt.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from cox.config import Gate


@dataclass(frozen=True)
class GateResult:
    gate: Gate
    exit_code: int
    duration_ms: int

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


def run(gate: Gate, cwd: Path) -> GateResult:
    """Run `gate.run` through the shell in `cwd`, inheriting stdio.

    `shell=True` is deliberate: gate commands are project-authored shell
    strings (`make lint`, `pytest -q && ruff check .`), not argv vectors.
    Coxswain runs what the repo's own `.cox.yaml` declares — no more
    privilege than the developer typing it.
    """
    started = time.monotonic()
    proc = subprocess.run(gate.run, shell=True, cwd=cwd)
    duration_ms = int((time.monotonic() - started) * 1000)
    return GateResult(
        gate=gate, exit_code=proc.returncode, duration_ms=duration_ms
    )
