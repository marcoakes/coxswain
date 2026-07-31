"""Speak the Agent Client Protocol to a worker (SPEC_ACP_V0.md).

**Wringer is an ACP client. It is never the agent.** That distinction is the
neutrality position in one sentence: Wringer supervises, somebody else's
agent writes the code, and swapping which agent becomes a config line rather
than a rewrite.

The wire is JSON-RPC 2.0 over the child's stdin/stdout, newline-delimited.
Method names are the protocol's, verified against its published schema:
`initialize`, `session/new`, `session/prompt`, and the agent-to-client
`session/update`, `fs/read_text_file`, `fs/write_text_file`,
`session/request_permission`.

One session per iteration. A fresh context each lap is what keeps the loop's
evidence honest — a long-lived conversation drifts, and then the ledger
describes something other than what was tried.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = 1

# What Wringer, as a client, offers the agent. Terminal is deliberately
# absent in v0: an agent that wants to run commands can do it through the
# gates a repo already declared, which is the part that gets verified.
CLIENT_CAPABILITIES = {"fs": {"readTextFile": True, "writeTextFile": True}}

# A ceiling on any single request, for the case where a turn has no deadline
# of its own. The TURN's deadline — `worker_timeout` from the repo's config —
# always wins when it is nearer, because the number a repo wrote down must be
# the number that binds. Getting this wrong made a `worker_timeout: 2` agent
# hang for two minutes.
REQUEST_TIMEOUT_SECONDS = 120


class AcpError(Exception):
    """The agent could not be spoken to. Recorded as a failed worker turn —
    never as a verdict about the code."""


@dataclass
class Turn:
    """What one session produced, for the ledger."""

    stop_reason: str = "unknown"
    timed_out: bool = False
    agent_name: str = ""
    agent_version: str = ""
    protocol_version: int = 0
    updates: list[str] = field(default_factory=list)
    permissions: list[dict[str, Any]] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)


class Connection:
    """A JSON-RPC peer on a subprocess's stdio.

    Reading happens on a thread because the exchange is bidirectional: while
    Wringer waits for a `session/prompt` response, the agent is sending
    notifications and making its own requests, and a naive read loop would
    deadlock the moment both sides spoke at once.
    """

    def __init__(self, proc: subprocess.Popen, deadline: float | None = None) -> None:
        self._proc = proc
        # Absolute monotonic time the whole turn must end by.
        self._deadline = deadline
        self._next_id = 0
        self._responses: dict[int, dict] = {}
        self._lock = threading.Lock()
        self._inbound: list[dict] = []
        self._done = threading.Event()
        self._reader = threading.Thread(target=self._read_forever, daemon=True)
        self._reader.start()

    def _read_forever(self) -> None:
        stream = self._proc.stdout
        if stream is None:  # pragma: no cover - always piped by the caller
            return
        for raw in stream:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                # A line we cannot parse is the agent's problem, not a reason
                # to abandon the turn: keep reading and let the timeout rule.
                continue
            with self._lock:
                if "id" in message and ("result" in message or "error" in message):
                    self._responses[message["id"]] = message
                else:
                    self._inbound.append(message)
        self._done.set()

    def send_request(self, method: str, params: dict) -> dict:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
        self._write(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        return self._await(request_id)

    def respond(self, request_id: Any, result: dict) -> None:
        self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    def respond_error(self, request_id: Any, message: str) -> None:
        self._write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32000, "message": message},
            }
        )

    def _write(self, message: dict) -> None:
        stream = self._proc.stdin
        if stream is None:  # pragma: no cover
            raise AcpError("the agent has no stdin")
        try:
            stream.write((json.dumps(message) + "\n").encode("utf-8"))
            stream.flush()
        except (BrokenPipeError, OSError) as exc:
            raise AcpError(f"the agent stopped listening: {exc}") from exc

    def _await(self, request_id: int) -> dict:
        """Wait for one response, serving the agent's own requests meanwhile.

        Bounded by whichever comes first: this request's own ceiling, or the
        turn's deadline. `worker_timeout` is the repo's instruction and must
        not be quietly outlived by a client-side default.
        """
        deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
        if self._deadline is not None:
            deadline = min(deadline, self._deadline)
        while time.monotonic() < deadline:
            with self._lock:
                found = self._responses.pop(request_id, None)
                pending = self._inbound[:]
                self._inbound.clear()
            for message in pending:
                self._serve(message)
            if found is not None:
                if "error" in found:
                    raise AcpError(f"{found['error'].get('message', 'agent error')}")
                return found.get("result", {})
            if self._done.is_set() and self._proc.poll() is not None:
                raise AcpError("the agent exited before replying")
            time.sleep(0.01)
        raise AcpError("the agent did not reply before the turn's deadline")

    # Set by the session so inbound requests can be served with context.
    handler: Any = None

    def _serve(self, message: dict) -> None:
        if self.handler is not None:
            self.handler(message)

    def drain(self) -> None:
        """Serve whatever arrived after the turn's response."""
        with self._lock:
            pending = self._inbound[:]
            self._inbound.clear()
        for message in pending:
            self._serve(message)


