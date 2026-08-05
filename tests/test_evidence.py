"""Run ids and the evidence writer."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from wringer import evidence
from wringer.git import RepoState

RUN_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")

NOW = datetime(2026, 7, 30, 8, 6, 1, 123456, tzinfo=timezone(timedelta(hours=1)))


def stamp(path: Path, when: datetime) -> None:
    """Give a run directory a real mtime.

    Pass an AWARE datetime. Run ids are UTC and every ordering source is
    reduced to epoch seconds, so a naive datetime here would silently mean
    "local" and make these tests pass or fail depending on the machine's
    timezone — which is the exact bug (AC-03) they exist to pin down.
    """
    assert when.tzinfo is not None, "stamp() needs an aware datetime"
    epoch = when.timestamp()
    os.utime(path, (epoch, epoch))


def test_run_id_has_the_spec_shape():
    run_id = evidence.new_run_id(NOW)
    assert RUN_ID.match(run_id), run_id
    # 08:06:01+01:00 is 07:06:01 UTC, and the id is stamped in UTC — see the
    # timezone-invariance test below for why.
    assert run_id.startswith("20260730-070601-")


def test_run_ids_are_the_same_wherever_the_clock_is_set():
    """The AC-03 assertion, verbatim from the field report.

    A container has no reason to share its host's timezone; this project's
    own image resolves to Etc/UTC. On 2026-08-05 a container run that
    happened twenty minutes AFTER a host run of the same repository got an id
    sorting forty minutes BEFORE it, because both were stamped in local time:

        host       20260805-102717-3470   started_at +01:00   (10:27 wall)
        container  20260805-094741-56d0   started_at +00:00   (10:47 wall)

    `run_id` is the directory name, so anything ordering runs lexically
    disagreed with `ls -t`. The id must name one instant, not one instant as
    seen from wherever the process happened to be standing.
    """
    instant = datetime(2026, 8, 5, 9, 47, 41, tzinfo=UTC)

    in_bst = evidence.new_run_id(instant.astimezone(timezone(timedelta(hours=1))))
    in_utc = evidence.new_run_id(instant.astimezone(UTC))
    in_tokyo = evidence.new_run_id(instant.astimezone(timezone(timedelta(hours=9))))

    stamps = {run_id.rsplit("-", 1)[0] for run_id in (in_bst, in_utc, in_tokyo)}
    assert stamps == {"20260805-094741"}


def test_run_ids_differ_within_the_same_second():
    ids = {evidence.new_run_id(NOW) for _ in range(50)}
    assert len(ids) > 1


def test_create_makes_a_fresh_directory(tmp_path: Path):
    bundle = evidence.Bundle.create(tmp_path / ".wringer" / "runs", now=NOW)
    assert bundle.directory.is_dir()
    assert bundle.directory.name == bundle.run_id
    assert bundle.directory.parent == tmp_path / ".wringer" / "runs"
    assert not any(bundle.directory.iterdir())  # nothing written yet


def test_create_regenerates_the_id_on_collision(tmp_path: Path, monkeypatch):
    suffixes = iter(["beef", "beef", "cafe"])
    monkeypatch.setattr(evidence.secrets, "token_hex", lambda _: next(suffixes))

    first = evidence.Bundle.create(tmp_path, now=NOW)
    second = evidence.Bundle.create(tmp_path, now=NOW)

    assert first.run_id.endswith("-beef")
    assert second.run_id.endswith("-cafe")
    assert first.directory != second.directory


def test_create_gives_up_rather_than_reusing_a_directory(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(evidence.secrets, "token_hex", lambda _: "beef")
    evidence.Bundle.create(tmp_path, now=NOW)

    with pytest.raises(evidence.EvidenceError):
        evidence.Bundle.create(tmp_path, now=NOW)


def test_latest_run_is_the_newest_not_the_alphabetically_last(tmp_path: Path):
    """Two runs in the same second are ordered by a random suffix, not a
    counter — so the id alone can call an older run the latest one. That is
    exactly what a verify-fix-verify loop produces."""
    runs = tmp_path / "runs"
    runs.mkdir()
    earlier = runs / "20260730-201936-ffff"  # lexically last, chronologically first
    later = runs / "20260730-201936-0000"
    earlier.mkdir()
    later.mkdir()
    os.utime(earlier, (1, 1))
    os.utime(later, (2, 2))

    assert evidence.latest_run(runs) == later


def test_latest_run_prefers_a_newer_second_over_mtime(tmp_path: Path):
    runs = tmp_path / "runs"
    runs.mkdir()
    older_second = runs / "20260730-201936-ffff"
    newer_second = runs / "20260730-201937-0000"
    older_second.mkdir()
    newer_second.mkdir()
    os.utime(older_second, (9, 9))  # a misleading mtime must not win
    os.utime(newer_second, (2, 2))

    assert evidence.latest_run(runs) == newer_second


def test_latest_run_is_not_hijacked_by_a_manual_name(tmp_path: Path):
    """`--output` lets a caller name a directory anything, and QUICKSTART
    teaches exactly that. Compared as text, "manual-001" outranks every real
    run id forever ("m" > "2"), so `wring explain` would keep diagnosing it
    however many newer runs landed."""
    runs = tmp_path / "runs"
    runs.mkdir()
    manual = runs / "manual-001"
    later = runs / "20260730-201936-0000"
    manual.mkdir()
    later.mkdir()
    # the manual run happened first, six seconds before the real one
    stamp(manual, datetime(2026, 7, 30, 20, 19, 30, tzinfo=UTC))
    stamp(later, datetime(2026, 7, 30, 20, 19, 36, tzinfo=UTC))

    assert evidence.latest_run(runs) == later


def test_latest_run_still_picks_a_manual_run_when_it_is_the_newest(tmp_path: Path):
    """A directory whose name is not a run id is dated by its mtime — which
    means it can win, it just cannot win by spelling."""
    runs = tmp_path / "runs"
    runs.mkdir()
    earlier = runs / "20260730-201936-0000"
    manual = runs / "manual-001"
    earlier.mkdir()
    manual.mkdir()
    stamp(earlier, datetime(2026, 7, 30, 20, 19, 36, tzinfo=UTC))
    stamp(manual, datetime(2026, 7, 30, 20, 19, 40, tzinfo=UTC))

    assert evidence.latest_run(runs) == manual


def test_latest_run_believes_the_manifest_over_the_directory_name(
    tmp_path: Path,
):
    """Belt and braces for AC-03. Stamping ids in UTC is the fix; not
    ordering on the id at all is what makes the fix unnecessary next time.

    Here the names say one thing and the runs' own records say the opposite —
    which is exactly the shape of a directory holding one bundle written
    before the UTC change and one written after. `started_at` carries an
    offset, so it can be believed; a name cannot.
    """
    runs = tmp_path / "runs"
    runs.mkdir()
    looks_newer = runs / "20260805-102717-3470"  # name sorts last
    really_newer = runs / "20260805-094741-56d0"  # ran 20 minutes later
    for directory, started in (
        (looks_newer, "2026-08-05T10:27:17+01:00"),  # 09:27 UTC
        (really_newer, "2026-08-05T09:47:41+00:00"),  # 09:47 UTC
    ):
        directory.mkdir()
        (directory / evidence.MANIFEST_FILENAME).write_text(
            json.dumps({"started_at": started}), encoding="utf-8"
        )
    # mtimes deliberately agree with the names, not the truth, so only the
    # manifest can get this right.
    os.utime(really_newer, (1, 1))
    os.utime(looks_newer, (2, 2))

    assert evidence.latest_run(runs) == really_newer


def test_a_run_with_no_record_is_still_dated_in_utc(tmp_path: Path):
    """The case the first attempt at this got wrong, in both directions.

    A directory with no record falls back to the timestamp in its id. Ids are
    UTC, so the fallback must read UTC — the first version kept the old local
    parse "to preserve behaviour" and thereby misdated every record-less
    directory by the host's offset. East of UTC that hides a newer run;
    west of UTC an abandoned one outranks its successors.

    Not a corner case. A loop KILLED mid-flight never reaches
    `loop.write_manifest`, and killed loops are the only thing `wring resume`
    exists for.
    """
    runs = tmp_path / "runs"
    runs.mkdir()
    # 09:47:41 UTC — no manifest, so the id is all there is.
    crashed = runs / "20260805-094741-56d0"
    crashed.mkdir()
    os.utime(crashed, (1, 1))  # a useless mtime, like a killed process leaves

    # A complete run one minute later, by its own record.
    finished = runs / "20260805-094841-0000"
    finished.mkdir()
    (finished / evidence.MANIFEST_FILENAME).write_text(
        json.dumps({"started_at": "2026-08-05T10:48:41+01:00"}), encoding="utf-8"
    )
    os.utime(finished, (2, 2))

    assert evidence.latest_run(runs) == finished

    # And the other way round: the record-less one really is newer.
    later_crash = runs / "20260805-095000-abcd"
    later_crash.mkdir()
    os.utime(later_crash, (3, 3))
    assert evidence.latest_run(runs) == later_crash


def test_latest_run_reads_a_judge_verdicts_own_record(tmp_path: Path):
    """`wring judge` writes `verdict.json`, not `manifest.json`, and `wring
    deliver` orders those directories with this same function. Looking only
    for a manifest meant every verdict fell through to the id — 100% of the
    time, for a whole command."""
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()
    looks_newer = verdicts / "20260805-102717-3470"
    really_newer = verdicts / "20260805-094741-56d0"
    for directory, started in (
        (looks_newer, "2026-08-05T10:27:17+01:00"),  # 09:27 UTC
        (really_newer, "2026-08-05T09:47:41+00:00"),  # 09:47 UTC
    ):
        directory.mkdir()
        (directory / "verdict.json").write_text(
            json.dumps({"started_at": started}), encoding="utf-8"
        )
    os.utime(really_newer, (1, 1))
    os.utime(looks_newer, (2, 2))

    assert evidence.latest_run(verdicts) == really_newer


def test_latest_run_survives_a_manifest_it_cannot_read(tmp_path: Path):
    """An ordering key must be total. A bundle too damaged to parse still
    has an mtime, and refusing to list runs because one is corrupt would be
    the wrong trade for `wring explain`."""
    runs = tmp_path / "runs"
    runs.mkdir()
    broken = runs / "20260805-094741-56d0"
    broken.mkdir()
    (broken / evidence.MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")

    assert evidence.latest_run(runs) == broken


def test_latest_run_with_no_runs_is_none(tmp_path: Path):
    assert evidence.latest_run(tmp_path / "nothing-here") is None


def test_at_clears_what_the_previous_run_left(tmp_path: Path):
    """One directory describes one run. A stale `result.json` is read
    straight back by `wring explain`, which is how a bundle ends up calling
    a gate passed on the same screen its summary calls it skipped."""
    directory = tmp_path / "manual-001"
    first = evidence.Bundle.at(directory, now=NOW)
    first.event("run.started", run_id=first.run_id)
    for filename in (
        evidence.MANIFEST_FILENAME,
        evidence.SUMMARY_FILENAME,
        evidence.DIFF_FILENAME,
        evidence.STATUS_FILENAME,
    ):
        (directory / filename).write_text("last run's", encoding="utf-8")
    stale = first.gate_dir(2, "test")
    (stale / evidence.RESULT_FILENAME).write_text('{"status": "passed"}', "utf-8")
    mine = directory / "notes.txt"
    mine.write_text("the caller's own file", encoding="utf-8")

    evidence.Bundle.at(directory, now=NOW)

    assert not (directory / evidence.EVIDENCE_FILENAME).exists()
    assert not (directory / evidence.MANIFEST_FILENAME).exists()
    assert not (directory / evidence.SUMMARY_FILENAME).exists()
    assert not (directory / evidence.DIFF_FILENAME).exists()
    assert not (directory / evidence.STATUS_FILENAME).exists()
    assert not stale.exists()
    # the directory belongs to the caller: only Wringer's artifacts go
    assert mine.read_text(encoding="utf-8") == "the caller's own file"


def test_the_ledger_is_a_chain_not_a_list(tmp_path: Path):
    """Each line carries the hash of the whole line before it, so the order
    is cryptographically fixed rather than merely written down."""
    import hashlib

    bundle = evidence.Bundle.create(tmp_path, now=NOW)
    for n in range(4):
        bundle.event("gate.finished", gate_id=f"g{n}", exit_code=0, duration_ms=n)

    lines = (
        (bundle.directory / evidence.EVIDENCE_FILENAME)
        .read_bytes()
        .splitlines()
    )
    events = [json.loads(line) for line in lines]

    assert events[0]["prev_hash"] == evidence.GENESIS_HASH
    for previous, event in zip(lines, events[1:], strict=False):
        assert event["prev_hash"] == hashlib.sha256(previous).hexdigest()


def test_an_edited_ledger_breaks_its_chain(tmp_path: Path):
    """The whole point: a silent edit stops being silent. This is what
    `wring audit` will one day check — the field is written now because
    adding it later would cost a version bump on every bundle in the world.
    """
    import hashlib

    bundle = evidence.Bundle.create(tmp_path, now=NOW)
    bundle.event("gate.finished", gate_id="honest", exit_code=1, duration_ms=1)
    bundle.event("run.finished", status="failed", failed_gate="honest")

    ledger = bundle.directory / evidence.EVIDENCE_FILENAME
    lines = ledger.read_bytes().splitlines()
    # someone rewrites history: the failure becomes a pass
    lines[0] = lines[0].replace(b'"exit_code": 1', b'"exit_code": 0')
    ledger.write_bytes(b"\n".join(lines) + b"\n")

    events = [json.loads(line) for line in ledger.read_bytes().splitlines()]
    recomputed = hashlib.sha256(ledger.read_bytes().splitlines()[0]).hexdigest()

    assert events[1]["prev_hash"] != recomputed, "the tamper went undetected"


def test_the_chain_head_of_an_absent_ledger_is_genesis(tmp_path: Path):
    assert evidence.chain_head(tmp_path / "nothing.jsonl") == evidence.GENESIS_HASH


def test_gate_dir_is_named_for_the_declared_position(tmp_path: Path):
    bundle = evidence.Bundle.create(tmp_path, now=NOW)

    third = bundle.gate_dir(3, "test")

    assert third.is_dir()
    # NNN follows the config, not the run — a --gate run keeps its number
    assert third.relative_to(bundle.directory).as_posix() == "gates/003_test"
    assert bundle.relative(third / "stdout.log") == "gates/003_test/stdout.log"


def test_events_append_one_json_object_per_line(tmp_path: Path):
    bundle = evidence.Bundle.create(tmp_path, now=NOW)
    bundle.event("run.started", run_id=bundle.run_id, sha=None)
    bundle.event("gate.finished", gate_id="test", exit_code=1, duration_ms=9231)

    lines = (
        (bundle.directory / evidence.EVIDENCE_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    )
    recorded = [json.loads(line) for line in lines]
    stamps = [event.pop("ts") for event in recorded]
    chain = [event.pop("prev_hash") for event in recorded]
    assert recorded == [
        {"type": "run.started", "run_id": bundle.run_id, "sha": None},
        {
            "type": "gate.finished",
            "gate_id": "test",
            "exit_code": 1,
            "duration_ms": 9231,
        },
    ]
    # the chain links each line to the one before it: the first is genesis,
    # and each later link is the sha256 of the previous whole line
    assert chain[0] == evidence.GENESIS_HASH
    assert len(set(chain)) == len(chain)
    # every event is placeable in time, and in order
    parsed = [datetime.fromisoformat(stamp) for stamp in stamps]
    assert all(stamp.tzinfo is not None for stamp in parsed)
    assert parsed == sorted(parsed)


def test_events_scrub_secrets_inside_lists(tmp_path: Path):
    """Redaction covers the bundle, so it cannot hold for some files in it
    and not others: a path whose *name* carried a secret was reaching
    evidence.jsonl intact while status.txt beside it said [REDACTED]."""
    from wringer.redact import Redactor

    bundle = evidence.Bundle.create(
        tmp_path, now=NOW, redactor=Redactor(("hushhush12345",))
    )

    bundle.event(
        "git.status",
        dirty=True,
        changed_files=["src/hushhush12345.py"],
        untracked=["hushhush12345.txt"],
    )

    written = (bundle.directory / evidence.EVIDENCE_FILENAME).read_text("utf-8")
    assert "hushhush12345" not in written
    recorded = json.loads(written)
    assert recorded["changed_files"] == ["src/[REDACTED].py"]
    assert recorded["untracked"] == ["[REDACTED].txt"]
    assert recorded["dirty"] is True  # non-strings pass through untouched


def test_gate_result_json_is_exactly_the_contract(tmp_path: Path):
    from wringer.config import Gate
    from wringer.gates import GateResult

    bundle = evidence.Bundle.create(tmp_path, now=NOW)
    gate = Gate(id="test", run="make test", timeout=300)
    gate_dir = bundle.gate_dir(2, gate.id)
    result = GateResult(
        gate=gate,
        exit_code=1,
        duration_ms=9231,
        timed_out=False,
        stdout_path=gate_dir / "stdout.log",
        stderr_path=gate_dir / "stderr.log",
    )

    written = bundle.write_gate_result(gate_dir, result)

    assert written == gate_dir / "result.json"
    assert json.loads(written.read_text(encoding="utf-8")) == {
        "gate_id": "test",
        "command": "make test",
        "exit_code": 1,
        "duration_ms": 9231,
        "timed_out": False,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "optional": False,
        "status": "failed",
    }


def test_manifest_matches_the_spec_shape(tmp_path: Path):
    bundle = evidence.Bundle.create(tmp_path, now=NOW)
    state = RepoState(
        root=tmp_path, head_sha="abc123", branch="main", dirty=True
    )
    bundle.write_manifest(state=state, status="failed", failed_gate="test")

    manifest = json.loads(
        (bundle.directory / evidence.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest == {
        "schema_version": "wringer.evidence.v1",
        "run_id": bundle.run_id,
        # local time with offset, seconds precision
        "started_at": "2026-07-30T08:06:01+01:00",
        "repo": {
            "root": ".",
            "head_sha": "abc123",
            "branch": "main",
            "dirty": True,
        },
        "result": {"status": "failed", "failed_gate": "test"},
    }
