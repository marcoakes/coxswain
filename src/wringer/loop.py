"""The repair loop — verify, brief the worker, verify again (SPEC_RUN_V0.md).

`wring verify` proves a change. This closes the loop around it: while the
gates fail, write what failed into a brief and hand it to the worker the repo
declared, then verify again. The worker is somebody else's program — usually
a coding agent — spawned as a subprocess. **Wringer makes no LLM call and no
network call of its own here**, exactly as in v0.1.

Two rulings shape everything below:

- **A worker's exit code never ends the loop.** The evidence decides. A
  worker that crashed after fixing the bug converges on the next lap; one
  that exited cleanly without touching anything stops on `no_progress`.
- **The loop never writes to git.** It runs gates and a worker. Committing
  what came out is the human's decision.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from wringer import __version__, config, evidence, gates, git, verify
from wringer.redact import Redactor

LOOPS_DIRNAME = Path(".wringer") / "loops"
SCHEMA_VERSION = "wringer.loop.v1"
EVENTS_FILENAME = "loop.jsonl"
MANIFEST_FILENAME = "manifest.json"
SUMMARY_FILENAME = "summary.md"
ITERATIONS_DIRNAME = "iterations"
BRIEF_FILENAME = "brief.md"

# The synthetic gate id the worker runs as. Not a gate anyone declared — it
# just borrows the gate runner's process-group kill, bounded drain, and
# scrub-then-cap log writing rather than reimplementing them worse.
WORKER_ID = "worker"

# How much of a failing gate's log to quote into the brief. The worker can
# open the bundle for the rest; this is what it needs to start.
BRIEF_TAIL_LINES = 40

# Untracked files this big contribute their size rather than their contents
# to the fingerprint. Hashing a 2 GB artifact to notice it changed would cost
# more than the whole loop.
FINGERPRINT_MAX_BYTES = 10 * 1024 * 1024

# How much of a failing gate's log shapes its failure signature. Enough to
# tell two different failures apart, little enough that a long tail of
# incidental output does not drown the part that identifies it.
SIGNATURE_TAIL_LINES = 30

# Noise stripped before a failure is hashed, so the *shape* of a failure is
# what gets compared rather than the timestamps and paths around it. Missing
# a match is safe — the iteration ceiling still catches it; matching two
# genuinely different failures would not be, so these stay conservative.
_NOISE = (
    re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"),  # timestamps
    re.compile(r"\d{8}-\d{6}-[0-9a-f]{4}"),                            # run ids
    re.compile(r"0x[0-9a-fA-F]+"),                                     # addresses
    re.compile(r"\b\d+(?:\.\d+)?\s*m?s\b"),                            # durations
    re.compile(r"/(?:tmp|private/var|var/folders)/\S+"),               # scratch paths
)

Reporter = Callable[..., None]


@dataclass(frozen=True)
class Outcome:
    directory: Path
    status: str  # converged | stopped | interrupted
    reason: str  # converged | max_iterations | no_progress | interrupted
    iterations: int
    final: verify.Outcome | None

    @property
    def converged(self) -> bool:
        return self.status == "converged"


@dataclass(frozen=True)
class Bundle:
    """The loop's own evidence, beside but never inside the verify bundles.

    Verify runs are referenced by path: one run, one bundle, one place. Like
    `evidence.Bundle`, this owns the redactor so every write scrubs by
    construction rather than by the caller remembering.
    """

    directory: Path
    loop_id: str
    started_at: datetime
    redactor: Redactor = Redactor()

    @classmethod
    def create(
        cls,
        loops_root: Path,
        now: datetime | None = None,
        redactor: Redactor | None = None,
    ) -> Bundle:
        started_at = now if now is not None else datetime.now().astimezone()
        try:
            loops_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise evidence.EvidenceError(f"cannot create {loops_root}: {exc}") from exc

        for _ in range(64):
            loop_id = evidence.new_run_id(started_at)
            directory = loops_root / loop_id
            try:
                directory.mkdir(exist_ok=False)
            except FileExistsError:
                continue  # same second, fresh suffix
            except OSError as exc:
                raise evidence.EvidenceError(
                    f"cannot create {directory}: {exc}"
                ) from exc
            return cls(
                directory=directory,
                loop_id=loop_id,
                started_at=started_at,
                redactor=redactor or Redactor(),
            )
        raise evidence.EvidenceError(
            f"could not allocate a loop directory under {loops_root}"
        )

    def iteration_dir(self, iteration: int) -> Path:
        directory = self.directory / ITERATIONS_DIRNAME / f"{iteration:03d}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def event(self, event_type: str, **fields: Any) -> None:
        scrubbed = evidence.deep_scrub(self.redactor, fields)
        line = json.dumps(
            {"type": event_type, "ts": evidence.timestamp(), **scrubbed}
        )
        with (self.directory / EVENTS_FILENAME).open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def write_brief(self, iteration: int, text: str) -> Path:
        path = self.iteration_dir(iteration) / BRIEF_FILENAME
        path.write_text(self.redactor.scrub(text), encoding="utf-8")
        return path

    def write_manifest(
        self,
        state: git.RepoState,
        run: config.Run,
        status: str,
        reason: str,
        iterations: int,
        final_run: str | None,
    ) -> None:
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "loop_id": self.loop_id,
            "started_at": self.started_at.replace(microsecond=0).isoformat(),
            "repo": {
                "root": ".",
                "head_sha": state.head_sha,
                "branch": state.branch,
                "dirty": state.dirty,
            },
            "config": {
                "max_iterations": run.max_iterations,
                "worker": self.redactor.scrub(run.worker),
            },
            "result": {
                "status": status,
                "reason": reason,
                "iterations": iterations,
                "final_run": final_run,
            },
        }
        (self.directory / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )


def failure_signature(outcome: verify.Outcome) -> str | None:
    """A hash of the *shape* of a failure, or None if nothing failed.

    Two failures with the same signature are the same failure. Retrying one
    is not repair, it is repetition — which is the whole lesson of the
    incident SPEC_SUPERVISION_V0 was written from: twenty agents were retried
    on identical input and produced nothing twenty times.

    Normalization is deliberately conservative. A false negative merely
    spends budget the iteration ceiling still bounds; a false positive would
    stop a loop that was genuinely making progress.
    """
    if outcome.failed_gate is None:
        return None
    failing = next(
        (r for r in outcome.results if r.gate.id == outcome.failed_gate), None
    )
    if failing is None:  # pragma: no cover - a failed_gate always has a result
        return None

    parts = [outcome.failed_gate, str(failing.exit_code)]
    for path in (failing.stdout_path, failing.stderr_path):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        parts.append(_normalize(text))

    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _normalize(text: str) -> str:
    """Strip the parts of a log that differ between identical failures."""
    tail = text.splitlines()[-SIGNATURE_TAIL_LINES:]
    lines = []
    for line in tail:
        for pattern in _NOISE:
            line = pattern.sub("", line)
        collapsed = " ".join(line.split())
        if collapsed:
            lines.append(collapsed)
    return "\n".join(lines)


def fingerprint(root: Path) -> str:
    """A hash of everything a worker could have changed.

    HEAD, the tracked diff, the porcelain status, and the contents of every
    untracked file. If this is unchanged across a worker's turn, the worker
    changed nothing, and re-running the gates would produce the same answer
    at the same cost — so the loop stops instead.

    Deliberately the degenerate form of the roadmap's anti-thrash machinery:
    failure-signature hashing and oscillation detection are a later slice.
    """
    state = git.inspect(root)
    digest = hashlib.sha256()
    for part in (
        state.head_sha or "",
        git.diff(root, state.head_sha) or "",
        _without_wringer(git.status(root) or ""),
    ):
        digest.update(part.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")

    for relative in sorted(state.untracked):
        if _is_wringers(relative):
            # Every verify writes a new bundle, so counting Wringer's own
            # evidence as the worker's work would make the tree look changed
            # on every lap and no worker would ever be found idle. The same
            # rule that makes verify snapshot git before opening its bundle.
            continue
        digest.update(relative.encode("utf-8", "surrogateescape"))
        path = root / relative
        try:
            if path.is_dir():
                # git reports an untracked directory as one entry; its
                # contents are covered by walking it in sorted order
                for child in sorted(p for p in path.rglob("*") if p.is_file()):
                    digest.update(str(child.relative_to(root)).encode())
                    _hash_file(digest, child)
            else:
                _hash_file(digest, path)
        except OSError:
            # vanished mid-scan; its absence is itself a change we will see
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return digest.hexdigest()


def _is_wringers(relative: str) -> bool:
    """Whether a path belongs to Wringer's own evidence rather than the repo."""
    return relative.split("/", 1)[0] == evidence.RUNS_DIRNAME.parts[0]


