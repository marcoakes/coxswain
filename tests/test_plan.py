"""`wring plan` — the approved spec becomes work (SPEC_INTENT_V0.md §4).

`wring plan` runs nothing. It reads a file a human approved, writes the task
file, the briefs and the rubric, prints the gate change it would like someone
to make, and stops. Everything here is about what it refuses.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from wringer import cli, config, fleet, rubric, spec

CONFIG = """\
version: 1
gates:
  - id: check
    run: "true"
judge:
  endpoint: http://127.0.0.1:11434/v1/chat/completions
  model: cheap-model
  rubric: wringer.rubric.yaml
"""

SPEC = """\
schema_version: wringer.spec.v1
approved: true
title: Add CSV export to the reports page
intent: |2
  Our reports page needs a CSV export.
open_questions:
  - id: date-format
    question: Which date format should the export use?
    required: true
    answer: ISO-8601.
  - id: row-cap
    question: Is there a maximum row count?
    required: false
    answer: ''
criteria:
  - id: export-button-exists
    title: A CSV export button appears on the reports page
    guidance: A test asserts the button renders.
    required: true
    human: false
  - id: reads-well
    title: The column headings read the way a finance team expects
    required: true
    human: true
gates:
  - id: test
    run: pytest -q
tasks:
  - id: csv-export
    brief: briefs/csv-export.md
    dir: .
    objective: Add the export endpoint and the button that calls it.
"""


def setup_repo(repo: Path, spec_text: str = SPEC, config_text: str = CONFIG) -> None:
    (repo / config.CONFIG_FILENAME).write_text(config_text, encoding="utf-8")
    (repo / spec.SPEC_FILENAME).write_text(spec_text, encoding="utf-8")


def test_an_unapproved_spec_is_refused_and_changes_nothing(
    repo, monkeypatch, capsys
):
    setup_repo(repo, SPEC.replace("approved: true", "approved: false"))
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_GATE_FAILED

    err = capsys.readouterr().err
    assert "approved: false" in err
    assert "no --yes" in err
    # nothing was written, so nothing can be run
    assert not (repo / spec.TASKS_FILENAME).exists()
    assert not (repo / spec.RUBRIC_FILENAME).exists()
    assert not (repo / "briefs").exists()


def test_unanswered_required_questions_are_refused_and_listed(
    repo, monkeypatch, capsys
):
    setup_repo(repo, SPEC.replace("    answer: ISO-8601.\n", "    answer: ''\n"))
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_GATE_FAILED

    err = capsys.readouterr().err
    assert "date-format: Which date format" in err
    # the optional one is not held against the plan
    assert "row-cap" not in err
    assert not (repo / spec.TASKS_FILENAME).exists()


def test_a_deleted_question_counts_as_answered(repo, monkeypatch, capsys):
    trimmed = SPEC.split("open_questions:")[0] + "open_questions: []\n" + (
        "criteria:" + SPEC.split("criteria:", 1)[1]
    )
    setup_repo(repo, trimmed)
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_OK

    assert (repo / spec.TASKS_FILENAME).is_file()


def test_no_spec_file_is_a_config_error(repo, monkeypatch, capsys):
    (repo / config.CONFIG_FILENAME).write_text(CONFIG, encoding="utf-8")
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_CONFIG

    assert "wring spec" in capsys.readouterr().err


# --- what an approved spec produces --------------------------------------


def test_an_approved_spec_produces_tasks_the_fleet_accepts(
    repo, monkeypatch, capsys
):
    setup_repo(repo)
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_OK

    # the fleet's own loader is the contract, so it is what checks the file
    tasks = fleet.load_tasks(repo / spec.TASKS_FILENAME)
    assert [t.id for t in tasks] == ["csv-export"]
    assert tasks[0].brief == "briefs/csv-export.md"
    assert (repo / tasks[0].brief).is_file()


def test_the_criteria_block_is_a_rubric_the_judge_loads_unmodified(
    repo, monkeypatch, capsys
):
    """No translation layer: the judge's own loader reads what plan wrote."""
    setup_repo(repo)
    monkeypatch.chdir(repo)
    assert cli.main(["plan"]) == cli.EXIT_OK
    capsys.readouterr()

    loaded = rubric.load(Path(spec.RUBRIC_FILENAME), repo)
    assert loaded.title == "Add CSV export to the reports page"
    assert [c.id for c in loaded.criteria] == ["export-button-exists", "reads-well"]
    assert [c.human for c in loaded.criteria] == [False, True]


