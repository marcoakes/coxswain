"""Write the evidence bundle — the product.

Boring, stable, grep-friendly (SPEC_VERIFY_V0.md §The evidence
bundle). `evidence.jsonl` is append-only, one JSON object per line;
`manifest.json` is the run's index and carries `schema_version` so future
readers can tell what they are holding. Day 1 writes those two files;
`summary.md`, `diff.patch`, `status.txt` and `gates/NNN_id/` arrive with
the Day-2 and Day-3 bolts.

Nothing here uploads anywhere. Ever.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wringer import gates
from wringer.git import RepoState
from wringer.redact import Redactor

SCHEMA_VERSION = "wringer.evidence.v1"
EVIDENCE_FILENAME = "evidence.jsonl"
MANIFEST_FILENAME = "manifest.json"
# A sibling file, not a manifest key: `wringer.evidence.v1` shipped in v0.1.0
# and is frozen, so the manifest cannot grow one. Additive — a reader that
# does not know this file ignores it, and every v1 bundle stays a v1 bundle.
#
# The `prev_hash` chain makes the LEDGER tamper-evident and says nothing about
# the rest of the bundle: edit `gates/001_test/stdout.log` and no chain
# notices. `wring attest` (P5) cannot make its central claim — "proven by
# gates G, and none of it has been altered since" — without this, and every
# bundle written before it exists is a bundle that can never be attested.
DIGESTS_FILENAME = "digests.json"
DIGESTS_SCHEMA_VERSION = "wringer.digests.v1"
RESULT_FILENAME = "result.json"
DIFF_FILENAME = "diff.patch"
STATUS_FILENAME = "status.txt"
# Rendered by summary.py, but named here with the bundle's other files: what
# a run writes has to be knowable in one place to be removable in one place.
SUMMARY_FILENAME = "summary.md"
GATES_DIRNAME = "gates"
RUNS_DIRNAME = Path(".wringer") / "runs"

# The id's timestamp prefix: `20260730-070601` of `20260730-070601-a13f`.
_RUN_ID_TIME_FORMAT = "%Y%m%d-%H%M%S"
_RUN_ID_TIME_LENGTH = 15

_RUN_ID_ATTEMPTS = 64

# Files a run directory may use to record when it began, in the order they
# are looked for. `verdict.json` is `judge.VERDICT_FILENAME`, spelled out
# rather than imported because judge.py imports this module; both files carry
# `started_at` as local-time-with-offset, which is the whole point of
# preferring them to a directory name.
_STARTED_AT_RECORDS = (MANIFEST_FILENAME, "verdict.json")


class EvidenceError(Exception):
    """The bundle could not be written (CLI exit code 2)."""


def latest_run(runs_root: Path) -> Path | None:
    """The most recent run directory, or None if there are none."""
    if not runs_root.is_dir():
        return None
    runs = [path for path in runs_root.iterdir() if path.is_dir()]
    if not runs:
        return None
    return max(runs, key=_started_at)


def _started_at(run_dir: Path) -> tuple[float, float]:
    """When a run began, for ordering — from its own record, its id, or mtime.

    Epoch seconds, so the three sources are actually comparable.

    **The record wins.** `started_at` carries a UTC offset, so it is
    unambiguous, and a directory NAME is not: ids were stamped in local time
    until 2026-08-05, and a container writing UTC against a host writing BST
    produced ids that sorted forty minutes from the truth. Ids are UTC now;
    reading the record rather than the name is what stops the next timezone
    mattering at all.

    **Every fallback is read as UTC too**, because that is what an id means
    in this version. Getting this wrong is not theoretical — the first
    attempt at this function kept the old local-time parse for directories
    with no record, on the reasoning that it preserved existing behaviour,
    and that quietly misdated by the host's offset the two cases that reach
    it most:

      - a loop KILLED mid-flight, which is the only thing `wring resume`
        exists for, and which never reached `loop.write_manifest`;
      - every `wring judge` verdict, which writes `verdict.json` and not a
        manifest — so `wring deliver` picking "the latest verdict" took the
        fallback 100% of the time.

    A directory whose name is not a run id at all is dated by mtime: `--output`
    lets a caller name a directory anything and QUICKSTART teaches exactly
    that, so compared as *text* one letter outranks every real run forever —
    `manual-001` beats `20260730-…` because "m" > "2", and `wring explain`
    would keep diagnosing the manual run however many newer ones landed.

    Within one second an id ends in a *random* suffix, not a counter, so
    mtime breaks that tie too. Two runs landing in the same second is not a
    corner case: it is what a verify-fix-verify loop does all day.
    """
    mtime = run_dir.stat().st_mtime
    recorded = _recorded_started_at(run_dir)
    if recorded is not None:
        return recorded.timestamp(), mtime
    try:
        named = datetime.strptime(
            run_dir.name[:_RUN_ID_TIME_LENGTH], _RUN_ID_TIME_FORMAT
        ).replace(tzinfo=UTC)
    except ValueError:  # not a run id — a caller-named --output directory
        return mtime, mtime
    return named.timestamp(), mtime


def _recorded_started_at(run_dir: Path) -> datetime | None:
    """A run's own record of when it began, or None if it never wrote one.

    More than one kind of directory gets ordered by `latest_run`, and they do
    not all write a `manifest.json`: `wring judge` writes `verdict.json`.
    Both carry `started_at` in the same shape, so both are read here rather
    than each caller being trusted to remember — a safety property that
    depends on every call site getting it right is not one.

    Deliberately total: this is an ordering key, and a bundle too damaged to
    read its own record still has an mtime. Refusing to list runs because one
    of them is corrupt would be the wrong trade for `wring explain`.
    """
    for filename in _STARTED_AT_RECORDS:
        try:
            raw = json.loads((run_dir / filename).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        value = raw.get("started_at")
        if not isinstance(value, str):
            continue
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            continue
    return None


def read_manifest(run_dir: Path) -> dict[str, Any]:
    return _read_json(run_dir / MANIFEST_FILENAME)


def read_events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / EVIDENCE_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvidenceError(f"cannot read {path}: {exc}") from exc
    try:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise EvidenceError(f"{path} holds a malformed event: {exc}") from exc


def read_gate_results(run_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Each executed gate's directory and `result.json`, in declared order —
    which is what `NNN_` prefixes sort into."""
    gates_root = run_dir / GATES_DIRNAME
    if not gates_root.is_dir():
        return []
    rows = []
    for gate_dir in sorted(path for path in gates_root.iterdir() if path.is_dir()):
        result = gate_dir / RESULT_FILENAME
        if result.is_file():
            rows.append((gate_dir, _read_json(result)))
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvidenceError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EvidenceError(f"{path} is not valid JSON: {exc}") from exc


