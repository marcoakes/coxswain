#!/usr/bin/env python3
"""A minimal agent that really speaks ACP, for the test suite.

Not a mock of Wringer's client — a separate process exchanging real
JSON-RPC over stdio, so the tests exercise the wire rather than the author's
idea of the wire. No network, no API key, no vendor binary: CI can run this
anywhere, which is the whole reason it exists.

Behaviour is chosen by argv so one file covers every case the loop needs:

    fix        write the file that makes the gate pass, via fs/write_text_file
    escape     try to write outside the repo (must be refused)
    permission ask for permission, then fix
    idle       do nothing and stop cleanly
    crash      exit mid-turn, before answering the prompt
    loudcrash  say something, THEN exit mid-turn — the shape where the
               agent's last words are the whole diagnostic value
    hang       accept the prompt and never answer
    deaf       answer session/new, then never read stdin again (pipe fills)
    garbage    emit a line that is not JSON, then behave
    leak       print a passed-through credential to stderr AND into a
               session/update, then fix. The shape §8 asks for: a secret
               planted in agent output, so a test can grep the bundle.
"""

from __future__ import annotations

import json
import os
import sys
import time

BEHAVIOUR = sys.argv[1] if len(sys.argv) > 1 else "fix"

# The variables `leak` will echo if they reached it. One matches the
# redactor's default `*KEY*` pattern and one deliberately matches none of
# them, so the two tests can tell the acp.py scrub apart from the
# env_passthrough folding.
LEAKABLE = ("WRINGER_TEST_API_KEY", "WRINGER_TEST_CREDENTIAL")


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def reply(request_id, result: dict) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def request(request_id: int, method: str, params: dict) -> dict:
    """Ask the client something and wait for its answer, ignoring anything
    else that arrives meanwhile."""
    send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)
        if message.get("id") == request_id and (
            "result" in message or "error" in message
        ):
            return message
    return {}


def notify(session_id: str, text: str) -> None:
    send({
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk", "text": text},
        },
    })


def main() -> int:
    if BEHAVIOUR == "garbage":
        sys.stdout.write("this is not json at all\n")
        sys.stdout.flush()

    session_id = "session-1"
    outbound = 1000

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue

        method = message.get("method")
        request_id = message.get("id")

        if method == "initialize":
            reply(request_id, {
                "protocolVersion": 1,
                "agentCapabilities": {},
                "agentInfo": {"name": "fake-acp-agent", "version": "0.0.1"},
            })
        elif method == "session/new":
            if BEHAVIOUR == "crash":
                return 3
            reply(request_id, {"sessionId": session_id})
            if BEHAVIOUR == "deaf":
                # Answer, then stop reading stdin FOREVER. The client's next
                # write fills the pipe buffer and blocks — and that block is
                # armed before any of the turn's deadlines exist, so without a
                # bounded write nothing ever fires. The eight-hour incident's
                # shape, in the seam built to honour its lessons.
                time.sleep(3600)
                return 0
        elif method == "session/prompt":
            if BEHAVIOUR == "hang":
                # accept, then never answer: the client's request timeout and
                # the loop's worker_timeout are what must save us
                while True:
                    line = sys.stdin.readline()
                    if not line:
                        return 0
            notify(session_id, f"working ({BEHAVIOUR})")

            if BEHAVIOUR == "loudcrash":
                notify(session_id, "THE LAST THING THE AGENT SAID")
                sys.stdout.flush()
                return 3

            if BEHAVIOUR == "leak":
                # Both paths acp.py writes: the child's own stderr, which
                # used to be a raw file handle, and a session/update, whose
                # text used to be joined and written unscrubbed.
                for name in LEAKABLE:
                    value = os.environ.get(name)
                    if value:
                        sys.stderr.write(f"stderr says {name}={value}\n")
                        sys.stderr.flush()
                        notify(session_id, f"update says {name}={value}")


            if BEHAVIOUR == "permission":
                outbound += 1
                request(outbound, "session/request_permission", {
                    "sessionId": session_id,
                    "toolCall": {"title": "write calc.py", "kind": "edit"},
                    "options": [
                        {"optionId": "yes", "name": "Allow", "kind": "allow_once"},
                        {"optionId": "no", "name": "Deny", "kind": "reject_once"},
                    ],
                })

            if BEHAVIOUR in ("fix", "permission", "garbage", "leak"):
                outbound += 1
                request(outbound, "fs/write_text_file", {
                    "sessionId": session_id,
                    "path": "calc.py",
                    "content": "FIXED\n",
                })
            elif BEHAVIOUR == "escape":
                outbound += 1
                answer = request(outbound, "fs/write_text_file", {
                    "sessionId": session_id,
                    "path": "../escaped.txt",
                    "content": "should never be written\n",
                })
                notify(session_id, f"refused: {'error' in answer}")

            reply(request_id, {"stopReason": "end_turn"})
            return 0
        elif request_id is not None:
            reply(request_id, {})

    return 0


if __name__ == "__main__":
    sys.exit(main())
