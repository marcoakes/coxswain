"""Run many repair loops under supervision — `wringer.fleet.v1`.

SPEC_SUPERVISION_V0.md §S3. Hundreds of tasks may be queued; a bounded pool
runs at a time; what can heal is retried once on a *new* failure shape; what
cannot is parked with its evidence; and the whole thing survives its own
death because every fact is on an append-only ledger before it is acted on.

**The fleet is only a supervisor.** Each child is an ordinary `wring run`
loop in its own directory, spawned as a subprocess — which is what keeps the
whole thing testable with shell workers and keeps the fleet's own logic
small enough to reason about.

The invariants this file exists to enforce, from the incident that paid for
them: nothing retries without a ceiling, nothing retries on an identical
failure, nothing waits without a deadline, and liveness is measured by
**ledger growth** rather than by a process still existing — the incident's
fleet had live processes for eight hours and produced nothing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from wringer import config, evidence, loop
from wringer.redact import Redactor

FLEETS_DIRNAME = Path(".wringer") / "fleets"
WORKTREES_DIRNAME = Path(".wringer") / "worktrees"
SCHEMA_VERSION = "wringer.fleet.v1"
EVENTS_FILENAME = "fleet.jsonl"
MANIFEST_FILENAME = "manifest.json"
SUMMARY_FILENAME = "summary.md"

# How often the supervisor looks at its children. Short enough that a
# finished child is noticed promptly, long enough that watching costs
# nothing next to the work being watched.
POLL_SECONDS = 0.2

SUCCEEDED, FAILED, PARKED = "succeeded", "failed", "parked"


class FleetError(Exception):
    """The fleet could not run (CLI exit code 2)."""


@dataclass(frozen=True)
class Task:
    id: str
    brief: str
    dir: str


@dataclass
class TaskState:
    """One task's life. Mutable because it is exactly the thing that changes."""

    task: Task
    attempts: int = 0
    status: str = "pending"
    reason: str = ""
    signatures: list[str] = field(default_factory=list)
    loop_dirs: list[str] = field(default_factory=list)
    worktree: str | None = None


@dataclass(frozen=True)
class Outcome:
    directory: Path
    succeeded: int
    failed: int
    parked: int
    join_satisfied: bool

    @property
    def total(self) -> int:
        return self.succeeded + self.failed + self.parked


