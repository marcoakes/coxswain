"""`wring verify` — one gate, an evidence bundle, contract exit codes."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from wringer import cli, evidence, gates

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


def of_type(recorded: list[dict], event_type: str) -> list[dict]:
    return [event for event in recorded if event["type"] == event_type]


def bare(event: dict) -> dict:
    """Drop the fields that differ every run — the timestamp and the hash
    chain link — so a test can assert the shape that carries meaning."""
    return {
        key: value
        for key, value in event.items()
        if key not in ("ts", "prev_hash")
    }


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
        "git.status",
        "gate.started",
        "gate.finished",
        "run.finished",
    ]

    started, git_status, gate_started, gate_finished, finished = recorded
    assert git_status["dirty"] is True
    assert ".wringer.yaml" in git_status["changed_files"] + git_status.get(
        "untracked", []
    )
    assert started["run_id"] == bundle.name
    assert started["wringer_version"] == cli.__version__
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
    assert recorded_manifest["schema_version"] == "wringer.evidence.v1"
    assert recorded_manifest["run_id"] == bundle.name
    # local ISO-8601 with a UTC offset
    assert datetime.fromisoformat(recorded_manifest["started_at"]).tzinfo is not None
    assert recorded_manifest["repo"] == {
        "root": ".",
        "head_sha": started["sha"],
        "branch": "main",
        # the untracked .wringer.yaml we just wrote
        "dirty": True,
    }
    assert recorded_manifest["result"] == {"status": "passed", "failed_gate": None}

    assert (bundle / "summary.md").is_file()

    out = capsys.readouterr().out
    assert "✓ unit passed" in out
    assert "Evidence written to:" in out
    assert f".wringer/runs/{bundle.name}/" in out
    assert "rerun" not in out


def test_failing_required_gate_exits_one_and_names_the_gate(
    repo, write_config, monkeypatch, capsys
):
    write_config(repo, ONE_FAILING_GATE)
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_GATE_FAILED

    bundle = only_bundle(repo)
    recorded = events(bundle)
    gate_finished = of_type(recorded, "gate.finished")[0]
    assert gate_finished["exit_code"] == 1
    assert bare(recorded[-1]) == {
        "type": "run.finished",
        "status": "failed",
        "failed_gate": "unit",
    }
    assert manifest(bundle)["result"] == {"status": "failed", "failed_gate": "unit"}

    out = capsys.readouterr().out
    assert "✗ unit failed" in out
    assert "rerun wring verify --gate unit" in out


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
    recorded = events(bundle)
    gate_finished = of_type(recorded, "gate.finished")[0]
    assert gate_finished["exit_code"] == 1  # the failure IS recorded
    assert bare(recorded[-1]) == {"type": "run.finished", "status": "passed"}
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
    assert ".wringer.yaml" in err
    assert "wring init" in err
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
    assert of_type(events(bundle), "gate.started")[0]["gate_id"] == "test"
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
        "git.status",
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
        "stdout_truncated": False,
        "stderr_truncated": False,
        "optional": False,
        "status": "failed",
    }

    text = summary_text(bundle)
    assert "| test | failed |" in text
    assert "| deploy | skipped | — | — |" in text

    out = capsys.readouterr().out
    assert "✗ test failed" in out
    assert f"open .wringer/runs/{bundle.name}/summary.md" in out
    assert "rerun wring verify --gate test" in out


def test_the_bundle_captures_the_working_tree(
    repo, write_config, git_run, monkeypatch
):
    write_config(repo, ONE_PASSING_GATE)
    (repo / "tracked.py").write_text("before\n", encoding="utf-8")
    git_run(repo, "add", "tracked.py")
    git_run(repo, "commit", "-q", "-m", "add tracked")
    (repo / "tracked.py").write_text("after\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_OK

    bundle = only_bundle(repo)
    patch = (bundle / evidence.DIFF_FILENAME).read_text(encoding="utf-8")
    status = (bundle / evidence.STATUS_FILENAME).read_text(encoding="utf-8")

    assert "-before" in patch
    assert "+after" in patch
    assert "tracked.py" in status
    assert ".wringer.yaml" in status
    # Wringer's own run directory must not appear in its own evidence: the
    # capture is taken before the bundle exists.
    assert ".wringer/" not in status
    assert ".wringer/" not in patch

    git_status = of_type(events(bundle), "git.status")[0]
    assert git_status["dirty"] is True
    assert "tracked.py" in git_status["changed_files"]
    assert git_status["untracked"] == [".wringer.yaml"]


def test_a_clean_repo_captures_an_empty_diff(
    repo, write_config, git_run, monkeypatch
):
    write_config(repo, ONE_PASSING_GATE)
    git_run(repo, "add", ".wringer.yaml")
    git_run(repo, "commit", "-q", "-m", "add config")
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_OK

    bundle = only_bundle(repo)
    assert (bundle / evidence.DIFF_FILENAME).read_text(encoding="utf-8") == ""
    assert (bundle / evidence.STATUS_FILENAME).read_text(encoding="utf-8") == ""
    git_status = of_type(events(bundle), "git.status")[0]
    # no `untracked` key at all when there is nothing untracked
    assert bare(git_status) == {
        "type": "git.status",
        "dirty": False,
        "changed_files": [],
    }


def test_a_truncated_log_is_declared_in_the_evidence(
    repo, write_config, monkeypatch, capfd
):
    monkeypatch.setattr(gates, "MAX_LOG_BYTES", 64)
    write_config(
        repo,
        """\