def _without_wringer(porcelain: str) -> str:
    """Porcelain status with Wringer's own entries dropped, for the same
    reason the untracked walk skips them."""
    return "\n".join(
        line
        for line in porcelain.splitlines()
        if not _is_wringers(line[3:].strip().strip('"'))
    )


def _hash_file(digest: Any, path: Path) -> None:
    size = path.stat().st_size
    if size > FINGERPRINT_MAX_BYTES:
        digest.update(f"<{size} bytes>".encode())
        return
    digest.update(path.read_bytes())


def run(
    root: Path,
    cfg: config.Config,
    max_iterations: int | None = None,
    on_iteration: Reporter | None = None,
    on_gate: verify.GateReporter | None = None,
    on_worker: Reporter | None = None,
) -> Outcome:
    """Drive the loop. `cfg.run` must not be None — the caller checks that,
    because a missing `run:` section is a config error with its own message."""
    assert cfg.run is not None
    settings = cfg.run
    budget = max_iterations if max_iterations is not None else settings.max_iterations

    planned = verify.plan(cfg, None)
    redactor = Redactor.from_config(cfg.evidence)
    bundle = Bundle.create(root / LOOPS_DIRNAME, redactor=redactor)
    state = git.inspect(root)

    bundle.event(
        "loop.started",
        loop_id=bundle.loop_id,
        wringer_version=__version__,
        repo=root.name,
        sha=state.head_sha,
        max_iterations=budget,
    )

    final: verify.Outcome | None = None
    status = reason = "stopped"
    iterations = 0
    # The tree as it was when the previous worker was handed control. Equal
    # again now means that worker changed nothing.
    before_worker: str | None = None
    # Every failure shape this loop has already seen. Seeing one twice means
    # the worker is going in circles (A→B→A) or standing still (A→A), and
    # either way the gates will keep saying the same thing.
    seen_signatures: set[str] = set()
    deadline = (
        time.monotonic() + settings.wall_clock
        if settings.wall_clock is not None
        else None
    )

    for iteration in range(1, budget + 1):
        iterations = iteration
        if on_iteration is not None:
            on_iteration(iteration, budget)
        bundle.event("iteration.started", iteration=iteration)

        final = verify.run(root, cfg, planned, on_gate=on_gate)
        signature = failure_signature(final)
        bundle.event(
            "verify.finished",
            iteration=iteration,
            status=final.status,
            **(
                {"failed_gate": final.failed_gate}
                if final.failed_gate is not None
                else {}
            ),
            **({"failure_signature": signature} if signature is not None else {}),
            evidence_dir=verify.bundle_path(final.bundle, root),
        )

        if final.status == "interrupted":
            status = reason = "interrupted"
            break
        if final.passed:
            status = reason = "converged"
            break

        current = fingerprint(root)
        if before_worker is not None and current == before_worker:
            # An identical tree gives an identical result; verifying it again
            # would be theatre. Checked BEFORE the breaker because it is the
            # more precise diagnosis of the same symptom: "your worker did
            # nothing" is actionable in a way "the failure came back" is not.
            status, reason = "stopped", "no_progress"
            break

        # The breaker. The worker changed *something* and the same failure
        # shape came back anyway — it is going round in a circle (A→B→A) or
        # editing things that do not touch the failure (A→A). Spending the
        # rest of the budget on it would be the incident of 2026-07-30 in
        # miniature: twenty retries of a failure that was never transient.
        if signature is not None and signature in seen_signatures:
            status, reason = "stopped", "oscillating"
            break
        if signature is not None:
            seen_signatures.add(signature)
        if iteration == budget:
            status, reason = "stopped", "max_iterations"
            break
        # Checked between steps, never mid-gate: Wringer does not abandon a
        # verify half-done to save seconds, so a deadline stops the *next*
        # step rather than killing the one in flight.
        if deadline is not None and time.monotonic() >= deadline:
            status, reason = "stopped", "budget_exhausted"
            break

        brief = bundle.write_brief(iteration, _brief(final, root))
        before_worker = current

        command = config.substitute(
            settings.worker,
            brief=brief,
            evidence_dir=verify.bundle_path(final.bundle, root),
            iteration=iteration,
        )
        bundle.event("worker.started", iteration=iteration, command=command)
        try:
            result = _run_worker(
                bundle, command, settings.worker_timeout, iteration, root
            )
        except KeyboardInterrupt:
            # A worker.started with no worker.finished, mirroring how verify
            # records a gate that was killed mid-flight.
            status = reason = "interrupted"
            break
        bundle.event(
            "worker.finished",
            iteration=iteration,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            **({"timed_out": True} if result.timed_out else {}),
        )
        if on_worker is not None:
            on_worker(result)

    bundle.event(
        "loop.finished", status=status, reason=reason, iterations=iterations
    )
    final_run = verify.bundle_path(final.bundle, root) if final is not None else None
    bundle.write_manifest(
        state=state,
        run=settings,
        status=status,
        reason=reason,
        iterations=iterations,
        final_run=final_run,
    )
    _write_summary(bundle, state, status, reason, iterations, final_run)

    return Outcome(
        directory=bundle.directory,
        status=status,
        reason=reason,
        iterations=iterations,
        final=final,
    )