def load_tasks(path: Path) -> list[Task]:
    """One JSON object per line: references, never inline payloads.

    Invariant 5. The incident handed each consumer a 50 KB blob inline and
    every one of them drowned; a task therefore names a brief *file* and a
    directory, and stays small enough to read at a glance.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FleetError(f"cannot read {path}: {exc}") from exc

    tasks: list[Task] = []
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path.name}:{number}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FleetError(f"{where}: not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise FleetError(f"{where}: each line must be a JSON object")

        unknown = sorted(set(raw) - {"id", "brief", "dir"})
        if unknown:
            raise FleetError(f"{where}: unknown keys: {', '.join(unknown)}")
        for key in ("id", "brief", "dir"):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise FleetError(f"{where}: '{key}' must be a non-empty string")

        task_id = raw["id"].strip()
        if not config.GATE_ID_PATTERN.fullmatch(task_id) or len(task_id) > 64:
            raise FleetError(
                f"{where}: id '{task_id}' must be a slug — it names a directory"
            )
        if task_id in seen:
            raise FleetError(f"{where}: duplicate task id '{task_id}'")
        seen.add(task_id)
        tasks.append(Task(id=task_id, brief=raw["brief"], dir=raw["dir"]))

    if not tasks:
        raise FleetError(f"{path} declares no tasks")
    return tasks


@dataclass(frozen=True)
class Bundle:
    directory: Path
    fleet_id: str
    started_at: datetime
    redactor: Redactor = Redactor()

    @classmethod
    def create(
        cls, fleets_root: Path, redactor: Redactor | None = None
    ) -> Bundle:
        started_at = datetime.now().astimezone()
        try:
            fleets_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FleetError(f"cannot create {fleets_root}: {exc}") from exc
        for _ in range(64):
            fleet_id = evidence.new_run_id(started_at)
            directory = fleets_root / fleet_id
            try:
                directory.mkdir(exist_ok=False)
            except FileExistsError:
                continue
            except OSError as exc:
                raise FleetError(f"cannot create {directory}: {exc}") from exc
            return cls(directory, fleet_id, started_at, redactor or Redactor())
        raise FleetError(f"could not allocate a directory under {fleets_root}")

    def event(self, event_type: str, **fields: Any) -> None:
        scrubbed = evidence.deep_scrub(self.redactor, fields)
        path = self.directory / EVENTS_FILENAME
        line = json.dumps(
            {
                "type": event_type,
                "ts": evidence.timestamp(),
                "prev_hash": evidence.chain_head(path),
                **scrubbed,
            }
        )
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def write_manifest(
        self, settings: config.Fleet, states: list[TaskState], satisfied: bool
    ) -> None:
        counts = _counts(states)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "fleet_id": self.fleet_id,
            "started_at": self.started_at.replace(microsecond=0).isoformat(),
            "config": {
                "concurrency": settings.concurrency,
                "deadline": settings.deadline,
                "retries": settings.retries,
                "join": settings.join,
            },
            "result": {
                "succeeded": counts[SUCCEEDED],
                "failed": counts[FAILED],
                "parked": counts[PARKED],
                "join_satisfied": satisfied,
            },
            "tasks": [
                {
                    "id": s.task.id,
                    "status": s.status,
                    "reason": s.reason,
                    "attempts": s.attempts,
                    "loops": s.loop_dirs,
                }
                for s in states
            ],
        }
        (self.directory / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

    def write_digests(self) -> Path:
        """Hash every file in this fleet bundle. **Written last.**"""
        return evidence.digest_directory(self.directory)

    def write_summary(self, states: list[TaskState], satisfied: bool) -> None:
        counts = _counts(states)
        lines = [
            f"# wring fleet — {self.fleet_id}",
            "",
            f"- started: {self.started_at.replace(microsecond=0).isoformat()}",
            f"- result: **{counts[SUCCEEDED]} succeeded, {counts[FAILED]} failed, "
            f"{counts[PARKED]} parked** of {len(states)}",
            f"- join: **{'satisfied' if satisfied else 'not satisfied'}**",
            "",
            "| task | status | attempts | why |",
            "|---|---|---|---|",
        ]
        for state in states:
            lines.append(
                f"| {state.task.id} | {state.status} | {state.attempts} "
                f"| {state.reason or '—'} |"
            )
        parked = [s for s in states if s.status == PARKED]
        if parked:
            lines += [
                "",
                "Parked work is not lost: its evidence is above and in the "
                "child loop directories. **There is no fleet resume yet** — "
                "`wring resume` continues a single killed *loop*, not a fleet. "
                "To retry, re-run `wring fleet` with a task file holding the "
                "parked ids.",
            ]
        (self.directory / SUMMARY_FILENAME).write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )


def _counts(states: list[TaskState]) -> dict[str, int]:
    counts = {SUCCEEDED: 0, FAILED: 0, PARKED: 0}
    for state in states:
        if state.status in counts:
            counts[state.status] += 1
    return counts


@dataclass
class _Child:
    state: TaskState
    proc: subprocess.Popen
    started: float
    loop_dir: Path | None = None
    last_growth: float = 0.0
    last_size: int = -1


def run(
    root: Path,
    cfg: config.Config,
    tasks: list[Task],
    on_event: Any = None,
) -> Outcome:
    """Supervise the queue until it empties or the deadline bites."""
    assert cfg.fleet is not None
    settings = cfg.fleet
    redactor = Redactor.from_config(cfg.evidence)
    bundle = Bundle.create(root / FLEETS_DIRNAME, redactor=redactor)

    bundle.event(
        "fleet.started",
        fleet_id=bundle.fleet_id,
        tasks=len(tasks),
        concurrency=settings.concurrency,
        deadline=settings.deadline,
    )

    states = [TaskState(task=t) for t in tasks]
    queue = list(states)
    running: list[_Child] = []
    deadline = time.monotonic() + settings.deadline

    while queue or running:
        expired = time.monotonic() >= deadline
        while queue and not expired and len(running) < settings.concurrency:
            state = queue.pop(0)
            child = _spawn(root, bundle, state, settings)
            if child is None:
                continue
            running.append(child)

        if expired:
            for child in running:
                _stop(child)
                child.state.status = PARKED
                child.state.reason = "fleet deadline"
                bundle.event(
                    "task.parked", task=child.state.task.id, why="deadline"
                )
            for state in queue:
                state.status = PARKED
                state.reason = "fleet deadline"
                bundle.event("task.parked", task=state.task.id, why="deadline")
            running, queue = [], []
            break

        time.sleep(POLL_SECONDS)
        for child in list(running):
            if child.proc.poll() is not None:
                running.remove(child)
                _settle(bundle, child, settings, queue)
            elif _is_silent(child, settings):
                _stop(child)
                running.remove(child)
                child.state.status = FAILED
                child.state.reason = "reaped: no progress in its ledger"
                bundle.event("task.reaped", task=child.state.task.id)
                _maybe_retry(bundle, child.state, settings, queue, "no_progress")

    if settings.worktree:
        # Tidy up every checkout this fleet made. Parked and failed tasks
        # keep their EVIDENCE — that lives in the fleet bundle and the child
        # loop dirs — but the working copies go, or a hundred-task fleet
        # leaves a hundred trees behind.
        for state in states:
            if state.worktree:
                remove_worktree(root, Path(state.worktree))

    satisfied = _join_satisfied(states, settings.join)
    counts = _counts(states)
    bundle.event(
        "fleet.finished",
        succeeded=counts[SUCCEEDED],
        failed=counts[FAILED],
        parked=counts[PARKED],
        join_satisfied=satisfied,
    )
    bundle.write_manifest(settings, states, satisfied)
    bundle.write_summary(states, satisfied)
    bundle.write_digests()  # LAST, so it covers the manifest and the summary

    return Outcome(
        directory=bundle.directory,
        succeeded=counts[SUCCEEDED],
        failed=counts[FAILED],
        parked=counts[PARKED],
        join_satisfied=satisfied,
    )


def make_worktree(root: Path, task_id: str) -> Path | None:
    """Give a task its own checkout, so parallel children cannot collide.

    The only git WRITE Wringer performs, and it is metadata: `worktree add`
    and `worktree remove`. No commit, no branch move, no push — the law that
    the harness never writes history is untouched.

    Detached at HEAD: a worktree on a branch would move that branch, which is
    history. Returns None if git refuses, and the caller parks the task —
    a fleet that silently ran two children in one tree would be worse.
    """
    path = root / WORKTREES_DIRNAME / task_id
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        remove_worktree(root, path)
    proc = subprocess.run(
        ["git", "worktree", "add", "--detach", str(path), "HEAD"],
        cwd=root, capture_output=True, text=True, timeout=120,
    )
    return path if proc.returncode == 0 else None


def remove_worktree(root: Path, path: Path) -> None:
    """Tidy up. --force because a child may have left the tree dirty, and a
    fleet that cannot clean up after itself accumulates until a human does."""
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(path)],
        cwd=root, capture_output=True, text=True, timeout=120,
    )


def _spawn(
    root: Path, bundle: Bundle, state: TaskState, settings: config.Fleet
) -> _Child | None:
    if settings.worktree:
        made = make_worktree(root, state.task.id)
        if made is None:
            state.status = PARKED
            state.reason = "could not create a git worktree"
            bundle.event("task.parked", task=state.task.id, why="worktree_failed")
            return None
        state.worktree = str(made)
        bundle.event("task.worktree", task=state.task.id, path=str(
            made.relative_to(root) if made.is_relative_to(root) else made))
        workdir = made
    else:
        workdir = (root / state.task.dir).resolve()
    if not workdir.is_dir():
        state.status = PARKED
        state.reason = f"no such directory: {state.task.dir}"
        bundle.event("task.parked", task=state.task.id, why="missing_dir")
        return None

    state.attempts += 1
    # The fallback ladder is *declared*, never improvised: attempt N uses
    # entry N-1 if the repo wrote one down.
    fallback = None
    index = state.attempts - 2
    if 0 <= index < len(settings.worker_fallbacks):
        fallback = settings.worker_fallbacks[index]

    env = dict(os.environ)
    # Shell-native rather than a new placeholder vocabulary: a repo's worker
    # command can use these directly.
    env["WRINGER_TASK_ID"] = state.task.id
    env["WRINGER_TASK_BRIEF"] = str((root / state.task.brief).resolve())
    if fallback:
        env["WRINGER_WORKER_FALLBACK"] = fallback

    # Invariant 8: budgets nest. These were parsed and silently discarded, so
    # a child could outlive the fleet that spawned it — and the fleet's own
    # deadline is no substitute, because it kills the supervisor rather than
    # the worker burning the budget.
    argv = [sys.executable, "-m", "wringer", "run"]
    if settings.child_max_iterations is not None:
        argv += ["--max-iterations", str(settings.child_max_iterations)]
    if settings.child_worker_timeout is not None:
        argv += ["--worker-timeout", str(settings.child_worker_timeout)]
    if settings.child_wall_clock is not None:
        argv += ["--wall-clock", str(settings.child_wall_clock)]

    proc = subprocess.Popen(
        argv,
        cwd=workdir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name == "posix",
    )
    bundle.event(
        "task.started",
        task=state.task.id,
        attempt=state.attempts,
        dir=state.task.dir,
        **({"fallback": fallback} if fallback else {}),
    )
    now = time.monotonic()
    return _Child(state=state, proc=proc, started=now, last_growth=now)


def _stop(child: _Child) -> None:
    import signal

    try:
        os.killpg(os.getpgid(child.proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        try:
            child.proc.kill()
        except OSError:
            pass


def _child_ledger(root_dir: Path) -> Path | None:
    found = loop.latest_loop(root_dir / loop.LOOPS_DIRNAME)
    return found / loop.EVENTS_FILENAME if found is not None else None


def _is_silent(child: _Child, settings: config.Fleet) -> bool:
    """Liveness is ledger growth, not a live process.

    The incident's fleet had twenty live processes for eight hours. "It is
    still running" is not evidence that anything is happening.
    """
    ledger = _child_ledger(
        Path(child.state.worktree)
        if child.state.worktree
        else Path(child.state.task.dir).resolve()
    )
    size = -1
    if ledger is not None and ledger.is_file():
        try:
            size = ledger.stat().st_size
        except OSError:
            size = -1
    now = time.monotonic()
    if size > child.last_size:
        child.last_size = size
        child.last_growth = now
        return False
    return (now - child.last_growth) >= settings.progress_window


def _settle(
    bundle: Bundle, child: _Child, settings: config.Fleet, queue: list[TaskState]
) -> None:
    """Record what a finished child achieved, and heal it if it can be."""
    state = child.state
    workdir = (
        Path(state.worktree) if state.worktree else Path(state.task.dir).resolve()
    )
    found = loop.latest_loop(workdir / loop.LOOPS_DIRNAME)
    signature, reason = None, "unknown"
    if found is not None:
        state.loop_dirs.append(found.name)
        try:
            manifest = json.loads(
                (found / loop.MANIFEST_FILENAME).read_text(encoding="utf-8")
            )
            reason = manifest.get("result", {}).get("reason", "unknown")
        except (OSError, json.JSONDecodeError):
            pass
        signature = _last_signature(found)

    if child.proc.returncode == 0:
        state.status = SUCCEEDED
        state.reason = "converged"
        bundle.event("task.finished", task=state.task.id, status=SUCCEEDED,
                     loop=found.name if found else None)
        return

    bundle.event(
        "task.finished",
        task=state.task.id,
        status=FAILED,
        reason=reason,
        loop=found.name if found else None,
        **({"failure_signature": signature} if signature else {}),
    )
    _maybe_retry(bundle, state, settings, queue, reason, signature)


def _last_signature(loop_dir: Path) -> str | None:
    try:
        events = loop.read_events(loop_dir)
    except evidence.EvidenceError:
        return None
    signatures = [
        e["failure_signature"]
        for e in events
        if e.get("type") == "verify.finished" and e.get("failure_signature")
    ]
    return signatures[-1] if signatures else None


def _maybe_retry(
    bundle: Bundle,
    state: TaskState,
    settings: config.Fleet,
    queue: list[TaskState],
    reason: str,
    signature: str | None = None,
) -> None:
    """The self-healing ladder, and the rule that stops it being a treadmill.

    A failure shape seen before for *this task* is deterministic: retrying it
    would reproduce it. That is invariant 2, and it is the single rule that
    would have saved the incident's twenty wasted agents.
    """
    if signature is not None and signature in state.signatures:
        state.status = PARKED
        state.reason = f"{reason} (same failure twice — retrying would repeat it)"
        bundle.event("task.parked", task=state.task.id, why="deterministic")
        return
    if signature is not None:
        state.signatures.append(signature)

    if state.attempts > settings.retries:
        state.status = PARKED if settings.on_exhausted == "park" else FAILED
        state.reason = f"{reason} (attempts exhausted)"
        bundle.event(
            "task.parked" if state.status == PARKED else "task.finished",
            task=state.task.id,
            why="exhausted",
        )
        return

    state.status = "pending"
    state.reason = reason
    bundle.event("task.retried", task=state.task.id, after=reason)
    queue.append(state)


def _join_satisfied(states: list[TaskState], join: str) -> bool:
    succeeded = sum(1 for s in states if s.status == SUCCEEDED)
    if join == "all":
        return succeeded == len(states)
    if join == "first_pass":
        return succeeded >= 1
    if join.startswith("quorum:"):
        return succeeded >= len(states) * float(join.split(":", 1)[1])
    return False  # pragma: no cover - validated at parse time
