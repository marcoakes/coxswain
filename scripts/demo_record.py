"""Record a real terminal session as a cast of (elapsed, line) pairs.

There is no asciinema on the maintainer's Mac, and the alternative — writing
an SVG that *depicts* what Wringer would print — is exactly the thing this
repository exists to refuse. So this runs the real commands, through a real
pty, and records what actually came back and when.

The cast is committed beside the SVG it renders, so anyone can check the
picture against the transcript, and `scripts/demo.sh` regenerates both.
"""

from __future__ import annotations

import json
import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path

# The grid the cast's timeline snaps to, in seconds.
#
# Pacing is presentation; captured OUTPUT is evidence. Quantizing `at` never
# touches a single character of `text`, so law 8 is untouched — what the
# commands printed is exactly what they printed. What it removes is the
# churn: every regeneration used to rewrite 19 of 20 float timings and every
# derived SVG keyframe, so a diff could not be read for whether the DEMO had
# changed. A tenth of a second is below the threshold anyone perceives in a
# terminal recording and above the jitter of a loaded machine.
#
# It does not make regeneration byte-identical, and is not meant to: the run
# id and the `0.1s` gate durations live inside captured text and stay real.
# Regeneration is a deliberate act, done when the flow changes.
TIMING_QUANTUM = 0.1


def _run_step(wring: str, scratch: Path) -> tuple[str, list[str]]:
    return "wring run", [wring, "run"]


def _listing_step(wring: str, scratch: Path) -> tuple[str, list[str]]:
    """The receipts listing — displayed and executed as ONE string.

    They used to differ. The cast displayed `ls .wringer/runs/<id>/` while
    what actually ran was
    `ls -1 .wringer/runs/$(ls -1 .wringer/runs | tail -1)`. A viewer who typed
    what they saw got columnated output, not the one-per-line listing the
    recording shows — a transcript of a command nobody ran, which is the
    law-8 failure this project keeps finding in itself. A review flagged it on
    2026-08-03 and it was still there two days later, because nothing tested
    it. `tests/test_docs.py` does now.

    Called AFTER `wring run`, so the run id it names is the one that run just
    created — which is what makes the displayed command literal and runnable
    rather than a placeholder.
    """
    runs = scratch / ".wringer" / "runs"
    names = (
        sorted(p.name for p in runs.iterdir() if p.is_dir())
        if runs.is_dir()
        else []
    )
    if not names:
        raise SystemExit(
            "demo_record: no run directory to list — `wring run` wrote none, "
            "so there are no receipts to show"
        )
    listing = f"ls -1 .wringer/runs/{names[-1]}/"
    return listing, ["sh", "-c", listing]


def quantize(cast: list[dict], quantum: float = TIMING_QUANTUM) -> list[dict]:
    """Snap every `at` to the grid, leaving `text` untouched.

    Monotonic by construction: rounding is order-preserving, so a frame never
    lands before the one it followed.
    """
    return [
        {**frame, "at": round(round(frame["at"] / quantum) * quantum, 3)}
        for frame in cast
    ]


def record(command: list[str], cwd: Path, env: dict[str, str]) -> list[dict]:
    """Run `command` under a pty and timestamp every line it prints."""
    primary, secondary = pty.openpty()
    started = time.monotonic()
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=secondary,
        stderr=secondary,
        close_fds=True,
    )
    os.close(secondary)

    frames: list[dict] = []
    buffer = b""
    while True:
        ready, _, _ = select.select([primary], [], [], 0.1)
        if ready:
            try:
                chunk = os.read(primary, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                raw, buffer = buffer.split(b"\n", 1)
                frames.append(
                    {
                        "at": round(time.monotonic() - started, 3),
                        "text": raw.decode("utf-8", errors="replace").rstrip("\r"),
                    }
                )
        elif proc.poll() is not None:
            break

    if buffer.strip():
        frames.append(
            {
                "at": round(time.monotonic() - started, 3),
                "text": buffer.decode("utf-8", errors="replace").rstrip("\r"),
            }
        )
    os.close(primary)
    proc.wait(timeout=30)
    return frames


def main() -> int:
    scratch = Path(sys.argv[1])
    out = Path(sys.argv[2])
    wring = sys.argv[3]

    env = dict(os.environ)
    env["PATH"] = f"{Path(wring).parent}:{env['PATH']}"
    # Deterministic width so the SVG's line lengths are the real ones.
    env["COLUMNS"] = "78"

    # Deliberately NOT `wring verify` first. Its failure dump is twenty lines
    # of pytest arriving in one burst — true, but a wall rather than a demo,
    # and the README already carries that transcript as a static block. The
    # loop is the thing that paces: fail, hand to the worker, pass, converge.
    # Then the receipts, because "it converged" is a claim and the bundle is
    # the evidence.
    #
    # Built lazily, one step at a time: the second command names the run id
    # the FIRST command creates, so the list cannot be computed up front.
    cast: list[dict] = []
    offset = 0.0
    for step in (_run_step, _listing_step):
        prompt, command = step(wring, scratch)
        if cast:  # a blank line before each new prompt, as a shell leaves
            cast.append({"at": round(offset, 3), "text": ""})
            offset += 0.05
        cast.append({"at": round(offset, 3), "text": f"$ {prompt}", "prompt": True})
        offset += 0.6
        frames = record(command, scratch, env)
        for frame in frames:
            cast.append({"at": round(offset + frame["at"], 3), "text": frame["text"]})
        offset += (frames[-1]["at"] if frames else 0.0) + 1.4

    cast = quantize(cast)
    out.write_text(json.dumps(cast, indent=1) + "\n", encoding="utf-8")
    print(f"recorded {len(cast)} lines over {cast[-1]['at']:.1f}s -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
