"""`wring init` behavior."""

from wringer import cli, config, detect


def test_init_writes_template_that_parses(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == cli.EXIT_OK

    written = tmp_path / config.CONFIG_FILENAME
    assert written.is_file()
    assert "wring verify" in capsys.readouterr().out

    # The template must be loadable by our own strict parser.
    cfg = config.load(written)
    assert [g.id for g in cfg.gates] == [detect.PLACEHOLDER_GATE_ID]
    assert cfg.gates[0].run == detect.PLACEHOLDER_GATE_RUN
    assert cfg.gates[0].optional is False


def test_init_names_the_file_it_found_on_the_terminal(tmp_path, monkeypatch, capsys):
    """R2-07's other half. The rendered `.wringer.yaml` comment is covered in
    tests/test_detect.py, but the defect the field report actually quoted was
    the line `wring init` PRINTS:

        Wrote .wringer.yaml — nothing to detect here, so it is a template.

    said to someone looking at their own pyproject.toml. Without this test
    that exact wording can be restored and the suite stays green.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    assert cli.main(["init"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "found pyproject.toml" in out
    assert "nothing to detect here" not in out


def test_init_says_plainly_when_there_was_nothing_to_read(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)

    assert cli.main(["init"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "nothing here to read commands from" in out
    assert "pyproject.toml" not in out


def test_a_fresh_init_then_verify_exits_zero_and_says_it_proved_nothing(
    repo, monkeypatch, capsys
):
    """The first thing a new user does, end to end.

    Before this, the template's three example gates were all `make` targets,
    so in any repo without a Makefile `wring init && wring verify` went red
    and exited 1 on a perfectly healthy tree (field report 2026-08-05,
    R2-08). "The tool is broken" is the wrong first impression when the true
    one is "you have not configured it yet".

    The green exit is bought with a sentence, not with silence. A gate that
    always passes proves nothing, and a bundle that says `passed` because of
    it is precisely the vacuous evidence this project exists to prevent — so
    the run says so, in the terminal and in the bundle, until the placeholder
    is replaced.
    """
    monkeypatch.chdir(repo)
    assert cli.main(["init"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["verify"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "still a template" in out
    assert "proved nothing" in out
    assert "✗" not in out  # a warning, not a failure

    runs = sorted((repo / ".wringer" / "runs").iterdir())
    assert len(runs) == 1
    written = (runs[0] / "summary.md").read_text(encoding="utf-8")
    assert "still a template" in written
    assert "proved nothing" in written


def test_the_warning_goes_away_once_the_placeholder_is_replaced(
    repo, monkeypatch, capsys, write_config
):
    """The other half of the acceptance test. A repo with real gates must
    not be nagged, or the warning becomes noise and stops being read."""
    write_config(
        repo,
        'version: 1\ngates:\n  - id: check\n'
        '    run: "grep -q version .wringer.yaml"\n',
    )
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "still a template" not in out
    runs = sorted((repo / ".wringer" / "runs").iterdir())
    assert "still a template" not in (runs[0] / "summary.md").read_text(
        encoding="utf-8"
    )


def test_init_writes_detected_gates_when_it_finds_them(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n\n[project.optional-dependencies]\n'
        'dev = ["pytest", "ruff"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert cli.main(["init"]) == cli.EXIT_OK

    cfg = config.load(tmp_path / config.CONFIG_FILENAME)
    assert [gate.id for gate in cfg.gates] == ["lint", "test"]
    out = capsys.readouterr().out
    assert "pyproject.toml" in out
    assert "lint, test" in out


def test_init_keeps_evidence_out_of_git(repo, monkeypatch, capsys):
    """A bundle holds raw gate output; a repo that commits it is one push
    away from publishing whatever a gate printed."""
    monkeypatch.chdir(repo)

    assert cli.main(["init"]) == cli.EXIT_OK

    ignored = (repo / ".gitignore").read_text(encoding="utf-8")
    assert ".wringer/" in ignored
    assert ".gitignore" in capsys.readouterr().out


def test_init_appends_to_an_existing_gitignore(repo, monkeypatch, capsys):
    (repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    assert cli.main(["init"]) == cli.EXIT_OK

    ignored = (repo / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in ignored  # what was there is kept
    assert ".wringer/" in ignored


def test_init_does_not_duplicate_an_existing_ignore_rule(repo, monkeypatch, capsys
):
    (repo / ".gitignore").write_text(".wringer/\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    assert cli.main(["init"]) == cli.EXIT_OK

    assert (repo / ".gitignore").read_text(encoding="utf-8").count(
        ".wringer/"
    ) == 1


def test_init_refuses_to_overwrite(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / config.CONFIG_FILENAME).write_text("version: 1\n", encoding="utf-8")

    assert cli.main(["init"]) == cli.EXIT_CONFIG
    err = capsys.readouterr().err
    assert "refusing to overwrite" in err
    kept = (tmp_path / config.CONFIG_FILENAME).read_text(encoding="utf-8")
    assert kept == "version: 1\n"


def test_init_outside_a_repo_leaves_no_gitignore_and_says_so(
    tmp_path, monkeypatch, capsys
):
    """`.gitignore` in a directory with no git is litter, and it implies a
    repository that is not there. Worse, `init` used to end by recommending
    `wring verify`, which then refused with exit 2 — the runbook dead-ended
    two lines after the command that suggested it."""
    monkeypatch.chdir(tmp_path)

    assert cli.main(["init"]) == cli.EXIT_OK

    assert not (tmp_path / ".gitignore").exists()
    out = capsys.readouterr().out
    assert "not a git repository" in out
    assert "git init" in out


def test_explain_does_not_call_a_template_run_proven(repo, monkeypatch, capsys):
    """`wring explain` is what someone reads after the terminal is gone.

    It printed "Every required gate passed — nothing to diagnose." over a
    bundle whose own summary.md said the run proved nothing — the two
    surfaces disagreeing about the same bundle, with the reassuring one
    winning by being the one a human runs later.
    """
    monkeypatch.chdir(repo)
    assert cli.main(["init"]) == cli.EXIT_OK
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["explain"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "still a template" in out
    assert "proved nothing" in out
    assert "nothing to diagnose" not in out


def test_explain_stays_quiet_for_a_repo_with_real_gates(
    repo, monkeypatch, capsys, write_config
):
    write_config(
        repo,
        'version: 1\ngates:\n  - id: check\n'
        '    run: "grep -q version .wringer.yaml"\n',
    )
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["explain"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "still a template" not in out
    assert "nothing to diagnose" in out


def test_verify_json_tells_an_agent_the_run_proved_nothing(
    repo, monkeypatch, capsys
):
    """The reader most likely to over-read `"status": "passed"` is the one
    the terminal warning cannot reach."""
    import json as _json

    monkeypatch.chdir(repo)
    assert cli.main(["init"]) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main(["verify", "--json"]) == cli.EXIT_OK

    reported = _json.loads(capsys.readouterr().out)
    assert reported["status"] == "passed"
    assert reported["template_only"] is True


def test_verify_json_says_false_when_the_repo_is_configured(
    repo, monkeypatch, capsys, write_config
):
    """Present even when false: a consumer must never have to distinguish
    "not a template" from "the tool forgot to tell me"."""
    import json as _json

    write_config(
        repo,
        'version: 1\ngates:\n  - id: check\n'
        '    run: "grep -q version .wringer.yaml"\n',
    )
    monkeypatch.chdir(repo)
    assert cli.main(["verify", "--json"]) == cli.EXIT_OK

    reported = _json.loads(capsys.readouterr().out)
    assert reported["template_only"] is False
