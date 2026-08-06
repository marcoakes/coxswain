"""`wring verify --prove` — prove the gates can fail (SPEC_VACUITY_V0.md).

> The agent wrote tautological tests, its gates pass, and the green tick means
> nothing — reward-hacking by another name, and the failure mode everyone in
> this field fears and nobody guards. The counter is deterministic: **if the
> gates still pass without the change, they never tested it.**

The mechanism is a scratch worktree detached at HEAD. That tree *is* the
pre-change tree — tracked edits absent, untracked files naturally missing — so
there is no reverse-patching and no cleverness. Run the same declared gates
there and compare:

| changed tree | pre-change tree | meaning |
|---|---|---|
| pass | **fail** | the gate tests this change — what proof looks like |
| pass | **pass** | the gate is *insensitive* to this change |

A lint gate passing on both is ordinary. **Every** gate passing on both is the
signal, and the verdict is `gates_vacuous`.

## The trap this module exists not to fall into

`git worktree add --detach` carries **tracked files and nothing else** — no
`.venv`, no `node_modules`, no build cache, because those are gitignored. A
gate of `pytest -q` therefore runs where the project is not installed, and
fails. The table above reads *pass on changed, fail on pre-change* and
concludes **the gate tests this change**.

That is a false `proven`, and it would fire on every run in any repo whose
dependencies are not committed, however tautological the tests — the feature
built to catch reward-hacking certifying it. Two things close it, and this
module does not work without both:

- **`run.prove_setup`**, an optional command run in the scratch worktree
  before the pre-change gates (`uv sync --frozen`, `npm ci`). Every repo
  already has it, because it is in their CI. If it fails the verdict is
  `inconclusive` — never `proven`, and never silently dropped.
- **every `sensitive` row cites the failure it rests on.**
  `ModuleNotFoundError: No module named 'yourproject'` is then instantly
  legible as a broken environment rather than as a caught regression. The
  failure is deliberately NOT auto-classified: a verdict that shows its
  working is the product, and one that hides it is the thing this spec exists
  to prevent.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wringer import config, gates

SCHEMA_VERSION = "wringer.vacuity.v1"
VACUITY_FILENAME = "vacuity.json"
# The pre-change gate logs live here, in the bundle: evidence, not summary.
# A reader who doubts a `sensitive` row can read both trees' output.
VACUITY_DIRNAME = "vacuity"

PROVEN = "proven"
GATES_VACUOUS = "gates_vacuous"
NOT_APPLICABLE = "not_applicable"
INCONCLUSIVE = "inconclusive"

# How long `run.prove_setup` may take. Generous — it is `npm ci` on a cold
# cache — and bounded, because an unbounded setup command would hang the
# verification it is meant to strengthen.
SETUP_TIMEOUT_SECONDS = 900

_FIX = "write a test that fails without your change"


@dataclass
class GateRow:
    gate_id: str
    changed: str
    pre_change: str
    sensitive: bool
    # The line the `sensitive` verdict rests on: WHY the gate failed on the
    # pre-change tree. Present exactly when `sensitive` is true, because that
    # is the row whose meaning depends on it.
    cites: str | None = None
    pre_change_log: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "changed": self.changed,
            "pre_change": self.pre_change,
            "sensitive": self.sensitive,
            "cites": self.cites,
            "pre_change_log": self.pre_change_log,
        }


@dataclass
class Result:
    verdict: str
    reason: str
    rows: list[GateRow] = field(default_factory=list)
    worktree_ms: int = 0
    prove_ms: int = 0
    setup: dict[str, Any] | None = None

    @property
    def insensitive(self) -> list[str]:
        return [row.gate_id for row in self.rows if not row.sensitive]

    def as_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "verdict": self.verdict,
            "reason": self.reason,
            # No ceiling key exists anywhere in the config, by ruling. These
            # are here so a repo decides with numbers instead of guessing a
            # threshold — and so a slow prove pass becomes the same problem as
            # slow gates, which people already know how to think about.
            "worktree_ms": self.worktree_ms,
            "prove_ms": self.prove_ms,
            "setup": self.setup,
            "gates": [row.as_json() for row in self.rows],
        }


def not_applicable(reason: str) -> Result:
    return Result(verdict=NOT_APPLICABLE, reason=reason)


def prove(
    root: Path,
    cfg: config.Config,
    planned: list[tuple[int, config.Gate]],
    results: list[gates.GateResult],
    bundle_dir: Path,
    dirty: bool,
) -> Result:
    """Run the declared gates against the pre-change tree and compare.

    Called only when every required gate has already passed — there is nothing
    to prove about a failure, which is law 3's shape.
    """
    from wringer import fleet

    if not dirty:
        return not_applicable(
            "the working tree has no changes, so there is nothing for the "
            "gates to be insensitive to"
        )
    changed_by_id = {result.gate.id: result for result in results}
    if not changed_by_id:
        return not_applicable("no gates ran, so there is nothing to compare")

    logs = bundle_dir / VACUITY_DIRNAME
    logs.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    # Named for the RUN, not just "prove". A fleet whose children share a root
    # — `worktree: false`, the default — would otherwise have every child
    # proving into the same scratch path, and `make_worktree` removes an
    # existing one before creating it, so the collision would be silent: one
    # child's pre-change gates running in a tree another child was deleting.
    worktree = fleet.make_worktree(root, f"prove-{bundle_dir.name}")
    worktree_ms = int((time.monotonic() - started) * 1000)
    if worktree is None:
        return Result(
            verdict=INCONCLUSIVE,
            reason=(
                "a scratch worktree could not be created, so the pre-change "
                "tree could not be built. Nothing was proven either way"
            ),
            worktree_ms=worktree_ms,
        )

    prove_started = time.monotonic()
    try:
        setup = _run_setup(cfg, worktree, logs)
        if setup is not None and not setup["ok"]:
            return Result(
                verdict=INCONCLUSIVE,
                reason=(
                    f"`run.prove_setup` failed in the scratch worktree "
                    f"({setup['cites']}), so the pre-change gates would have "
                    "failed on a broken environment rather than on the change. "
                    "That is not proof — fix the setup command and prove again"
                ),
                worktree_ms=worktree_ms,
                prove_ms=int((time.monotonic() - prove_started) * 1000),
                setup=setup,
            )

        rows: list[GateRow] = []
        for index, gate in planned:
            changed = changed_by_id.get(gate.id)
            if changed is None:
                continue  # skipped: it never ran on the changed tree either
            if gate.optional:
                # Proving an OPTIONAL gate is out of scope by ruling: it does
                # not decide the outcome, so its sensitivity cannot make a
                # green tick mean more or less than it did.
                continue
            row = _compare(gate, index, changed, worktree, logs, bundle_dir)
            rows.append(row)
    finally:
        # Pass, fail or Ctrl-C — the scratch tree goes.
        fleet.remove_worktree(root, worktree)

    prove_ms = int((time.monotonic() - prove_started) * 1000)
    if not rows:
        return Result(
            verdict=NOT_APPLICABLE,
            reason=(
                "every gate that ran is optional, and an optional gate does "
                "not decide the outcome"
            ),
            worktree_ms=worktree_ms,
            prove_ms=prove_ms,
            setup=setup,
        )

    if any(row.sensitive for row in rows):
        sensitive = [row.gate_id for row in rows if row.sensitive]
        return Result(
            verdict=PROVEN,
            reason=(
                f"{', '.join(sensitive)} failed on the pre-change tree, so the "
                "gates test this change"
            ),
            rows=rows,
            worktree_ms=worktree_ms,
            prove_ms=prove_ms,
            setup=setup,
        )
    return Result(
        verdict=GATES_VACUOUS,
        reason=(
            f"every required gate passed without the change too "
            f"({', '.join(row.gate_id for row in rows)}), so they proved "
            f"nothing about it — {_FIX}"
        ),
        rows=rows,
        worktree_ms=worktree_ms,
        prove_ms=prove_ms,
        setup=setup,
    )


def _run_setup(
    cfg: config.Config, worktree: Path, logs: Path
) -> dict[str, Any] | None:
    """`run.prove_setup` in the scratch worktree, if the repo declared one."""
    command = cfg.run.prove_setup if cfg.run is not None else None
    if not command:
        return None
    setup_gate = config.Gate(
        id="prove_setup", run=command, timeout=SETUP_TIMEOUT_SECONDS
    )
    result = gates.run(
        setup_gate,
        cwd=worktree,
        stdout_path=logs / "prove_setup.stdout.log",
        stderr_path=logs / "prove_setup.stderr.log",
    )
    return {
        "command": command,
        "ok": result.passed,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
        "cites": _cite(result),
    }


def _compare(
    gate: config.Gate,
    index: int,
    changed: gates.GateResult,
    worktree: Path,
    logs: Path,
    bundle_dir: Path,
) -> GateRow:
    stdout_path = logs / f"{index:03d}_{gate.id}.stdout.log"
    stderr_path = logs / f"{index:03d}_{gate.id}.stderr.log"
    pre = gates.run(
        gate, cwd=worktree, stdout_path=stdout_path, stderr_path=stderr_path
    )
    sensitive = changed.passed and not pre.passed
    return GateRow(
        gate_id=gate.id,
        changed=changed.status,
        pre_change=pre.status,
        sensitive=sensitive,
        # Cited only where it is load-bearing: a `sensitive` row MEANS "this
        # failed without the change", and the reader has to be able to see
        # whether that failure was the change or a missing environment.
        cites=_cite(pre) if sensitive else None,
        pre_change_log=stdout_path.relative_to(bundle_dir).as_posix(),
    )


def _cite(result: gates.GateResult) -> str:
    """One line saying why a gate failed, for a row whose meaning rests on it.

    The **last** informative line of stderr, then of stdout. Measured against
    the shapes that actually turn up rather than reasoned about:

        ModuleNotFoundError: No module named 'yourproject'   <- last of stderr
        cat: vendor/lib.py: No such file or directory        <- the only line
        FAILED (failures=1)                                  <- last of stderr
        sh: yourtool: command not found                      <- the only line

    Taking the FIRST line instead gets `Traceback (most recent call last):`
    from a Python failure and a row of `=` from unittest — both true and
    neither any use, which was the first version of this function.

    "Informative" excludes separator rules: a line of one punctuation
    character repeated is the thing a test runner prints AROUND the message.

    Deliberately NOT classified into "environment" or "regression". Making
    the failure visible is the product; guessing at its meaning would be the
    cleverness this spec exists to refuse.
    """
    if result.timed_out:
        return f"timed out after {result.gate.timeout}s"
    for path in (result.stderr_path, result.stdout_path):
        lines = _lines(path)
        if lines:
            return lines[-1]
    return f"exit {result.exit_code}, and it printed nothing"


def _lines(path: Path) -> list[str]:
    """Non-blank, non-separator lines. See `_cite`."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    kept = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if len(set(line)) == 1 and not line[0].isalnum():
            continue  # ==========, ----------, ..........
        kept.append(line)
    return kept