def _run_worker(
    bundle: Bundle, command: str, timeout: int, iteration: int, root: Path
) -> gates.GateResult:
    """Run the worker through the gate runner, for its process-group kill,
    its bounded drain, and its scrub-then-cap log writing."""
    directory = bundle.iteration_dir(iteration)
    return gates.run(
        config.Gate(id=WORKER_ID, run=command, timeout=timeout),
        cwd=root,
        stdout_path=directory / "worker.stdout.log",
        stderr_path=directory / "worker.stderr.log",
        redactor=bundle.redactor,
    )


def _brief(outcome: verify.Outcome, root: Path) -> str:
    """What the worker is told: the machine-readable verdict, the failing
    gate, and enough of its output to act without opening the bundle."""
    summary = verify.json_summary(outcome, root)
    lines = [
        "# Fix this",
        "",
        "`wring verify` failed. This is the structured result an agent would",
        "get from `wring verify --json`:",
        "",
        "```json",
        json.dumps(summary, indent=2),
        "```",
        "",
    ]

    failing = next(
        (r for r in outcome.results if r.gate.id == outcome.failed_gate), None
    )
    if failing is not None:
        lines += [
            f"## Failing gate: `{failing.gate.id}`",
            "",
            f"- command: `{failing.gate.run}`",
            f"- exit code: {failing.exit_code}",
        ]
        if failing.timed_out:
            lines.append(f"- timed out after {failing.gate.timeout}s")
        lines.append("")
        for label, path in (
            ("stdout", failing.stdout_path),
            ("stderr", failing.stderr_path),
        ):
            tail = _tail(path)
            if tail:
                lines += [f"### {label}", "", "```", tail, "```", ""]

    lines += [
        "## What to do",
        "",
        "Fix the failure above, then re-check with:",
        "",
        "```",
        str(summary["rerun"] or "wring verify"),
        "```",
        "",
        "The whole evidence bundle — diff, status, every gate's logs — is at "
        f"`{summary['evidence_dir']}`.",
        "Do not edit anything under `.wringer/`: that is the evidence, not the code.",
        "",
    ]
    return "\n".join(lines)


