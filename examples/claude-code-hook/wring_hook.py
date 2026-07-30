#!/usr/bin/env python3
"""Put a coding agent's edits through the wringer, every time.

A Claude Code `PostToolUse` hook: after the agent edits a file, run the
repo's declared gates and hand the agent back the structured result and the
diagnosis. When every gate passes it says nothing.

This is the v0.1 shape of the loop `wring run` will own in v0.2 — the agent
is the worker, `wring verify` is the gate, and the evidence bundle is what
both of them argue from. Nothing here calls an LLM or uploads anything; the
hook only reads what `wring` already wrote to disk.

Control flow follows Wringer's exit codes, which are contract
(SPEC_VERIFY_V0.md): 0 passed - 1 a required gate failed - 2 config or
environment error - 3 refused (unsafe tree) - 4 interrupted.

Feedback follows Claude Code's hook contract: a PostToolUse hook **cannot
block** — the tool has already run — so the way to reach the model is
`hookSpecificOutput.additionalContext` on stdout with exit 0, not a non-zero
exit. A non-zero exit here would only print a line at the human.

Stdlib only. Install: see README.md beside this file.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

# Wringer's exit codes.
PASSED = 0
GATE_FAILED = 1

CANNOT_RUN = {
    2: "Config or environment error — check .wringer.yaml.",
    3: "Refused: the tree is mid-merge, mid-rebase, or otherwise unsafe.",
    4: "Interrupted before it finished.",
}

# A gate set worth running after a single edit. Empty means every declared
# gate. A repo whose suite takes five minutes should set this to its fast
# gate (WRINGER_HOOK_GATES=lint) and leave the full run to a Stop hook or CI:
# a hook that makes every edit expensive gets switched off, and a hook that is
# switched off proves nothing.
GATES_ENV = "WRINGER_HOOK_GATES"

# How much of the diagnosis to pass on. `wring explain` is already compact;
# this is a backstop against a gate that prints a novel.
MAX_CONTEXT_CHARS = 6000


def main() -> int:
    payload = _read_payload()
    cwd = payload.get("cwd") or os.getcwd()

    # Opt-in: no declared gates, nothing to prove.
    if not os.path.isfile(os.path.join(cwd, ".wringer.yaml")):
        return 0

    # A missing `wring` is not the agent's problem, and must not stall a
    # session that never asked for it.
    wring = shutil.which("wring")
    if wring is None:
        return 0

    verify = _run([wring, "verify", "--json", *_gate_args()], cwd)
    if verify is None or verify.returncode == PASSED:
        # Silence on success is deliberate: a hook that speaks when there is
        # no news teaches the reader to skip it.
        return 0

    if verify.returncode == GATE_FAILED:
        _emit(_context(verify.stdout.strip(), wring, cwd))
        return 0

    note = CANNOT_RUN.get(verify.returncode, "Unexpected failure.")
    print(
        f"wring verify could not run (exit {verify.returncode}). {note}",
        file=sys.stderr,
    )
    return 1


def _read_payload() -> dict:
    """The hook payload on stdin. Absent or malformed is survivable — the
    only field wanted is `cwd`, and os.getcwd() stands in for it."""
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, OSError):
        return {}


def _gate_args() -> list[str]:
    gates = os.environ.get(GATES_ENV, "").split()
    return [part for gate in gates for part in ("--gate", gate)]


def _run(argv: list[str], cwd: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    except OSError:
        return None


def _context(result_json: str, wring: str, cwd: str) -> str:
    """What the agent is told: the machine-readable verdict, then the
    diagnosis `wring explain` already knows how to write."""
    lines = [
        "`wring verify` failed — this change is not mergeable yet.",
        "",
        "Structured result:",
        result_json,
    ]

    explain = _run([wring, "explain"], cwd)
    if explain is not None and explain.returncode == 0 and explain.stdout.strip():
        lines += ["", explain.stdout.rstrip()]

    lines += [
        "",
        "Fix the failure above, then continue. The whole evidence bundle is on "
        "disk at the evidence_dir named in the structured result — read it "
        "rather than guessing at what broke.",
    ]

    context = "\n".join(lines)
    if len(context) > MAX_CONTEXT_CHARS:
        kept = context[-MAX_CONTEXT_CHARS:]
        context = f"[earlier output trimmed]\n{kept}"
    return context


def _emit(context: str) -> None:
    """Exit 0 plus this object is how a PostToolUse hook reaches the model;
    stderr and a non-zero exit only reach the human."""
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": context,
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    sys.exit(main())
