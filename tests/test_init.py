"""`wring init` behavior."""

from wringer import cli, config


def test_init_writes_template_that_parses(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == cli.EXIT_OK

    written = tmp_path / config.CONFIG_FILENAME
    assert written.is_file()
    assert "wring verify" in capsys.readouterr().out

    # The template must be loadable by our own strict parser.
    cfg = config.load(written)
    assert [g.id for g in cfg.gates] == ["format", "lint", "test"]
    assert cfg.gates[0].optional is True
    assert cfg.gates[1].optional is False


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


def test_init_keeps_evidence_out_of_git(tmp_path, monkeypatch, capsys):
    """A bundle holds raw gate output; a repo that commits it is one push
    away from publishing whatever a gate printed."""
    monkeypatch.chdir(tmp_path)

    assert cli.main(["init"]) == cli.EXIT_OK

    ignored = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".wringer/" in ignored
    assert ".gitignore" in capsys.readouterr().out


def test_init_appends_to_an_existing_gitignore(tmp_path, monkeypatch, capsys):
    (tmp_path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert cli.main(["init"]) == cli.EXIT_OK

    ignored = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in ignored  # what was there is kept
    assert ".wringer/" in ignored


def test_init_does_not_duplicate_an_existing_ignore_rule(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / ".gitignore").write_text(".wringer/\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert cli.main(["init"]) == cli.EXIT_OK

    assert (tmp_path / ".gitignore").read_text(encoding="utf-8").count(
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
