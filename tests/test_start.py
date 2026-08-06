"""`wring start` — the guided launch (SPEC_START_V0.md).

Every test here runs the real command against a real scratch repository. The
wizard's whole safety argument is about what it writes and what it refuses to
write, so nothing about the config emitter is mocked: the assertions read the
bytes that landed on disk and push them back through `config.parse`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from wringer import cli, config, start

# A config a human plainly wrote: their own gates, their own workspace.
HAND_WRITTEN = """\
# my own file, with my own comments
version: 1
gates:
  - id: mine
    run: "true"

workspace: ../mine
"""

MINIMAL = """\
version: 1
gates:
  - id: mine
    run: "true"
"""


def read_config(repo: Path) -> config.Config:
    return config.load(repo / config.CONFIG_FILENAME)


def raw_config(repo: Path) -> dict:
    return yaml.safe_load(
        (repo / config.CONFIG_FILENAME).read_text(encoding="utf-8")
    )


# --- the command exists, with the flags every answer needs -----------------


def test_start_is_a_registered_command():
    parser = cli.build_parser()
    args = parser.parse_args(["start", "--accept-gates"])
    assert args.func is cli.cmd_start


def test_every_answer_except_the_key_has_a_flag():
    """§3b — every answer has a non-interactive form. The key deliberately
    has none: `--key <value>` is a process listing (§3a)."""
    parser = cli.build_parser()
    args = parser.parse_args(
        ["start", "--workspace", "../work", "--repo", ".", "--accept-gates"]
    )
    assert args.workspace == "../work"
    assert args.repo == "."
    assert args.accept_gates is True

    with pytest.raises(SystemExit):
        parser.parse_args(["start", "--key", "sk-ant-notarealkey"])


# --- the config emitter ----------------------------------------------------


def test_start_writes_a_config_where_there_was_none(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)

    assert cli.main(["start", "--accept-gates"]) == cli.EXIT_OK
    capsys.readouterr()

    cfg = read_config(repo)
    assert cfg.version == 1
    assert cfg.gates


def test_the_emitted_config_round_trips_through_the_parser(repo):
    """§3d — a wizard that writes a config the parser rejects is a wizard that
    bricks a repo. The emitter proves it before the bytes reach the disk."""
    (repo / config.CONFIG_FILENAME).write_text(MINIMAL, encoding="utf-8")

    emission = start.emit(
        repo,
        workspace="../work",
        worker=config.AcpWorker(
            command="agent", args=("--acp",), env_passthrough=("SOME_KEY",)
        ),
    )

    parsed = config.parse(yaml.safe_load(emission.text))
    assert parsed.workspace == "../work"
    assert isinstance(parsed.run.worker, config.AcpWorker)
    assert parsed.run.worker.command == "agent"
    assert parsed.run.worker.env_passthrough == ("SOME_KEY",)


def test_an_existing_config_is_added_to_never_replaced(repo, monkeypatch, capsys):
    """§3d — read, never replaced. The user's bytes, comments and all, are
    still there afterwards, and the additions come after them."""
    (repo / config.CONFIG_FILENAME).write_text(MINIMAL, encoding="utf-8")
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--workspace", "../work", "--accept-gates"])
    assert code == cli.EXIT_OK
    capsys.readouterr()

    after = (repo / config.CONFIG_FILENAME).read_text(encoding="utf-8")
    assert after.startswith(MINIMAL), (
        "the wizard rewrote a file it was supposed to add to"
    )
    assert read_config(repo).workspace == "../work"
    # The user's own gate survived; nothing was re-detected over it.
    assert [gate.id for gate in read_config(repo).gates] == ["mine"]


def test_a_section_the_user_wrote_is_refused_rather_than_rewritten(
    repo, monkeypatch, capsys
):
    """§3d — exit 3 rather than replacing a section the user wrote."""
    (repo / config.CONFIG_FILENAME).write_text(HAND_WRITTEN, encoding="utf-8")
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--workspace", "../somewhere-else", "--accept-gates"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_REFUSED
    assert "workspace" in captured.err
    assert (repo / config.CONFIG_FILENAME).read_text(encoding="utf-8") == HAND_WRITTEN


def test_declaring_the_same_workspace_twice_changes_nothing(
    repo, monkeypatch, capsys
):
    """§1 — each step is idempotent. Re-running the launch with the answer the
    config already carries is not a clash, and must not read as one."""
    (repo / config.CONFIG_FILENAME).write_text(HAND_WRITTEN, encoding="utf-8")
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--workspace", "../mine", "--accept-gates"])
    capsys.readouterr()

    assert code == cli.EXIT_OK
    assert (repo / config.CONFIG_FILENAME).read_text(encoding="utf-8") == HAND_WRITTEN


def test_no_start_section_is_ever_written(repo, monkeypatch, capsys):
    """§3d — the wizard keeps no state of its own in `.wringer.yaml`. Unknown
    top-level keys are hard errors, so a `start:` section would brick the repo
    it was written into."""
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--workspace", "../work", "--accept-gates"])
    assert code == cli.EXIT_OK
    capsys.readouterr()

    assert "start" not in raw_config(repo)


def test_nothing_is_written_when_the_emitter_refuses(repo):
    (repo / config.CONFIG_FILENAME).write_text(HAND_WRITTEN, encoding="utf-8")

    with pytest.raises(start.Refused):
        start.emit(repo, workspace="../elsewhere")

    assert (repo / config.CONFIG_FILENAME).read_text(encoding="utf-8") == HAND_WRITTEN


# --- the non-interactive contract ------------------------------------------


def test_a_missing_answer_exits_2_and_names_the_flag(repo, monkeypatch, capsys):
    """§3b — no TTY and a missing answer is exit 2, never a guess and never a
    hang. The message has to name the answer, or it is not actionable."""
    monkeypatch.chdir(repo)

    code = cli.main(["start"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_CONFIG
    assert "--accept-gates" in captured.err


def test_start_outside_a_git_repository_exits_2(tmp_path, monkeypatch, capsys):
    """The launch ends on a receipt, and a receipt needs a run, and a run needs
    a repository. Said before anything is written rather than after."""
    monkeypatch.chdir(tmp_path)

    code = cli.main(["start", "--accept-gates"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_CONFIG
    assert "git init" in captured.err
    assert not (tmp_path / config.CONFIG_FILENAME).exists()


def test_a_repo_that_is_not_there_exits_2(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--repo", "nowhere", "--accept-gates"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_CONFIG
    assert "nowhere" in captured.err