def _tail(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    if not lines:
        return ""
    kept = lines[-BRIEF_TAIL_LINES:]
    dropped = len(lines) - len(kept)
    note = f"[... {dropped} earlier lines, see the bundle ...]\n" if dropped else ""
    return note + "\n".join(kept)


_REASONS = {
    "converged": "every required gate passed",
    "max_iterations": "the iteration budget ran out",
    "no_progress": "the worker changed nothing, so the gates would say the same",
    "oscillating": "the same failure came back, so the worker is not converging",
    "budget_exhausted": "the wall-clock budget ran out",
    "interrupted": "stopped before it finished",
}


def _write_summary(
    bundle: Bundle,
    state: git.RepoState,
    status: str,
    reason: str,
    iterations: int,
    final_run: str | None,
) -> None:
    events = [
        json.loads(line)
        for line in (bundle.directory / EVENTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    verifies = {e["iteration"]: e for e in events if e["type"] == "verify.finished"}
    workers = {e["iteration"]: e for e in events if e["type"] == "worker.finished"}

    name = state.root.name or str(state.root)
    head = f"`{state.head_sha[:7]}`" if state.head_sha else "not a git repository"
    lines = [
        f"# wring run — {bundle.loop_id}",
        "",
        f"- repo: **{name}** @ {head}",
        f"- started: {bundle.started_at.replace(microsecond=0).isoformat()}",
        f"- result: **{status}** — {_REASONS.get(reason, reason)}",
        f"- iterations: {iterations}",
        "",
        "| iteration | verify | worker | evidence |",
        "|---|---|---|---|",
    ]
    for number in sorted(verifies):
        row = verifies[number]
        outcome = row["status"]
        if row.get("failed_gate"):
            outcome += f" (`{row['failed_gate']}`)"
        worker = workers.get(number)
        if worker is None:
            told = "—"
        else:
            told = f"exit {worker['exit_code']}"
            if worker.get("timed_out"):
                told += ", timed out"
        lines.append(f"| {number} | {outcome} | {told} | `{row['evidence_dir']}` |")

    if final_run:
        lines += ["", f"Final verification: `{final_run}`"]
    (bundle.directory / SUMMARY_FILENAME).write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