def _clear_previous(directory: Path) -> None:
    """Remove what an earlier run left in a reused `--output` directory.

    One directory must describe one run. `evidence.jsonl` is append-only
    *within* a run, so a reused log would grow into a file describing two;
    worse, a stale `gates/NNN_id/result.json` is read straight back by
    `wring explain`, which is how a bundle ends up saying a gate passed on
    the same screen its summary calls it skipped. A bundle that contradicts
    itself is worse than no bundle at all.

    Only Wringer's own artifacts go: the directory belongs to the caller,
    and anything else they keep in it is theirs.
    """
    for filename in (
        EVIDENCE_FILENAME,
        MANIFEST_FILENAME,
        SUMMARY_FILENAME,
        DIFF_FILENAME,
        STATUS_FILENAME,
    ):
        (directory / filename).unlink(missing_ok=True)
    previous_gates = directory / GATES_DIRNAME
    if previous_gates.is_dir():
        # Not ignore_errors: a gates/ tree we cannot clear would leave last
        # run's verdicts in this run's bundle, and that must be loud.
        shutil.rmtree(previous_gates)


GENESIS_HASH = "0" * 64


def chain_head(ledger: Path) -> str:
    """The hash of the last line of a ledger, or the genesis hash if empty.

    Every event carries the hash of the one before it, so a ledger is a
    chain rather than a list: altering or removing any line breaks every
    hash after it, and appending a forged line requires rewriting the tail.
    This is *tamper-evidence*, not tamper-proofing — anyone who can write
    the file can rewrite the whole chain — but it turns silent edits into
    detectable ones, and that is the difference between evidence and a log.

    The field is written now and **not yet verified by any command**: adding
    it while these schemas are unreleased is nearly free, and adding it
    later would cost a version bump on every bundle in the world.
    `wring attest` / `wring audit` are the slice that will consume it.
    """
    try:
        with ledger.open("rb") as stream:
            last = b""
            for raw in stream:
                if raw.strip():
                    last = raw.rstrip(b"\n")
    except OSError:
        return GENESIS_HASH
    if not last:
        return GENESIS_HASH
    return hashlib.sha256(last).hexdigest()


def deep_scrub(redactor: Redactor, value: Any) -> Any:
    """Erase secrets anywhere inside a value, not just at the top.

    `changed_files` and `untracked` are lists, so a file whose *name* carries
    a secret was reaching `evidence.jsonl` intact while `status.txt` beside it
    in the same bundle said `[REDACTED]`. The guarantee SECURITY.md makes is
    about the bundle, so it cannot hold for some files in it and not others —
    which is also why the loop's own writer uses this same function.
    """
    if isinstance(value, str):
        return redactor.scrub(value)
    if isinstance(value, (list, tuple)):
        # JSON has no tuples; a list is what either one is written as
        return [deep_scrub(redactor, item) for item in value]
    if isinstance(value, dict):
        return {key: deep_scrub(redactor, item) for key, item in value.items()}
    return value


