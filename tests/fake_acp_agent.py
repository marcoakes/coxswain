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
    hang       accept the prompt and never answer
    garbage    emit a line that is not JSON, then behave
"""

from __future__ import annotations

import json
import sys

BEHAVIOUR = sys.argv[1] if len(sys.argv) > 1 else "fix"


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
        elif method == "session/prompt":
            if BEHAVIOUR == "hang":
                # accept, then never answer: the client's request timeout and
                # the loop's worker_timeout are what must save us
                while True:
                    line = sys.stdin.readline()
                    if not line:
                        return 0
            notify(session_id, f"working ({BEHAVIOUR})")

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

            if BEHAVIOUR in ("fix", "permission", "garbage"):
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