def write(bundle_dir: Path, result: Result) -> Path:
    """`vacuity.json`, a SIBLING file — `wringer.evidence.v1` is frozen.

    Written BEFORE `digests.json`, so the bundle's own tamper-evidence covers
    the verdict and the pre-change logs beside it.
    """
    path = bundle_dir / VACUITY_FILENAME
    path.write_text(json.dumps(result.as_json(), indent=2) + "\n", encoding="utf-8")
    return path


def read_verdict(run_dir: Path) -> Result | None:
    """The recorded verdict, or None when the run never proved anything.

    Total by construction: a bundle whose `vacuity.json` cannot be read is
    treated as one that has none. The refusal downstream is for a run that
    MEASURED and came back saying nothing was proven, and a damaged file is
    not that.
    """
    path = run_dir / VACUITY_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("verdict"), str):
        return None
    rows = []
    for entry in raw.get("gates", []) or []:
        if isinstance(entry, dict):
            rows.append(
                GateRow(
                    gate_id=str(entry.get("gate_id")),
                    changed=str(entry.get("changed")),
                    pre_change=str(entry.get("pre_change")),
                    sensitive=bool(entry.get("sensitive")),
                    cites=entry.get("cites"),
                    pre_change_log=entry.get("pre_change_log"),
                )
            )
    return Result(
        verdict=raw["verdict"],
        reason=str(raw.get("reason", "")),
        rows=rows,
        worktree_ms=int(raw.get("worktree_ms") or 0),
        prove_ms=int(raw.get("prove_ms") or 0),
        setup=raw.get("setup"),
    )


def refusal_message(run_name: str, result: Result, vacuity_path: str) -> str:
    """Why `wring deliver` refuses, said so the reader can act on it.

    A refusal that only says *no* converts this feature into something people
    turn off. Same standard as the failing-gate refusal, which names the gate
    rather than saying "a gate failed".
    """
    insensitive = result.insensitive
    named = ", ".join(f"`{gate_id}`" for gate_id in insensitive[:5])
    return (
        f"refusing to deliver {run_name} — it recorded `{GATES_VACUOUS}`. "
        f"{named} passed on the pre-change tree too, so they proved nothing "
        f"about this change. The fix is to {_FIX}, then verify again; both "
        f"trees' output is in {vacuity_path}/ if you want to see why. There is "
        "no flag for this — make the evidence better, not the check weaker"
    )
