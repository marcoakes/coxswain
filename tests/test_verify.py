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

MIDDLE_GATE_FAILS = """\
version: 1
gates:
  - id: lint
    run: "true"
  - id: test
    run: "false"
  - id: deploy
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


def bare(event: dict) -> dict:
    """An event without its timestamp, for exact-shape assertions."""
    return {key: value for key, value in event.items() if key != "ts"}


def manifest(bundle: Path) -> dict:
    return json.loads(
        (bundle / evidence.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )


def gate_dirs(bundle: Path) -> list[str]:
    root = bundle / evidence.GATES_DIRNAME
    return sorted(path.name for path in root.iterdir()) if root.is_dir() else []


def result_json(bundle: Path, gate_dir: str) -> dict:
    path = bundle / evidence.GATES_DIRNAME / gate_dir / evidence.RESULT_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


def gate_log(bundle: Path, gate_dir: str, stream: str) -> str:
    path = bundle / evidence.GATES_DIRNAME / gate_dir / f"{stream}.log"
    return path.read_text(encoding="utf-8")


def summary_text(bundle: Path) -> str:
    return (bundle / "summary.md").read_text(encoding="utf-8")


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
    assert bare(gate_started) == {
        "type": "gate.started",
        "gate_id": "unit",
        "command": "true",
    }
    assert gate_finished["gate_id"] == "unit"
    assert gate_finished["exit_code"] == 0
    assert isinstance(gate_finished["duration_ms"], int)
    assert gate_finished["duration_ms"] >= 0
    assert bare(finished) == {"type": "run.finished", "status": "passed"}

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

    assert (bundle / "summary.md").is_file()

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
    assert bare(finished) == {
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
    assert bare(finished) == {"type": "run.finished", "status": "passed"}
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
    # NNN follows the declared order, so a single-gate run's evidence lands
    # where a full run would have put it
    assert gate_dirs(bundle) == ["003_test"]
    captured = capsys.readouterr()
    assert "✓ test passed" in captured.out
    # an explicit --gate is not a surprise, so no note about the others
    assert captured.err == ""


def test_every_declared_gate_runs_in_declared_order(
    repo, write_config, monkeypatch, capsys
):
    write_config(repo, THREE_GATES)
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_OK

    bundle = only_bundle(repo)
    recorded = events(bundle)
    assert [event["type"] for event in recorded] == [
        "run.started",
        "gate.started",
        "gate.finished",
        "gate.started",
        "gate.finished",
        "gate.started",
        "gate.finished",
        "run.finished",
    ]
    assert [e["gate_id"] for e in recorded if e["type"] == "gate.started"] == [
        "format",
        "lint",
        "test",
    ]
    assert gate_dirs(bundle) == ["001_format", "002_lint", "003_test"]
    for name in gate_dirs(bundle):
        contents = sorted(
            p.name for p in (bundle / evidence.GATES_DIRNAME / name).iterdir()
        )
        assert contents == ["result.json", "stderr.log", "stdout.log"]
    # nothing failed, so nothing points at a log
    assert all("log" not in event for event in recorded)

    text = summary_text(bundle)
    for gate_id in ("format", "lint", "test"):
        assert f"| {gate_id} | passed |" in text

    captured = capsys.readouterr()
    assert captured.out.count("✓") == 3
    assert captured.err == ""


def test_a_required_failure_stops_the_run_and_skips_the_rest(
    repo, write_config, monkeypatch, capsys
):
    write_config(repo, MIDDLE_GATE_FAILS)
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_GATE_FAILED

    bundle = only_bundle(repo)
    recorded = events(bundle)
    # 'deploy' never ran: no events, no directory — only the summary knows
    assert [e["gate_id"] for e in recorded if e["type"] == "gate.started"] == [
        "lint",
        "test",
    ]
    assert gate_dirs(bundle) == ["001_lint", "002_test"]

    lint_finished, test_finished = [
        e for e in recorded if e["type"] == "gate.finished"
    ]
    assert "log" not in lint_finished
    assert test_finished["log"] == "gates/002_test/stdout.log"
    assert bare(recorded[-1]) == {
        "type": "run.finished",
        "status": "failed",
        "failed_gate": "test",
    }
    assert manifest(bundle)["result"] == {"status": "failed", "failed_gate": "test"}

    row = result_json(bundle, "002_test")
    duration = row.pop("duration_ms")
    assert isinstance(duration, int) and duration >= 0
    assert row == {
        "gate_id": "test",
        "command": "false",
        "exit_code": 1,
        "timed_out": False,
        "optional": False,
        "status": "failed",
    }

    text = summary_text(bundle)
    assert "| test | failed |" in text
    assert "| deploy | skipped | — | — |" in text

    out = capsys.readouterr().out
    assert "✗ test failed" in out
    assert f"open .cox/runs/{bundle.name}/summary.md" in out
    assert "rerun cox verify --gate test" in out


def test_a_timeout_fails_the_run_and_says_timed_out(
    repo, write_config, monkeypatch, capsys
):
    write_config(
        repo,
        """\
