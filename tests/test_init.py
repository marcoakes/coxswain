"""`cox init` behavior."""

from cox import cli, config


def test_init_writes_template_that_parses(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == cli.EXIT_OK

    written = tmp_path / config.CONFIG_FILENAME
    assert written.is_file()
    assert "cox verify" in capsys.readouterr().out

    # The template must be loadable by our own strict parser.
    cfg = config.load(written)
    assert [g.id for g in cfg.gates] == ["format", "lint", "test"]
    assert cfg.gates[0].optional is True
    assert cfg.gates[1].optional is False


def test_init_refuses_to_overwrite(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / config.CONFIG_FILENAME).write_text("version: 1\n", encoding="utf-8")

    assert cli.main(["init"]) == cli.EXIT_CONFIG
    err = capsys.readouterr().err
    assert "refusing to overwrite" in err
    assert (tmp_path / config.CONFIG_FILENAME).read_text(encoding="utf-8") == "version: 1\n"
