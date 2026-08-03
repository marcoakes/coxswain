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
    listing = (
        "ls -1 .wringer/runs/$(ls -1 .wringer/runs | tail -1)"
    )
    cast: list[dict] = []
    offset = 0.0
    for prompt, command in (
        ("wring run", [wring, "run"]),
        ("ls .wringer/runs/<id>/", ["sh", "-c", listing]),
    ):
        if cast:  # a blank line before each new prompt, as a shell leaves
            cast.append({"at": round(offset, 3), "text": ""})
            offset += 0.05
        cast.append({"at": round(offset, 3), "text": f"$ {prompt}", "prompt": True})
        offset += 0.6
        frames = record(command, scratch, env)
        for frame in frames:
            cast.append({"at": round(offset + frame["at"], 3), "text": frame["text"]})
        offset += (frames[-1]["at"] if frames else 0.0) + 1.4

    out.write_text(json.dumps(cast, indent=1) + "\n", encoding="utf-8")
    print(f"recorded {len(cast)} lines over {cast[-1]['at']:.1f}s -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
