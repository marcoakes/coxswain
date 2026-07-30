"""`cox verify` — one gate, an evidence bundle, contract exit codes."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from cox import cli, evidence

SHA = re.compile(r"^[0-9a-f]{40}$")

ONE_PASSING_GATE = """\
version: 1
gates:
  - id: unit
    run: "true"
"""

ONE_FAILING_GATE = """\
version: 1
gates:
  - id: unit
    run: "false"
"""

THREE_GATES = """\
version: 1
gates:
  - id: format
    run: "true"
  - id: lint
    run: "true"
  - id: test
    run: "true"
"""


def bundles(root: Path) -> list[Path]:
    runs = root / evidence.RUNS_DIRNAME
    return sorted(runs.iterdir()) if runs.is_dir() else []


def only_bundle(root: Path) -> Path:
    found = bundles(root)
    assert len(found) == 1, found
    return found[0]


def events(bundle: Path) -> list[dict]:
    text = (bundle / evidence.EVIDENCE_FILENAME).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def manifest(bundle: Path) -> dict:
    return json.loads(
        (bundle / evidence.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )


def test_passing_gate_exits_zero_and_writes_the_full_bundle(
    repo, write_config, monkeypatch, capsys
):
    write_config(repo, ONE_PASSING_GATE)
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_OK

    bundle = only_bundle(repo)
    recorded = events(bundle)
    assert [event["type"] for event in recorded] == [
        "run.started",
        "gate.started",
        "gate.finished",
        "run.finished",
    ]

    started, gate_started, gate_finished, finished = recorded
    assert started["run_id"] == bundle.name
    assert started["cox_version"] == cli.__version__
    assert started["repo"] == repo.name
    assert SHA.match(started["sha"]), started["sha"]
    assert gate_started == {
        "type": "gate.started",
        "gate_id": "unit",
        "command": "true",
    }
    assert gate_finished["gate_id"] == "unit"
    assert gate_finished["exit_code"] == 0
    assert isinstance(gate_finished["duration_ms"], int)
    assert gate_finished["duration_ms"] >= 0
    assert finished == {"type": "run.finished", "status": "passed"}

    recorded_manifest = manifest(bundle)
    assert recorded_manifest["schema_version"] == "cox.evidence.v1"
    assert recorded_manifest["run_id"] == bundle.name
    # local ISO-8601 with a UTC offset
    assert datetime.fromisoformat(recorded_manifest["started_at"]).tzinfo is not None
    assert recorded_manifest["repo"] == {
        "root": ".",
        "head_sha": started["sha"],
        "branch": "main",
        # the untracked .cox.yaml we just wrote
        "dirty": True,
    }
    assert recorded_manifest["result"] == {"status": "passed", "failed_gate": None}

    out = capsys.readouterr().out
    assert "✓ unit passed" in out
    assert "Evidence written to:" in out
    assert f".cox/runs/{bundle.name}/" in out
    assert "rerun" not in out


def test_failing_required_gate_exits_one_and_names_the_gate(
    repo, write_config, monkeypatch, capsys
):
    write_config(repo, ONE_FAILING_GATE)
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_GATE_FAILED

    bundle = only_bundle(repo)
    gate_finished, finished = events(bundle)[2:]
    assert gate_finished["exit_code"] == 1
    assert finished == {
        "type": "run.finished",
        "status": "failed",
        "failed_gate": "unit",
    }
    assert manifest(bundle)["result"] == {"status": "failed", "failed_gate": "unit"}

    out = capsys.readouterr().out
    assert "✗ unit failed" in out
    assert "rerun cox verify --gate unit" in out


def test_optional_gate_failure_is_recorded_but_the_run_passes(
    repo, write_config, monkeypatch, capsys
):
    write_config(
        repo,
        """\
version: 1
gates:
  - id: format
    run: "false"
    optional: true
""",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_OK

    bundle = only_bundle(repo)
    gate_finished, finished = events(bundle)[2:]
    assert gate_finished["exit_code"] == 1  # the failure IS recorded
    assert finished == {"type": "run.finished", "status": "passed"}
    assert manifest(bundle)["result"] == {"status": "passed", "failed_gate": None}

    out = capsys.readouterr().out
    assert "✗ format failed" in out
    assert "(optional)" in out


def test_missing_config_is_a_config_error_and_writes_nothing(
    repo, monkeypatch, capsys
):
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_CONFIG

    err = capsys.readouterr().err
    assert ".cox.yaml" in err
    assert "cox init" in err
    assert bundles(repo) == []


def test_unknown_gate_is_a_config_error_and_writes_nothing(
    repo, write_config, monkeypatch, capsys
):
    write_config(repo, THREE_GATES)
    monkeypatch.chdir(repo)

    assert cli.main(["verify", "--gate", "typo"]) == cli.EXIT_CONFIG

    err = capsys.readouterr().err
    assert "no gate 'typo'" in err
    assert "format, lint, test" in err
    assert bundles(repo) == []


def test_gate_flag_selects_a_gate_other_than_the_first(
    repo, write_config, monkeypatch, capsys
):
    write_config(repo, THREE_GATES)
    monkeypatch.chdir(repo)

    assert cli.main(["verify", "--gate", "test"]) == cli.EXIT_OK

    bundle = only_bundle(repo)
    assert events(bundle)[1]["gate_id"] == "test"
    captured = capsys.readouterr()
    assert "✓ test passed" in captured.out
    # an explicit --gate is not a surprise, so no note about the others
    assert captured.err == ""


def test_multiple_gates_run_the_first_and_say_so_on_stderr(
    repo, write_config, monkeypatch, capsys
):
    write_config(repo, THREE_GATES)
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_OK

    assert events(only_bundle(repo))[1]["gate_id"] == "format"
    err = capsys.readouterr().err
    assert "declares 3 gates" in err
    assert "--gate ID" in err


def test_verify_finds_the_repo_root_from_a_subdirectory(
    repo, write_config, monkeypatch, capsys
):
    write_config(repo, ONE_PASSING_GATE)
    nested = repo / "src" / "deep"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert cli.main(["verify"]) == cli.EXIT_OK

    # config read from the root, bundle written at the root
    bundle = only_bundle(repo)
    assert not (nested / ".cox").exists()
    assert f".cox/runs/{bundle.name}/" in capsys.readouterr().out


def test_outside_a_git_repo_the_run_still_works_with_null_git_fields(
    tmp_path, write_config, monkeypatch, capsys
):
    write_config(tmp_path, ONE_PASSING_GATE)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["verify"]) == cli.EXIT_OK

    bundle = only_bundle(tmp_path)
    assert events(bundle)[0]["sha"] is None
    assert manifest(bundle)["repo"] == {
        "root": ".",
        "head_sha": None,
        "branch": None,
        "dirty": False,
    }
    assert "✓ unit passed" in capsys.readouterr().out


def test_each_run_gets_its_own_bundle(repo, write_config, monkeypatch):
    write_config(repo, ONE_PASSING_GATE)
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["verify"]) == cli.EXIT_OK

    assert len(bundles(repo)) == 2


def test_gate_command_runs_in_the_repo_root(repo, write_config, monkeypatch):
    write_config(
        repo,
        """\
version: 1
gates:
  - id: marker
    run: pwd > cwd.txt
""",
    )
    nested = repo / "sub"
    nested.mkdir()
    monkeypatch.chdir(nested)

    assert cli.main(["verify"]) == cli.EXIT_OK

    recorded = (repo / "cwd.txt").read_text(encoding="utf-8").strip()
    assert Path(recorded).resolve() == repo.resolve()