def _inside(root: Path, candidate: str) -> Path | None:
    """Resolve a path the agent named, or None if it escapes the repo.

    Wringer is not obliged to help an agent write outside the tree it was
    pointed at, and a symlink is not an argument.
    """
    try:
        resolved = (root / candidate).resolve()
        return resolved if resolved.is_relative_to(root.resolve()) else None
    except (OSError, ValueError):
        return None


def run_turn(
    command: str,
    args: tuple[str, ...],
    env_passthrough: tuple[str, ...],
    brief: str,
    root: Path,
    timeout: int,
    stdout_path: Path,
    stderr_path: Path,
) -> tuple[Turn, int]:
    """Hold one ACP session and return what it did, plus the exit status.

    The agent runs in its own process group, so the loop's existing kill and
    drain behaviour applies unchanged — an ACP worker is a worker.
    """
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    for name in env_passthrough:
        if name in os.environ:
            env[name] = os.environ[name]

    try:
        proc = subprocess.Popen(
            [command, *args],
            cwd=root,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_path.open("wb"),
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        raise AcpError(
            f"could not start the ACP agent {command!r}: {exc}. Wringer never "
            "installs an agent — install the one you declared"
        ) from exc

    turn = Turn()
    connection = Connection(proc, deadline=time.monotonic() + timeout)
    connection.handler = lambda message: _handle(message, connection, root, turn)

    try:
        info = connection.send_request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "clientCapabilities": CLIENT_CAPABILITIES,
                "clientInfo": {"name": "wringer", "version": _version()},
            },
        )
        turn.protocol_version = int(info.get("protocolVersion", 0) or 0)
        agent = info.get("agentInfo") or {}
        turn.agent_name = str(agent.get("name", ""))
        turn.agent_version = str(agent.get("version", ""))

        session = connection.send_request("session/new", {"cwd": str(root)})
        session_id = session.get("sessionId")
        if not session_id:
            raise AcpError("the agent opened no session")

        result = connection.send_request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": brief}],
            },
        )
        # Recorded, never acted on — exactly as a shell worker's exit code is.
        turn.stop_reason = str(result.get("stopReason", "unknown"))
        connection.drain()
    finally:
        _stop(proc, timeout)
        stdout_path.write_text("\n".join(turn.updates) + "\n", encoding="utf-8")

    return turn, proc.returncode if proc.returncode is not None else 0


def _handle(message: dict, connection: Connection, root: Path, turn: Turn) -> None:
    """Serve one agent-to-client message."""
    method = message.get("method", "")
    params = message.get("params") or {}
    request_id = message.get("id")

    if method == "session/update":
        update = params.get("update") or {}
        kind = update.get("sessionUpdate") or update.get("type") or "update"
        turn.updates.append(f"[{kind}] {json.dumps(update)[:400]}")
        return

    if method == "fs/read_text_file":
        path = _inside(root, str(params.get("path", "")))
        if path is None or not path.is_file():
            connection.respond_error(request_id, "no such file inside the repository")
            turn.refusals.append(str(params.get("path", "")))
            return
        connection.respond(
            request_id, {"content": path.read_text(encoding="utf-8", errors="replace")}
        )
        return

    if method == "fs/write_text_file":
        named = str(params.get("path", ""))
        path = _inside(root, named)
        if path is None:
            # The refusal is the interesting event: an agent trying to write
            # outside the repo is worth a line in the evidence.
            connection.respond_error(request_id, "refused: path escapes the repository")
            turn.refusals.append(named)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(params.get("content", "")), encoding="utf-8")
        turn.files_written.append(named)
        connection.respond(request_id, {})
        return

    if method == "session/request_permission":
        # Auto-approved in v0, and recorded. A consent prompt nobody is
        # sitting at is not a safety control; the container and the
        # supervision invariants are. The ledger is what makes this
        # auditable rather than invisible.
        tool = json.dumps(params.get("toolCall") or params.get("tool") or {})[:200]
        turn.permissions.append({"tool": tool, "outcome": "auto_approved"})
        options = params.get("options") or []
        chosen = next(
            (o.get("optionId") for o in options if o.get("kind") == "allow_always"),
            None,
        ) or next((o.get("optionId") for o in options), "allow")
        connection.respond(
            request_id, {"outcome": {"outcome": "selected", "optionId": chosen}}
        )
        return

    if request_id is not None:
        connection.respond_error(request_id, f"unsupported method {method!r}")


def _stop(proc: subprocess.Popen, timeout: int) -> None:
    import signal

    if proc.poll() is not None:
        return
    try:
        if proc.stdin is not None:
            proc.stdin.close()
    except OSError:
        pass
    try:
        proc.wait(timeout=min(5, timeout))
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover
        pass


def _version() -> str:
    from wringer import __version__

    return __version__
