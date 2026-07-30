"""Write the evidence bundle — the product.

Boring, stable, grep-friendly (SPEC_COX_VERIFY_V0.md §The evidence
bundle). `evidence.jsonl` is append-only, one JSON object per line;
`manifest.json` is the run's index and carries `schema_version` so future
readers can tell what they are holding. Day 1 writes those two files;
`summary.md`, `diff.patch`, `status.txt` and `gates/NNN_id/` arrive with
the Day-2 and Day-3 bolts.

Nothing here uploads anywhere. Ever.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cox.gates import GateResult
from cox.git import RepoState

SCHEMA_VERSION = "cox.evidence.v1"
EVIDENCE_FILENAME = "evidence.jsonl"
MANIFEST_FILENAME = "manifest.json"
RESULT_FILENAME = "result.json"
DIFF_FILENAME = "diff.patch"
STATUS_FILENAME = "status.txt"
GATES_DIRNAME = "gates"
RUNS_DIRNAME = Path(".cox") / "runs"

_RUN_ID_ATTEMPTS = 64


class EvidenceError(Exception):
    """The bundle could not be written (CLI exit code 2)."""


def timestamp() -> str:
    """Local ISO-8601 with offset, to the millisecond — fine enough to order
    two fast gates, coarse enough to stay readable."""
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def new_run_id(now: datetime) -> str:
    """`YYYYMMDD-HHMMSS-<4 hex>` in local time, e.g. `20260730-080601-a13f`.

    The random suffix — not a counter — keeps two runs in the same second
    from colliding without either one having to read the other's state.
    """
    return f"{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


@dataclass(frozen=True)
class Bundle:
    directory: Path
    run_id: str
    started_at: datetime

    @classmethod
    def create(cls, runs_root: Path, now: datetime | None = None) -> Bundle:
        """Allocate `runs_root/<run_id>/`, refusing to reuse a directory."""
        started_at = now if now is not None else datetime.now().astimezone()
        try:
            runs_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise EvidenceError(f"cannot create {runs_root}: {exc}") from exc

        for _ in range(_RUN_ID_ATTEMPTS):
            run_id = new_run_id(started_at)
            directory = runs_root / run_id
            try:
                directory.mkdir(exist_ok=False)
            except FileExistsError:
                continue  # same second, fresh suffix
            except OSError as exc:
                raise EvidenceError(f"cannot create {directory}: {exc}") from exc
            return cls(directory=directory, run_id=run_id, started_at=started_at)

        raise EvidenceError(f"could not allocate a run directory under {runs_root}")

    def gate_dir(self, index: int, gate_id: str) -> Path:
        """`gates/NNN_<id>/`, NNN being the gate's 1-based position in the
        **declared** order — not its position in this run.

        So `cox verify --gate test` on the spec's example config still
        writes `gates/003_test/`: a directory name means the same thing
        whether the run was complete, partial, or a single gate.
        """
        directory = self.directory / GATES_DIRNAME / f"{index:03d}_{gate_id}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def relative(self, path: Path) -> str:
        """A bundle-relative path, for evidence that points at other files."""
        return path.relative_to(self.directory).as_posix()

    def write_capture(self, filename: str, text: str) -> Path:
        """Write one captured git artifact (`diff.patch`, `status.txt`)."""
        if text and not text.endswith("\n"):
            text += "\n"
        path = self.directory / filename
        path.write_text(text, encoding="utf-8")
        return path

    def write_gate_result(self, gate_dir: Path, result: GateResult) -> Path:
        """`gates/NNN_<id>/result.json` — one gate's row of the contract."""
        payload = {
            "gate_id": result.gate.id,
            "command": result.gate.run,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "timed_out": result.timed_out,
            "optional": result.gate.optional,
            "status": result.status,
        }
        path = gate_dir / RESULT_FILENAME
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    def event(self, event_type: str, **fields: Any) -> None:
        """Append one `{"type": ..., "ts": ...}` object to `evidence.jsonl`.

        Every event is stamped: an audit trail whose entries cannot be
        placed in time is a weaker artifact than one that can, and
        `duration_ms` only tells you how long a gate took, not when.
        """
        line = json.dumps({"type": event_type, "ts": timestamp(), **fields})
        with (self.directory / EVIDENCE_FILENAME).open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(line + "\n")

    def write_manifest(
        self, state: RepoState, status: str, failed_gate: str | None
    ) -> None:
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "started_at": self.started_at.replace(microsecond=0).isoformat(),
            "repo": {
                # The bundle lives inside the repo it describes, so the
                # manifest stays portable: paths are repo-relative.
                "root": ".",
                "head_sha": state.head_sha,
                "branch": state.branch,
                "dirty": state.dirty,
            },
            "result": {"status": status, "failed_gate": failed_gate},
        }
        (self.directory / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