version: 1
gates:
  - id: slow
    run: sleep 30
    timeout: 1
""",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_GATE_FAILED

    bundle = only_bundle(repo)
    row = result_json(bundle, "001_slow")
    assert row["timed_out"] is True
    assert row["status"] == "failed"
    assert row["exit_code"] < 0  # ended by a signal
    assert 1000 <= row["duration_ms"] < 10_000  # the limit, not the command
    assert "| slow | timed out |" in summary_text(bundle)
    assert "✗ slow timed out" in capsys.readouterr().out


def test_an_optional_failure_is_recorded_and_the_run_continues(
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
  - id: test
    run: "true"
""",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_OK

    bundle = only_bundle(repo)
    recorded = events(bundle)
    assert [e["gate_id"] for e in recorded if e["type"] == "gate.started"] == [
        "format",
        "test",
    ]
    format_finished = [e for e in recorded if e["type"] == "gate.finished"][0]
    assert format_finished["exit_code"] == 1
    assert format_finished["log"] == "gates/001_format/stdout.log"
    assert bare(recorded[-1]) == {"type": "run.finished", "status": "passed"}
    assert manifest(bundle)["result"] == {"status": "passed", "failed_gate": None}
    assert result_json(bundle, "001_format")["optional"] is True
    assert "| format | failed (optional) |" in summary_text(bundle)

    out = capsys.readouterr().out
    assert "✗ format failed" in out
    assert "(optional)" in out
    assert "rerun cox verify" not in out


def test_gate_output_is_captured_and_kept_off_the_console(
    repo, write_config, monkeypatch, capfd
):
    write_config(
        repo,
        """\
version: 1
gates:
  - id: chatty
    run: echo captured-stdout; echo captured-stderr >&2
""",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_OK

    bundle = only_bundle(repo)
    assert gate_log(bundle, "001_chatty", "stdout") == "captured-stdout\n"
    assert gate_log(bundle, "001_chatty", "stderr") == "captured-stderr\n"

    captured = capfd.readouterr()
    assert "captured-stdout" not in captured.out
    assert "captured-stderr" not in captured.out + captured.err


def test_a_required_failure_prints_the_tail_of_both_logs(
    repo, write_config, monkeypatch, capfd
):
    write_config(
        repo,
        """\
version: 1
gates:
  - id: noisy
    run: echo boom-stdout; echo boom-stderr >&2; exit 1
""",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_GATE_FAILED

    out = capfd.readouterr().out
    assert "--- gates/001_noisy/stdout.log ---" in out
    assert "boom-stdout" in out
    assert "--- gates/001_noisy/stderr.log ---" in out
    assert "boom-stderr" in out


def test_a_silent_failure_prints_no_log_headers(
    repo, write_config, monkeypatch, capfd
):
    write_config(repo, ONE_FAILING_GATE)  # `false` writes nothing
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_GATE_FAILED

    out = capfd.readouterr().out
    assert "stdout.log ---" not in out
    assert "stderr.log ---" not in out


def test_a_long_log_is_tailed_not_dumped(repo, write_config, monkeypatch, capfd):
    write_config(
        repo,
        """\
version: 1
gates:
  - id: verbose
    run: for i in $(seq 1 50); do echo line-$i; done; exit 1
""",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_GATE_FAILED

    out = capfd.readouterr().out
    assert "(last 20 of 50 lines)" in out
    assert "line-50" in out
    assert "line-31" in out
    assert "line-30" not in out


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