version: 1
gates:
  - id: noisy
    run: for i in $(seq 1 200); do echo line-$i; done
""",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_OK
    capfd.readouterr()

    bundle = only_bundle(repo)
    row = result_json(bundle, "001_noisy")
    assert row["stdout_truncated"] is True
    assert row["stderr_truncated"] is False
    # the event says so too, so a machine reading only evidence.jsonl knows
    assert of_type(events(bundle), "gate.finished")[0]["truncated"] is True


def test_a_whole_log_carries_no_truncation_key(
    repo, write_config, monkeypatch, capfd
):
    write_config(repo, ONE_PASSING_GATE)
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_OK
    capfd.readouterr()

    bundle = only_bundle(repo)
    assert "truncated" not in of_type(events(bundle), "gate.finished")[0]


def test_output_writes_the_bundle_where_you_say(
    repo, write_config, monkeypatch, capsys
):
    write_config(repo, ONE_PASSING_GATE)
    monkeypatch.chdir(repo)
    target = repo / "somewhere" / "manual-001"

    assert cli.main(["verify", "--output", str(target)]) == cli.EXIT_OK

    assert (target / evidence.MANIFEST_FILENAME).is_file()
    assert (target / "summary.md").is_file()
    assert (target / evidence.GATES_DIRNAME / "001_unit").is_dir()
    # nothing was written to the default location
    assert bundles(repo) == []
    # the bundle still identifies itself, by the name it was given
    assert manifest(target)["run_id"] == "manual-001"
    assert "somewhere/manual-001/" in capsys.readouterr().out


def test_output_reuses_a_directory_because_naming_one_is_an_instruction(
    repo, write_config, monkeypatch, capsys
):
    write_config(repo, ONE_PASSING_GATE)
    monkeypatch.chdir(repo)
    target = repo / "fixed"

    assert cli.main(["verify", "--output", str(target)]) == cli.EXIT_OK
    assert cli.main(["verify", "--output", str(target)]) == cli.EXIT_OK
    capsys.readouterr()

    # a caller who names the same path twice means it
    assert manifest(target)["result"]["status"] == "passed"
    # ...and the log describes THAT run, not both of them stacked up
    recorded = events(target)
    assert [event["type"] for event in recorded].count("run.started") == 1
    assert recorded[0]["run_id"] == manifest(target)["run_id"]


def test_a_reused_output_directory_holds_no_evidence_from_the_run_before(
    repo, write_config, monkeypatch, capsys
):
    """A gate that did not run this time must leave nothing behind, or the
    bundle contradicts itself: summary.md calls the gate skipped while
    `wring explain` reads last run's result.json and calls it passed."""
    monkeypatch.chdir(repo)
    target = repo / "fixed"

    write_config(
        repo,
        """\
version: 1
gates:
  - id: lint
    run: "true"
  - id: test
    run: "true"
""",
    )
    assert cli.main(["verify", "--output", str(target)]) == cli.EXIT_OK
    assert (target / evidence.GATES_DIRNAME / "002_test").is_dir()

    # now lint fails, so test never gets a turn
    write_config(
        repo,
        """\
version: 1
gates:
  - id: lint
    run: "false"
  - id: test
    run: "true"
""",
    )
    assert cli.main(["verify", "--output", str(target)]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    assert not (target / evidence.GATES_DIRNAME / "002_test").exists()
    summary = (target / "summary.md").read_text(encoding="utf-8")
    assert "| test | skipped |" in summary

    assert cli.main(["explain", str(target)]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "✗ lint failed" in out
    assert "test passed" not in out  # the stale verdict is gone


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
    assert "rerun wring verify" not in out


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
    assert not (nested / ".wringer").exists()
    assert f".wringer/runs/{bundle.name}/" in capsys.readouterr().out


def test_outside_a_git_repo_verify_refuses(tmp_path, write_config, monkeypatch, capsys):
    """Verification is a claim about a commit. Without git there is no commit
    to make the claim about, so refuse rather than write a bundle whose
    provenance fields are all null."""
    write_config(tmp_path, ONE_PASSING_GATE)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["verify"]) == cli.EXIT_CONFIG

    err = capsys.readouterr().err
    assert "not a git repository" in err
    assert bundles(tmp_path) == []


def test_a_conflicted_merge_is_refused_with_exit_three(
    repo, write_config, git_run, monkeypatch, capsys
):
    (repo / "shared.txt").write_text("base\n", encoding="utf-8")
    git_run(repo, "add", "shared.txt")
    git_run(repo, "commit", "-q", "-m", "base")

    git_run(repo, "checkout", "-q", "-b", "other")
    (repo / "shared.txt").write_text("theirs\n", encoding="utf-8")
    git_run(repo, "commit", "-q", "-am", "theirs")

    git_run(repo, "checkout", "-q", "main")
    (repo / "shared.txt").write_text("ours\n", encoding="utf-8")
    git_run(repo, "commit", "-q", "-am", "ours")
    git_run(repo, "merge", "other", check=False)  # conflicts, on purpose

    write_config(repo, ONE_PASSING_GATE)
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_REFUSED

    err = capsys.readouterr().err
    assert "in the middle of a merge" in err
    assert bundles(repo) == []


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
