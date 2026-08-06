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


# The agent `wring start` is told to use in the recording. A real id from
# Wringer's own table — `tests/test_docs.py` asserts that — but the binary
# behind it during the recording is a STUB that `scripts/demo.sh` puts on
# PATH. That is the only route that films the agent step without installing a
# vendor binary or handling a credential, and the documentation says so in
# words beside the picture. The launch never runs it: the gates pass on the
# first try, so there is nothing for a repair loop to do.
START_AGENT_ID = "claude-code"


def _argv_step(wring: str, *args: str) -> tuple[str, list[str]]:
    """A step whose displayed command IS its argv.

    Displayed and executed differ in exactly one thing — argv[0] is the
    absolute path to the `wring` being recorded — and `tests/test_docs.py`
    checks that is the only difference. `_listing_step` earned that guard the
    hard way: the cast showed one command and ran another for two days.
    """
    return " ".join(("wring", *args)), [wring, *args]


def _run_step(wring: str, scratch: Path) -> tuple[str, list[str]]:
    return _argv_step(wring, "run")


def _start_step(wring: str, scratch: Path) -> tuple[str, list[str]]:
    """The guided launch, non-interactively.

    **The recorded run is the non-interactive surface, and that is measured
    rather than chosen** (SPEC_START_V0.md §3b-i). This recorder cannot film
    an interactive session: `getpass` reads `/dev/tty` rather than stdin and
    would block on the operator's real terminal; child stdin is DEVNULL; and
    capture is line-oriented, so a prompt printed without a trailing newline
    is glued onto whatever line comes next — a plausible-looking line no
    command ever printed, which is worse for law 8 than an absence.

    It is also the documented happy path: the north-star flow has an agent
    running setup and launching `wring start` at the end, and an agent passes
    flags.

    The key step is deliberately off-camera. The recorded run has the variable
    already set, `wring start` says so on the terminal, and the docs say in
    words that the one step a film cannot honestly show is the one where a
    human types a secret.
    """
    return _argv_step(wring, "start", "--accept-gates", "--agent", START_AGENT_ID)


def _prove_step(wring: str, scratch: Path) -> tuple[str, list[str]]:
    """The catch.

    `wring run` has just converged: gates green, worker done, a confident
    ending. This re-runs those same gates against the PRE-CHANGE tree in a
    scratch worktree. A gate that passes on both proved nothing about the
    change — and that is the verdict this recording exists to show.
    """
    return _argv_step(wring, "verify", "--prove")


def _deliver_step(wring: str, scratch: Path) -> tuple[str, list[str]]:
    """The consequence. A `gates_vacuous` bundle is refused, exit 1.

    Recorded last because a refusal is only meaningful once the reader has
    watched the thing it is refusing look fine.
    """
    return _argv_step(wring, "deliver")


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


# Which commands each recording films. `main()` iterates one of these, so a
# new recorded command needs an entry — that is the expected shape, and it is
# not new *capability*: no pty driving and no keystroke injection, which is
# what would put synthesised input into a file law 8 forbids editing.
STEP_SETS = {
    "run": (_run_step, _listing_step),
    "start": (_start_step,),
    # The agent lies, Wringer catches it: converge, prove, refuse.
    "vacuous": (_run_step, _prove_step, _deliver_step),
}


def main() -> int:
    scratch = Path(sys.argv[1])
    out = Path(sys.argv[2])
    wring = sys.argv[3]
    steps = STEP_SETS[sys.argv[4] if len(sys.argv) > 4 else "run"]

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
    for step in steps:
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
