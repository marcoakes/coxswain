"""Run ids and the evidence writer."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cox import evidence
from cox.git import RepoState

RUN_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")

NOW = datetime(2026, 7, 30, 8, 6, 1, 123456, tzinfo=timezone(timedelta(hours=1)))


def test_run_id_has_the_spec_shape():
    run_id = evidence.new_run_id(NOW)
    assert RUN_ID.match(run_id), run_id
    assert run_id.startswith("20260730-080601-")


def test_run_ids_differ_within_the_same_second():
    ids = {evidence.new_run_id(NOW) for _ in range(50)}
    assert len(ids) > 1


def test_create_makes_a_fresh_directory(tmp_path: Path):
    bundle = evidence.Bundle.create(tmp_path / ".cox" / "runs", now=NOW)
    assert bundle.directory.is_dir()
    assert bundle.directory.name == bundle.run_id
    assert bundle.directory.parent == tmp_path / ".cox" / "runs"
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
    assert recorded == [
        {"type": "run.started", "run_id": bundle.run_id, "sha": None},
        {
            "type": "gate.finished",
            "gate_id": "test",
            "exit_code": 1,
            "duration_ms": 9231,
        },
    ]
    # every event is placeable in time, and in order
    parsed = [datetime.fromisoformat(stamp) for stamp in stamps]
    assert all(stamp.tzinfo is not None for stamp in parsed)
    assert parsed == sorted(parsed)


def test_gate_result_json_is_exactly_the_contract(tmp_path: Path):
    from cox.config import Gate
    from cox.gates import GateResult

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
        "schema_version": "cox.evidence.v1",
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