def timestamp() -> str:
    """Local ISO-8601 with offset, to the millisecond — fine enough to order
    two fast gates, coarse enough to stay readable."""
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def new_run_id(now: datetime) -> str:
    """`YYYYMMDD-HHMMSS-<4 hex>` in UTC, e.g. `20260730-070601-a13f`.

    UTC, not local time, because a run id is a directory NAME and names get
    sorted. A container has no reason to share its host's timezone — this
    project's own image resolves to `Etc/UTC` — so a local-time id makes host
    and container runs of the same repository sort against each other
    wrongly. Measured on 2026-08-05: a container run that happened twenty
    minutes AFTER a host run carried an id sorting forty minutes BEFORE it,
    so `ls` and `ls -t` disagreed about which run was newest. For a tool
    whose whole premise is auditable evidence, an ambiguous ordering key is a
    defect rather than a preference.

    `started_at` in the manifest stays local-with-offset. That is the field a
    human reads, and the offset is the part they want.

    Callers pass an aware datetime, so this is a conversion and not a
    reinterpretation.

    The random suffix — not a counter — keeps two runs in the same second
    from colliding without either one having to read the other's state.
    """
    return f"{now.astimezone(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


@dataclass(frozen=True)
class Bundle:
    directory: Path
    run_id: str
    started_at: datetime
    # Held by the bundle rather than passed to each call: "redact before
    # write" is an invariant, and an invariant that depends on every caller
    # remembering is not one.
    redactor: Redactor = Redactor()

    @classmethod
    def create(
        cls,
        runs_root: Path,
        now: datetime | None = None,
        redactor: Redactor | None = None,
    ) -> Bundle:
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
            return cls(
                directory=directory,
                run_id=run_id,
                started_at=started_at,
                redactor=redactor or Redactor(),
            )

        raise EvidenceError(f"could not allocate a run directory under {runs_root}")

    @classmethod
    def at(
        cls,
        directory: Path,
        now: datetime | None = None,
        redactor: Redactor | None = None,
    ) -> Bundle:
        """Use the directory the caller named (`--output`).

        Unlike `create`, this does not refuse an existing directory: naming
        a path is an instruction, and a caller who says `--output` twice
        means to overwrite. The run id becomes the directory's own name, so
        the bundle still identifies itself.
        """
        try:
            directory.mkdir(parents=True, exist_ok=True)
            _clear_previous(directory)
        except OSError as exc:
            raise EvidenceError(f"cannot create {directory}: {exc}") from exc
        return cls(
            directory=directory,
            run_id=directory.name or new_run_id(datetime.now().astimezone()),
            started_at=now if now is not None else datetime.now().astimezone(),
            redactor=redactor or Redactor(),
        )

    def gate_dir(self, index: int, gate_id: str) -> Path:
        """`gates/NNN_<id>/`, NNN being the gate's 1-based position in the
        **declared** order — not its position in this run.

        So `wring verify --gate test` on the spec's example config still
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
        text = self.redactor.scrub(text)
        if text and not text.endswith("\n"):
            text += "\n"
        # Same bound as a gate log: a 500 MB diff is not evidence either.
        data, _ = gates.truncate(text.encode("utf-8"), gates.MAX_LOG_BYTES)
        path = self.directory / filename
        path.write_bytes(data)
        return path

    def write_gate_result(self, gate_dir: Path, result: gates.GateResult) -> Path:
        """`gates/NNN_<id>/result.json` — one gate's row of the contract."""
        payload = {
            "gate_id": result.gate.id,
            "command": self.redactor.scrub(result.gate.run),
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "timed_out": result.timed_out,
            "stdout_truncated": result.stdout_truncated,
            "stderr_truncated": result.stderr_truncated,
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
        scrubbed = {key: self._scrub(value) for key, value in fields.items()}
        path = self.directory / EVIDENCE_FILENAME
        line = json.dumps(
            {
                "type": event_type,
                "ts": timestamp(),
                "prev_hash": chain_head(path),
                **scrubbed,
            }
        )
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def _scrub(self, value: Any) -> Any:
        return deep_scrub(self.redactor, value)

    def write_digests(self) -> Path:
        """Hash every file in the bundle, into a sibling `digests.json`.

        **Written last**, so it covers everything else — including
        `manifest.json` and `summary.md`. It cannot cover itself, which is the
        one thing a reader must understand: `digests.json` proves the bundle
        has not changed *around* it, and a chained ledger proves the ledger.
        Neither proves the digest file itself, and nothing on a disk its owner
        controls could. That is tamper-EVIDENCE, and it is what turns a silent
        edit into a detectable one.

        Paths are POSIX and repo-bundle-relative so a digest computed on Linux
        matches one computed on macOS.
        """
        import hashlib

        entries: dict[str, str] = {}
        for path in sorted(self.directory.rglob("*")):
            if not path.is_file() or path.name == DIGESTS_FILENAME:
                continue
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(65536), b""):
                    digest.update(chunk)
            entries[path.relative_to(self.directory).as_posix()] = digest.hexdigest()

        target = self.directory / DIGESTS_FILENAME
        target.write_text(
            json.dumps(
                {
                    "schema_version": DIGESTS_SCHEMA_VERSION,
                    "algorithm": "sha256",
                    "files": entries,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return target

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