def test_the_brief_carries_the_criteria_and_the_answers(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    assert cli.main(["plan"]) == cli.EXIT_OK
    capsys.readouterr()

    brief = (repo / "briefs" / "csv-export.md").read_text(encoding="utf-8")
    assert spec.BRIEF_MARKER in brief
    assert "Add the export endpoint" in brief
    assert "export-button-exists" in brief
    assert "a human scores this" in brief
    # a decision the PM already made travels with the work
    assert "ISO-8601." in brief
    # the PM's own words go with it, so the worker sees the source
    assert "Our reports page needs a CSV export." in brief


def test_gates_are_proposed_as_a_diff_and_never_installed(
    repo, monkeypatch, capsys
):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    before = (repo / config.CONFIG_FILENAME).read_text(encoding="utf-8")

    assert cli.main(["plan"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "+  - id: test" in out
    assert "+    run: pytest -q" in out
    assert "does not install" in out
    # the config on disk is untouched, byte for byte
    assert (repo / config.CONFIG_FILENAME).read_text(encoding="utf-8") == before


def test_the_proposed_diff_applies_to_the_real_config(repo, monkeypatch, capsys):
    """A diff nobody can apply is a diff that proves nothing."""
    setup_repo(repo)
    monkeypatch.chdir(repo)
    assert cli.main(["plan", "--json"]) == cli.EXIT_OK
    diff = json.loads(capsys.readouterr().out)["gate_diff"]

    patched = repo / "patched"
    patched.mkdir()
    (patched / config.CONFIG_FILENAME).write_text(
        (repo / config.CONFIG_FILENAME).read_text(encoding="utf-8"), encoding="utf-8"
    )
    (repo / "gates.patch").write_text(diff, encoding="utf-8")
    import subprocess

    applied = subprocess.run(
        ["git", "apply", "--unsafe-paths", "--directory", "patched",
         str(repo / "gates.patch")],
        cwd=repo, capture_output=True, text=True,
    )
    assert applied.returncode == 0, applied.stderr

    updated = config.load(patched / config.CONFIG_FILENAME)
    assert [g.id for g in updated.gates] == ["check", "test"]
    assert updated.gates[1].run == "pytest -q"


def test_a_gate_the_config_already_declares_is_not_proposed_twice(
    repo, monkeypatch, capsys
):
    setup_repo(
        repo,
        config_text=CONFIG.replace(
            '  - id: check\n    run: "true"\n',
            '  - id: check\n    run: "true"\n  - id: test\n    run: "pytest"\n',
        ),
    )
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "Already declared" in out
    assert "+  - id: test" not in out


def test_a_spec_with_no_gates_proposes_nothing(repo, monkeypatch, capsys):
    setup_repo(repo, SPEC.replace(
        "gates:\n  - id: test\n    run: pytest -q\n", "gates: []\n"
    ))
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_OK

    assert "is unchanged" in capsys.readouterr().out


def test_json_output_is_one_object(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)

    assert cli.main(["plan", "--json"]) == cli.EXIT_OK

    payload = json.loads(capsys.readouterr().out)
    assert payload["tasks"] == ["csv-export"]
    assert payload["briefs"] == ["briefs/csv-export.md"]
    assert payload["rubric"] == spec.RUBRIC_FILENAME
    assert payload["gates_proposed"] == ["test"]
    assert payload["gates_already_declared"] == []


# --- what it refuses to overwrite ----------------------------------------


def test_a_brief_path_over_a_real_file_is_refused(repo, monkeypatch, capsys):
    setup_repo(repo, SPEC.replace("briefs/csv-export.md", "README.md"))
    (repo / "README.md").write_text("# a real readme\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_CONFIG

    assert "would overwrite README.md" in capsys.readouterr().err
    assert (repo / "README.md").read_text(encoding="utf-8") == "# a real readme\n"
    # nothing else was written either — the checks all run before any write
    assert not (repo / spec.TASKS_FILENAME).exists()


def test_a_tasks_file_that_is_not_a_task_file_is_refused(repo, monkeypatch,
                                                         capsys):
    setup_repo(repo)
    (repo / spec.TASKS_FILENAME).write_text("my notes, actually\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_CONFIG

    assert "refusing to overwrite" in capsys.readouterr().err
    assert (repo / spec.TASKS_FILENAME).read_text("utf-8") == "my notes, actually\n"


def test_rerunning_plan_regenerates_its_own_files(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    assert cli.main(["plan"]) == cli.EXIT_OK
    assert cli.main(["plan"]) == cli.EXIT_OK
    capsys.readouterr()

    assert len(fleet.load_tasks(repo / spec.TASKS_FILENAME)) == 1


def test_a_task_dir_that_does_not_exist_is_refused(repo, monkeypatch, capsys):
    setup_repo(repo, SPEC.replace("    dir: .\n", "    dir: services/api\n"))
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_CONFIG

    err = capsys.readouterr().err
    assert "does not exist" in err
    assert "fleet would park it" in err


def test_a_brief_that_escapes_the_repo_is_refused(repo, monkeypatch, capsys):
    setup_repo(repo, SPEC.replace("briefs/csv-export.md", "../escaped.md"))
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_CONFIG

    assert "escape the repository" in capsys.readouterr().err
    assert not (repo.parent / "escaped.md").exists()


def test_a_brief_reached_through_a_symlink_is_refused(repo, tmp_path_factory,
                                                      monkeypatch, capsys):
    """The string check cannot see a symlink; resolving the path can."""
    outside = tmp_path_factory.mktemp("outside")
    (repo / "briefs").symlink_to(outside, target_is_directory=True)
    setup_repo(repo)
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_CONFIG

    assert "outside the repository" in capsys.readouterr().err
    assert not (outside / "csv-export.md").exists()


# --- the whole PM loop ---------------------------------------------------


def test_the_planned_tasks_actually_run_under_the_fleet(repo, monkeypatch,
                                                        capsys):
    """The end of the loop: what `wring plan` writes, `wring fleet` runs."""
    setup_repo(
        repo,
        config_text="""\
version: 1
gates:
  - id: check
    run: "grep -q DONE work.txt"
run:
  worker: "echo DONE > work.txt"
  max_iterations: 2
fleet:
  deadline: 120
  concurrency: 1
""",
    )
    monkeypatch.chdir(repo)
    assert cli.main(["plan"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["fleet", spec.TASKS_FILENAME]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "1 succeeded, 0 failed, 0 parked" in out
    assert (repo / "work.txt").read_text(encoding="utf-8").strip() == "DONE"


def test_the_rendered_rubric_is_valid_yaml_the_parser_agrees_with(repo):
    loaded = spec.parse(yaml.safe_load(SPEC), spec.SPEC_FILENAME)
    text = spec.render_rubric(loaded)

    spec.validate_rubric_text(text)

    assert yaml.safe_load(text)["schema_version"] == "wringer.rubric.v1"
