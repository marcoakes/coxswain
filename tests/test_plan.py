"""`wring plan` — the approved spec becomes work (SPEC_INTENT_V0.md §4).

`wring plan` runs nothing. It reads a file a human approved, writes the task
file, the briefs and the rubric, prints the gate change it would like someone
to make, and stops. Everything here is about what it refuses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from conftest import flat

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

    assert "outside the repository" in flat(capsys.readouterr().err)
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


def test_the_proposed_gates_land_inside_the_gate_list(repo, monkeypatch, capsys):
    """A config with a blank line between sections still reads as one after
    the diff is applied — the addition goes in the list, not on top of the
    next key."""
    setup_repo(
        repo,
        config_text='version: 1\ngates:\n  - id: check\n    run: "true"\n\n'
        "judge:\n  endpoint: http://127.0.0.1:11434/v1/chat/completions\n"
        "  model: cheap-model\n  rubric: wringer.rubric.yaml\n",
    )
    monkeypatch.chdir(repo)
    assert cli.main(["plan", "--json"]) == cli.EXIT_OK
    diff = json.loads(capsys.readouterr().out)["gate_diff"]

    # the separator survives: the line after the addition is still blank
    lines = diff.splitlines()
    added = max(i for i, line in enumerate(lines) if line.startswith("+"))
    assert not lines[added + 1].strip()

    import subprocess

    (repo / "gates.patch").write_text(diff, encoding="utf-8")
    applied = subprocess.run(
        ["git", "apply", str(repo / "gates.patch")],
        cwd=repo, capture_output=True, text=True,
    )
    assert applied.returncode == 0, applied.stderr
    parsed = config.load(repo / config.CONFIG_FILENAME)
    assert [g.id for g in parsed.gates] == ["check", "test"]
    # and the judge section it was written above is still readable
    assert parsed.judge is not None and parsed.judge.model == "cheap-model"


def test_a_flow_style_config_is_still_read_correctly(repo, monkeypatch, capsys):
    """A gate id the line scan would miss must not be proposed again — the
    human applying that diff would get a config their own loader rejects."""
    setup_repo(
        repo,
        config_text="version: 1\n"
        'gates: [{id: check, run: "true"}, {id: test, run: "pytest"}]\n'
        "judge:\n  endpoint: http://127.0.0.1:11434/v1/chat/completions\n"
        "  model: cheap-model\n  rubric: wringer.rubric.yaml\n",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["plan", "--json"]) == cli.EXIT_OK

    payload = json.loads(capsys.readouterr().out)
    assert payload["gates_proposed"] == []
    assert payload["gates_already_declared"] == ["test"]


def test_an_unparseable_config_still_gets_a_diff(repo, monkeypatch, capsys):
    """A broken .wringer.yaml is a reason to show the change, not to hide it."""
    setup_repo(repo)
    (repo / config.CONFIG_FILENAME).write_text(
        "version: 1\ngates:\n  - id: check\n    run: true\n  oops: [\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["plan", "--json"]) == cli.EXIT_OK

    payload = json.loads(capsys.readouterr().out)
    assert payload["gates_proposed"] == ["test"]
    assert "+  - id: test" in payload["gate_diff"]


# --- what an adversarial review found (2026-08-01) -----------------------


def test_a_flow_style_config_gets_words_not_a_destructive_diff(
    repo, monkeypatch, capsys
):
    """THE one that would have cost someone their gates. The old code, unable
    to find a block-style `gates:` line, appended a SECOND `gates:` key — and
    YAML keeps the last, so the 'purely additive' diff deleted every gate the
    repo already declared, after a human read it and approved it."""
    setup_repo(
        repo,
        config_text="version: 1\n"
        'gates: [{id: check, run: "true"}]\n'
        "judge:\n  endpoint: http://127.0.0.1:11434/v1/chat/completions\n"
        "  model: cheap-model\n  rubric: wringer.rubric.yaml\n",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["plan", "--json"]) == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)

    assert payload["gates_proposed"] == ["test"]
    # no diff at all, rather than one that lies about being additive
    assert payload["gate_diff"] == ""

    assert cli.main(["plan"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "as text rather than a diff" in out
    assert "delete the gates you already have" in out
    assert "- id: test" in out
    # and whatever happens, the config is untouched
    assert config.load(repo / config.CONFIG_FILENAME).gates[0].id == "check"


def test_two_tasks_may_not_share_a_brief(repo, monkeypatch, capsys):
    """One file, two tasks: the second write wins, the fleet dispatches both
    tasks against it, and one objective is simply gone."""
    setup_repo(
        repo,
        SPEC.rstrip()
        + "\n  - id: csv-export-ui\n    brief: briefs/csv-export.md\n"
        "    dir: .\n    objective: Add the button.\n",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_CONFIG

    err = capsys.readouterr().err
    assert "names the same brief" in err
    assert not (repo / spec.TASKS_FILENAME).exists()


def test_a_hand_written_rubric_is_never_overwritten(repo, monkeypatch, capsys):
    """`judge.rubric:` has pointed at a file since v0.2, so a repo adopting
    `wring spec` may already have one — and it is the document that decides
    whether the work is accepted."""
    setup_repo(repo)
    theirs = (
        "schema_version: wringer.rubric.v1\ntitle: Ours, written by hand\n"
        "criteria:\n  - id: careful\n    title: We wrote this\n    required: true\n"
    )
    (repo / spec.RUBRIC_FILENAME).write_text(theirs, encoding="utf-8")
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_CONFIG

    assert "did not write it" in capsys.readouterr().err
    assert (repo / spec.RUBRIC_FILENAME).read_text(encoding="utf-8") == theirs
    assert not (repo / spec.TASKS_FILENAME).exists()


def test_a_rubric_plan_wrote_is_regenerated(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    assert cli.main(["plan"]) == cli.EXIT_OK
    assert cli.main(["plan"]) == cli.EXIT_OK
    capsys.readouterr()

    text = (repo / spec.RUBRIC_FILENAME).read_text(encoding="utf-8")
    assert spec.RUBRIC_MARKER in text
    # the marker is a YAML comment, so the judge's loader is unmoved by it
    assert rubric.load(Path(spec.RUBRIC_FILENAME), repo).title == (
        "Add CSV export to the reports page"
    )


def test_a_symlinked_rubric_cannot_reach_outside_the_repo(
    repo, tmp_path_factory, monkeypatch, capsys
):
    outside = tmp_path_factory.mktemp("outside") / "theirs.yaml"
    outside.write_text("not ours\n", encoding="utf-8")
    setup_repo(repo)
    (repo / spec.RUBRIC_FILENAME).symlink_to(outside)
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_CONFIG

    assert "outside the repository" in flat(capsys.readouterr().err)
    assert outside.read_text(encoding="utf-8") == "not ours\n"


def test_a_brief_under_a_file_shaped_parent_is_refused_before_any_write(
    repo, monkeypatch, capsys
):
    """mkdir would raise here — after tasks.jsonl and the rubric are already
    on disk. That is the half-ran state _plan_writes promises is impossible."""
    setup_repo(repo, SPEC.replace("briefs/csv-export.md", "notes/x.md"))
    (repo / "notes").write_text("I am a file, not a directory\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_CONFIG

    assert "is not a directory" in capsys.readouterr().err
    assert not (repo / spec.TASKS_FILENAME).exists()
    assert not (repo / spec.RUBRIC_FILENAME).exists()


def test_a_brief_inside_dot_git_is_refused(repo, monkeypatch, capsys):
    """Law 6, in its most literal form: Wringer never writes git state."""
    setup_repo(repo, SPEC.replace("briefs/csv-export.md", ".git/refs/heads/main"))
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_CONFIG

    assert ".git/" in capsys.readouterr().err
    assert (repo / ".git" / "refs" / "heads" / "main").read_text().strip()


@pytest.mark.parametrize(
    "collides", ["tasks.jsonl", "wringer.rubric.yaml", "wringer.spec.yaml",
                 ".wringer.yaml"]
)
def test_a_brief_over_a_file_plan_owns_is_refused(
    repo, monkeypatch, capsys, collides
):
    setup_repo(repo, SPEC.replace("briefs/csv-export.md", collides))
    monkeypatch.chdir(repo)

    assert cli.main(["plan"]) == cli.EXIT_CONFIG

    assert "writes or reads itself" in capsys.readouterr().err
