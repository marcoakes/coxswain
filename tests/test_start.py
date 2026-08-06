"""`wring start` — the guided launch (SPEC_START_V0.md).

Every test here runs the real command against a real scratch repository. The
wizard's whole safety argument is about what it writes and what it refuses to
write, so nothing about the config emitter is mocked: the assertions read the
bytes that landed on disk and push them back through `config.parse`.
"""

from __future__ import annotations

import os
import pty
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from wringer import agents, cli, config, start


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


# Obviously fake, and deliberately so: a fixture credential that could be
# mistaken for a real one is a hazard in a repo whose product is evidence.
FAKE_KEY = "sk-ant-notarealkey-3c81f0a6d2e94b57"


@pytest.fixture
def fake_agent(tmp_path_factory, monkeypatch):
    """Put a stand-in for an agent binary on PATH.

    Detection is `shutil.which` and nothing cleverer (§3c), so an executable
    with the right name is all it takes — and a stub is the only device that
    tests the offered path without installing a vendor binary into CI.

    Deliberately NOT under the repo fixture's directory: that tree is a git
    repo whose cleanliness later slices verify, and a stray `bin/` in it would
    show up as an untracked file in a real bundle.
    """
    bindir = tmp_path_factory.mktemp("agent-bin")
    agent = agents.AGENTS[0]
    binary = bindir / agent.command
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    # The launch has a key step, and its non-interactive form is the named
    # variable already being set (§3b, row 5). Set here so every test that
    # merely needs a working agent gets past it; the tests that are ABOUT the
    # key remove it again.
    monkeypatch.setenv(agent.key_env, FAKE_KEY)
    return agent


@pytest.fixture
def bare_path(tmp_path_factory):
    """A PATH with git on it and no agent anywhere.

    Not an empty PATH: `wring start`'s preflight is `wring doctor`'s checks,
    and a machine with no git FAILS one of them — so an empty PATH would test
    the preflight refusing rather than the agent step naming what to install.
    Not the real PATH either: a developer who happens to have an agent
    installed would silently stop exercising the absent branch.
    """
    bindir = tmp_path_factory.mktemp("bare-bin")
    git = shutil.which("git")
    assert git is not None, "the test suite needs git"
    (bindir / "git").symlink_to(git)
    return bindir

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


def real_gates(repo: Path) -> None:
    """Give a scratch repo a gate that is not the placeholder.

    A launch in a repo with nothing to detect ends on the template
    refusal (§4), which is correct and is its own test. Every test that
    is about something else needs to get past it.
    """
    (repo / config.CONFIG_FILENAME).write_text(MINIMAL, encoding="utf-8")


def read_config(repo: Path) -> config.Config:
    return config.load(repo / config.CONFIG_FILENAME)


def raw_config(repo: Path) -> dict:
    return yaml.safe_load(
        (repo / config.CONFIG_FILENAME).read_text(encoding="utf-8")
    )


# --- the command exists, with the flags every answer needs -----------------


def test_start_is_a_registered_command():
    parser = cli.build_parser()
    args = parser.parse_args(["start", "--accept-gates", "--no-agent"])
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

    # Exit 3, not 0: a repo with nothing to detect gets the placeholder
    # gate, and a launch does not call that a pass — see
    # test_a_template_only_launch_says_so_and_attempts_no_receipt. What
    # this test is about is the file that appeared.
    assert cli.main(["start", "--accept-gates", "--no-agent"]) == cli.EXIT_REFUSED
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

    code = cli.main(
        ["start", "--workspace", "../work", "--accept-gates", "--no-agent"]
    )
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

    code = cli.main(
        ["start", "--workspace", "../somewhere-else", "--accept-gates", "--no-agent"]
    )
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

    code = cli.main(
        ["start", "--workspace", "../mine", "--accept-gates", "--no-agent"]
    )
    capsys.readouterr()

    assert code == cli.EXIT_OK
    assert (repo / config.CONFIG_FILENAME).read_text(encoding="utf-8") == HAND_WRITTEN


def test_no_start_section_is_ever_written(repo, monkeypatch, capsys):
    """§3d — the wizard keeps no state of its own in `.wringer.yaml`. Unknown
    top-level keys are hard errors, so a `start:` section would brick the repo
    it was written into."""
    monkeypatch.chdir(repo)

    code = cli.main(
        ["start", "--workspace", "../work", "--accept-gates", "--no-agent"]
    )
    assert code == cli.EXIT_REFUSED  # the placeholder gate, as above
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

    code = cli.main(["start", "--accept-gates", "--no-agent"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_CONFIG
    assert "git init" in captured.err
    assert not (tmp_path / config.CONFIG_FILENAME).exists()


def test_a_repo_that_is_not_there_exits_2(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--repo", "nowhere", "--accept-gates", "--no-agent"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_CONFIG
    assert "nowhere" in captured.err


# --- the agent seam: detected, proposed, never installed --------------------


def test_the_agent_table_is_the_only_place_a_coding_agent_is_named():
    """§3c and AGENTS.md rule 5 — one module maps agent id → binary, args, the
    variable name it expects, its install command. `forge.py`'s precedent: the
    CLI says "the agent", never a product name, as it says "the forge" and
    never "GitHub"."""
    names = {
        token
        for agent in agents.AGENTS
        for token in (agent.id, agent.command, agent.package)
        if token
    }
    offenders: dict[str, list[str]] = {}
    for path in sorted((repo_root() / "src" / "wringer").glob("*.py")):
        if path.name == "agents.py":
            continue
        text = path.read_text(encoding="utf-8")
        found = sorted(name for name in names if name in text)
        if found:
            offenders[path.name] = found
    assert not offenders, (
        f"a coding-agent vendor string escaped the table: {offenders}. Every "
        "one of them belongs in agents.py, so swapping which agent Wringer "
        "offers stays a table edit rather than a grep"
    )


def test_the_agent_table_cannot_run_anything():
    """§3c-i — Wringer does not install an agent. The install command is data
    the human is shown; the module holding it has no way to execute it, which
    is a stronger guarantee than a promise not to."""
    source = (repo_root() / "src" / "wringer" / "agents.py").read_text("utf-8")
    for forbidden in ("subprocess", "os.system", "os.exec", "popen"):
        assert forbidden not in source, (
            f"agents.py references {forbidden!r} — the module that holds "
            "install commands must not be able to run one"
        )


# Every place in `src/` that may even SPELL a package-manager command, and
# why. Both are text a human is shown; neither is ever an argv. Pinned as an
# exact set so a third one cannot appear without this test saying so.
ALLOWED_PACKAGE_MANAGER_MENTIONS = {
    # `doctor`'s fix line for a `wring` that is importable but not on PATH.
    # It has diagnosed and never repaired since it shipped.
    "doctor.py": ["pip install"],
    # The agent table. Install commands are the data it exists to hold.
    "agents.py": ["npm install"],
}


def test_no_package_manager_is_invoked_anywhere_in_src():
    """The §8 box, as a grep: `grep -rn` shows no package-manager invocation in
    `src/`. Two modules spell one as advice; nothing runs one."""
    tokens = ("npm install", "pip install", "brew install", "apt-get",
              "cargo install", "go install")
    spelled: dict[str, list[str]] = {}
    for path in sorted((repo_root() / "src" / "wringer").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        found = sorted(token for token in tokens if token in text)
        if found:
            spelled[path.name] = found
    assert spelled == ALLOWED_PACKAGE_MANAGER_MENTIONS, (
        "a package-manager command appeared somewhere new in src/. If it is "
        "advice, add it to ALLOWED_PACKAGE_MANAGER_MENTIONS with the reason; "
        "if it is an invocation, Wringer does not do that"
    )


def test_an_absent_agent_is_named_with_its_install_command_and_nothing_is_run(
    repo, bare_path, monkeypatch, capsys
):
    """§3c — absent = named, with the exact install command printed for the
    human to run. SPEC_ACP_V0 rule 3 fixes the code: exit 2 naming what to
    install."""
    absent = agents.AGENTS[0]
    monkeypatch.setenv("PATH", str(bare_path))
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--accept-gates", "--agent", absent.id])
    captured = capsys.readouterr()
    output = captured.out + captured.err

    assert code == cli.EXIT_CONFIG
    assert absent.install in output, "the install command was not printed"
    assert not (repo / config.CONFIG_FILENAME).exists(), (
        "a config was written for an agent that is not installed"
    )


def test_a_detected_agent_is_written_as_an_acp_worker(
    repo, fake_agent, monkeypatch, capsys
):
    real_gates(repo)
    """§3c — the wizard writes the worker stanza with consent, and `--agent
    <id>` is that consent given ahead of time."""
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--accept-gates", "--agent", fake_agent.id])
    capsys.readouterr()

    assert code == cli.EXIT_OK
    worker = read_config(repo).run.worker
    assert isinstance(worker, config.AcpWorker)
    assert worker.command == fake_agent.command
    assert worker.args == fake_agent.args
    assert worker.env_passthrough == (fake_agent.key_env,)


def test_the_wizard_writes_an_acp_worker_or_no_worker_at_all(
    repo, monkeypatch, capsys
):
    real_gates(repo)
    """§3a-ii — a shell worker inherits the operator's ENTIRE environment
    (`gates.py:95-102` passes no `env=`), so a wizard that wrote one would
    silently hand the agent every secret in the shell. Declining writes no
    `run:` section; it does not fall back to a shell worker it invented."""
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--accept-gates", "--no-agent"])
    capsys.readouterr()

    assert code == cli.EXIT_OK
    assert read_config(repo).run is None
    # The blank template carries a COMMENTED example worker, so the check
    # is on the parsed document rather than on the bytes.
    assert "run" not in raw_config(repo)


def test_the_emitter_takes_no_worker_form_but_the_acp_one():
    """The same rule, one layer down: there is no argument through which a
    shell string could reach the file."""
    import inspect

    signature = inspect.signature(start.emit)
    assert signature.parameters["worker"].annotation == "config.AcpWorker | None"


def test_a_missing_agent_answer_exits_2_naming_both_flags(
    repo, monkeypatch, capsys
):
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--accept-gates"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_CONFIG
    assert "--agent" in captured.err
    assert "--no-agent" in captured.err


def test_an_unknown_agent_id_is_refused_and_the_known_ones_named(
    repo, monkeypatch, capsys
):
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--accept-gates", "--agent", "not-an-agent"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_CONFIG
    for agent in agents.AGENTS:
        assert agent.id in captured.err


def test_the_acp_spec_no_longer_promises_a_consent_based_install():
    """§3c-i, and it is a §8 box: a binding spec that still promises the
    deferred feature is a contradiction, not a footnote. Two shipped error
    strings say Wringer never installs an agent, and Marc confirmed the ruling
    on 2026-08-06, so the parenthetical is what changes."""
    text = (repo_root() / "SPEC_ACP_V0.md").read_text(encoding="utf-8")
    assert "Consent-based install belongs to" not in text
    assert "never installs" in text or "does not install" in text


# --- the key: prompted, held in memory, written nowhere --------------------
def test_an_already_set_variable_satisfies_the_key_step(
    repo, fake_agent, monkeypatch, capsys
):
    real_gates(repo)
    """§3b, row 5 — the key's non-interactive form is the named variable
    already being set. That is how every other command in the program receives
    a credential, and it is what makes the launch runnable in CI."""
    monkeypatch.setenv(fake_agent.key_env, FAKE_KEY)
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--accept-gates", "--agent", fake_agent.id])
    captured = capsys.readouterr()

    assert code == cli.EXIT_OK
    assert fake_agent.key_env in captured.out, "the variable was not named"
    assert FAKE_KEY not in captured.out + captured.err, (
        "the value was printed — the name is the answer, never the value"
    )


def test_the_key_step_exits_2_naming_the_variable_with_no_terminal(
    repo, fake_agent, monkeypatch, capsys
):
    """§3b, row 5 — unset and no TTY is exit 2 naming the variable. Never a
    guess, never a hang."""
    monkeypatch.delenv(fake_agent.key_env, raising=False)
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--accept-gates", "--agent", fake_agent.id])
    captured = capsys.readouterr()

    assert code == cli.EXIT_CONFIG
    assert fake_agent.key_env in captured.err


def test_the_key_appears_in_no_file_the_wizard_writes(
    repo, fake_agent, monkeypatch, capsys
):
    real_gates(repo)
    """§8 — the key appears in no file the wizard writes, asserted by a test
    that greps for the value."""
    monkeypatch.setenv(fake_agent.key_env, FAKE_KEY)
    monkeypatch.chdir(repo)

    assert cli.main(["start", "--accept-gates", "--agent", fake_agent.id]) == 0
    capsys.readouterr()

    hits = [
        path.relative_to(repo).as_posix()
        for path in repo.rglob("*")
        if path.is_file()
        and ".git/" not in path.relative_to(repo).as_posix()
        and FAKE_KEY in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert hits == [], f"the credential reached {hits}"


def test_the_config_records_the_name_and_writes_no_judge_section(
    repo, fake_agent, monkeypatch, capsys
):
    real_gates(repo)
    """§3a — the wizard writes the key's variable name into
    `run.worker.acp.env_passthrough` and **nowhere else**. Not
    `judge.api_key_env`: that key exists only under `judge:`, whose parser
    hard-requires `endpoint`, `model` and `rubric` — three values law 5
    forbids guessing and that §1 never collects. Judging is not part of the
    launch."""
    monkeypatch.setenv(fake_agent.key_env, FAKE_KEY)
    monkeypatch.chdir(repo)

    assert cli.main(["start", "--accept-gates", "--agent", fake_agent.id]) == 0
    capsys.readouterr()

    raw = raw_config(repo)
    assert "judge" not in raw
    assert raw["run"]["worker"]["acp"]["env_passthrough"] == [fake_agent.key_env]


def test_the_declared_name_is_folded_into_the_redactor(repo, fake_agent):
    """§3a — the value is folded into the redactor before anything runs, the
    way `cmd_judge` already does it. Fold first, then act: the order is the
    guarantee, and the config the wizard wrote is what carries the name."""
    from wringer import redact

    start.emit(repo, worker=agents.worker(fake_agent)).write()
    cfg = read_config(repo)

    assert config.declared_secret_names(cfg) == (fake_agent.key_env,)
    redactor = redact.Redactor.from_config(
        cfg.evidence,
        environ={fake_agent.key_env: FAKE_KEY},
        extra_names=config.declared_secret_names(cfg),
    )
    assert redactor.scrub(f"leaked {FAKE_KEY}") == "leaked [REDACTED]"


def test_the_persistence_command_is_printed_and_never_run(
    repo, fake_agent, monkeypatch, capsys
):
    real_gates(repo)
    """§3a — it is never persisted. At the end the exact command to make it
    durable is printed, and neither it nor anything else is run. Storing a
    credential is a larger power than launching a build, and this slice was
    not granted it."""
    monkeypatch.setenv(fake_agent.key_env, FAKE_KEY)
    monkeypatch.chdir(repo)

    assert cli.main(["start", "--accept-gates", "--agent", fake_agent.id]) == 0
    out = capsys.readouterr().out

    assert start.PERSIST_HINT.format(name=fake_agent.key_env) in out
    assert "stores nothing" in out or "stored nothing" in out


@pytest.mark.skipif(os.name != "posix", reason="pty is POSIX-only, like the rest")
def test_the_key_step_cannot_hang_when_a_controlling_terminal_exists(
    repo, fake_agent, monkeypatch
):
    """§3a-i, and it is a §8 box. CPython's `getpass` opens **/dev/tty**, not
    stdin, falling back to stdin only if that fails. So closing or redirecting
    stdin does NOT stop it: reached under the demo recorder it would open the
    operator's real terminal, print its prompt where the recording cannot see
    it, and block forever — the recorder's read loop exits only on pty EOF or
    child exit, and its 30-second cap sits after that loop.

    So the `stdin.isatty()` gate is checked BEFORE `getpass` is ever called,
    and that ordering is a safety property rather than a style. This is the
    shape that hangs without it: stdin closed AND a controlling tty present.
    """
    import select
    import signal
    import time

    env = dict(os.environ)
    env.pop(fake_agent.key_env, None)
    argv = [
        sys.executable, "-m", "wringer", "start",
        "--accept-gates", "--agent", fake_agent.id,
    ]

    pid, master = pty.fork()
    if pid == 0:  # pragma: no cover - the child never returns
        try:
            os.chdir(repo)
            # pty.fork() made the pty this process's CONTROLLING terminal and
            # its stdin. Put /dev/null back on fd 0: stdin is then not a tty
            # while /dev/tty is still openable — exactly a recorder's shape.
            devnull = os.open(os.devnull, os.O_RDONLY)
            os.dup2(devnull, 0)
            os.execve(argv[0], argv, env)
        finally:
            os._exit(127)

    deadline = time.monotonic() + 30
    status: int | None = None
    output = b""
    while time.monotonic() < deadline:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                output += os.read(master, 65536)
            except OSError:  # the pty closed with the child
                pass
        finished, code = os.waitpid(pid, os.WNOHANG)
        if finished == pid:
            status = code
            break

    if status is None:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        os.close(master)
        pytest.fail(
            "wring start blocked with stdin closed and a controlling terminal "
            "present — the isatty gate is gone, and getpass is reading "
            "/dev/tty. Nothing would ever answer it"
        )

    os.close(master)
    text = output.decode("utf-8", errors="replace")
    assert os.waitstatus_to_exitcode(status) == cli.EXIT_CONFIG, text
    assert fake_agent.key_env in text


# --- prompts, and a terminal the whole surface can live without ------------


def scripted(answers=None, secret=None, interactive=True) -> start.Prompts:
    """A `Prompts` the suite drives instead of a terminal.

    The whole reason this seam exists: an interactive command that could only
    be exercised by a human is one nothing in CI ever runs, and `wring start`
    is the command a new user meets first.
    """
    queue = list(answers or [])

    def read(question: str) -> str:
        assert queue, f"the wizard asked one question too many: {question!r}"
        return queue.pop(0)

    def read_secret(question: str) -> str:
        assert secret is not None, f"the wizard asked for a secret: {question!r}"
        return secret

    return start.Prompts(
        read=read, read_secret=read_secret, interactive=lambda: interactive
    )


def refusing() -> start.Prompts:
    """A `Prompts` that fails loudly if anything tries to ask a question."""

    def never(question: str) -> str:
        raise AssertionError(f"a prompt was reached with no terminal: {question!r}")

    return start.Prompts(read=never, read_secret=never, interactive=lambda: False)


def test_no_prompt_is_reachable_when_stdin_is_not_a_tty(
    repo, fake_agent, monkeypatch, capsys
):
    """§8 — no prompt is reachable when stdin is not a TTY. Asserted by making
    every reader raise: if the `isatty` gate is ever bypassed, this fails with
    the question it tried to ask rather than hanging in CI."""
    monkeypatch.setattr(start, "prompts", refusing)
    monkeypatch.delenv(fake_agent.key_env, raising=False)
    monkeypatch.chdir(repo)

    assert cli.main(["start"]) == cli.EXIT_CONFIG
    capsys.readouterr()


def test_the_gates_step_prompts_when_there_is_a_terminal(
    repo, fake_agent, monkeypatch, capsys
):
    real_gates(repo)
    """§3b, row 1 — TTY and answers missing: prompt for exactly those."""
    monkeypatch.setattr(start, "prompts", lambda: scripted(["y", fake_agent.id]))
    monkeypatch.chdir(repo)

    assert cli.main(["start"]) == cli.EXIT_OK
    capsys.readouterr()

    assert read_config(repo).run is not None


def test_declining_the_gates_at_the_prompt_writes_nothing(
    repo, fake_agent, monkeypatch, capsys
):
    """A gate is a command that runs on this machine with the user's
    privileges. "No" stops the launch and leaves the repo untouched."""
    monkeypatch.setattr(start, "prompts", lambda: scripted(["n"]))
    monkeypatch.chdir(repo)

    code = cli.main(["start"])
    capsys.readouterr()

    assert code == cli.EXIT_REFUSED
    assert not (repo / config.CONFIG_FILENAME).exists()


def test_the_gate_prompt_defaults_to_no(repo, fake_agent, monkeypatch, capsys):
    """A bare Enter is not consent. `[y/N]` and it means it."""
    monkeypatch.setattr(start, "prompts", lambda: scripted([""]))
    monkeypatch.chdir(repo)

    assert cli.main(["start"]) == cli.EXIT_REFUSED
    capsys.readouterr()


def test_choosing_no_agent_at_the_prompt_writes_no_run_section(
    repo, fake_agent, monkeypatch, capsys
):
    real_gates(repo)
    monkeypatch.setattr(start, "prompts", lambda: scripted(["y", "none"]))
    monkeypatch.chdir(repo)

    assert cli.main(["start"]) == cli.EXIT_OK
    capsys.readouterr()

    assert read_config(repo).run is None


def test_an_unrecognised_agent_answer_is_asked_again_then_refused(
    repo, fake_agent, monkeypatch, capsys
):
    """Bounded re-asking. A wizard that loops forever on bad input is a
    hazard; one that gives up on the first typo is an annoyance."""
    monkeypatch.setattr(
        start, "prompts", lambda: scripted(["y", "nope", "still-nope", "wrong"])
    )
    monkeypatch.chdir(repo)

    code = cli.main(["start"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_CONFIG
    assert "--agent" in captured.err


def test_the_key_is_read_through_the_seam_and_never_printed(
    repo, fake_agent, monkeypatch, capsys
):
    real_gates(repo)
    """§3a — typed at a prompt, held in memory, echoed nowhere. The reader is
    injected so the suite never reaches `getpass`, which would open /dev/tty
    and block (§3a-i)."""
    typed = "sk-ant-notarealkey-prompted-9d21"
    monkeypatch.delenv(fake_agent.key_env, raising=False)
    monkeypatch.setattr(
        start, "prompts", lambda: scripted(["y", fake_agent.id], secret=typed)
    )
    monkeypatch.chdir(repo)

    assert cli.main(["start"]) == cli.EXIT_OK
    captured = capsys.readouterr()

    assert typed not in captured.out + captured.err
    assert os.environ[fake_agent.key_env] == typed, (
        "the key never reached the environment the launched agent reads"
    )
    assert typed not in (repo / config.CONFIG_FILENAME).read_text("utf-8")


def test_an_empty_key_at_the_prompt_is_not_an_answer(
    repo, fake_agent, monkeypatch, capsys
):
    monkeypatch.delenv(fake_agent.key_env, raising=False)
    monkeypatch.setattr(
        start, "prompts", lambda: scripted(["y", fake_agent.id], secret="   ")
    )
    monkeypatch.chdir(repo)

    code = cli.main(["start"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_CONFIG
    assert fake_agent.key_env in captured.err


def test_the_whole_surface_runs_with_stdin_closed_and_does_not_hang(
    repo, fake_agent
):
    """§8 — the whole surface runs with no terminal and does not hang. A real
    subprocess with stdin at /dev/null, every answer supplied, bounded by a
    timeout: the shape a CI job and an agent both present."""
    import subprocess

    real_gates(repo)

    proc = subprocess.run(
        [
            sys.executable, "-m", "wringer", "start",
            "--accept-gates", "--agent", fake_agent.id,
        ],
        cwd=repo,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == cli.EXIT_OK, proc.stdout + proc.stderr


# --- step 7: the first build, and the two things it refuses to call a pass --

REAL_GATE = """\
version: 1
gates:
  - id: test
    run: "true"
"""

FAILING_GATE = """\
version: 1
gates:
  - id: test
    run: "false"
"""

MISSING_COMMAND = """\
version: 1
gates:
  - id: test
    run: "definitely-not-a-real-command-xyz -q"
"""


def attestations(repo: Path) -> list[Path]:
    root = repo / ".wringer" / "attestations"
    return sorted(root.iterdir()) if root.is_dir() else []


def runs(repo: Path) -> list[Path]:
    root = repo / ".wringer" / "runs"
    return sorted(root.iterdir()) if root.is_dir() else []


def test_the_launch_ends_on_a_receipt_a_stranger_could_check(
    repo, monkeypatch, capsys
):
    """§8, box 1 — every answer supplied non-interactively, in a repo with
    real gates, running start to finish with no prompt and ending on a real
    `wring attest` receipt."""
    (repo / config.CONFIG_FILENAME).write_text(REAL_GATE, encoding="utf-8")
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--accept-gates", "--no-agent"])
    out = capsys.readouterr().out

    assert code == cli.EXIT_OK
    assert len(runs(repo)) == 1, "the launch ran no gates"
    assert len(attestations(repo)) == 1, "the launch left no receipt"
    assert "wring audit" in out, "the reader was not told how to check it"


def test_a_template_only_launch_says_so_and_attempts_no_receipt(
    repo, monkeypatch, capsys
):
    """§4 and §8 — the blank template ships a placeholder gate running `true`.
    A launch that ended "your first build passed" over it would be a vacuous
    green produced by the onboarding flow: the exact failure this project
    exists to prevent. It reports the template state, names the next real
    step, and does NOT attest."""
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--accept-gates", "--no-agent"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_REFUSED
    assert len(runs(repo)) == 1, "the gates should still have run"
    assert attestations(repo) == [], (
        "a receipt was written over a run that proved nothing"
    )
    assert "placeholder" in (captured.out + captured.err)


def test_failing_gates_are_exit_1_and_leave_no_receipt(repo, monkeypatch, capsys):
    """§2 — 1 means the gates answered no. A real answer, not a tool error."""
    (repo / config.CONFIG_FILENAME).write_text(FAILING_GATE, encoding="utf-8")
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--accept-gates", "--no-agent"])
    capsys.readouterr()

    assert code == cli.EXIT_GATE_FAILED
    assert attestations(repo) == []


def test_a_gate_whose_command_is_missing_is_diagnosed_not_crashed(
    repo, monkeypatch, capsys
):
    """§4 — `pytest: command not found` is the documented first failure
    (QUICKSTART.md). It is Wringer working correctly: it ran what the repo
    declared. Say that, rather than showing a shell error to someone who has
    just installed the tool."""
    (repo / config.CONFIG_FILENAME).write_text(MISSING_COMMAND, encoding="utf-8")
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--accept-gates", "--no-agent"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_GATE_FAILED
    assert "not on PATH" in captured.out + captured.err


def test_the_key_reaches_no_bundle_even_when_a_gate_echoes_it(
    repo, fake_agent, monkeypatch, capsys
):
    """§8, box 3 — the typed key appears in no file the wizard writes, no
    ledger and no bundle, asserted by a test that greps for the value. A gate
    is a shell command that inherits the whole environment, so it is the
    easiest thing in the program to leak a credential with."""
    (repo / config.CONFIG_FILENAME).write_text(
        f'version: 1\ngates:\n  - id: test\n    run: "echo ${fake_agent.key_env}"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    cli.main(["start", "--accept-gates", "--agent", fake_agent.id])
    capsys.readouterr()

    hits = [
        path.relative_to(repo).as_posix()
        for path in (repo / ".wringer").rglob("*")
        if path.is_file()
        and FAKE_KEY in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert hits == [], f"the credential reached the evidence: {hits}"


# --- §3e: a clone is untrusted input ---------------------------------------


def test_a_clone_stops_before_any_gate_runs(
    repo, tmp_path_factory, monkeypatch, capsys
):
    """Ruling 5, and it is the most important refusal in the command.
    `SPEC_GET_V0.md` is binding for the machinery being reused: *runs nothing
    it cloned*. A guided launch that cloned and then executed would be the
    most dangerous command in the program, aimed at the least technical user
    it has."""
    launchpad = tmp_path_factory.mktemp("launchpad")
    monkeypatch.chdir(launchpad)

    code = cli.main(
        ["start", "--clone", f"file://{repo}", "--workspace", "work"]
    )
    captured = capsys.readouterr()

    assert code == cli.EXIT_REFUSED
    cloned = launchpad / "work" / repo.name
    assert (cloned / ".git").is_dir(), "nothing was cloned"
    assert not (cloned / ".wringer" / "runs").exists(), (
        "a gate ran in a repository this command had just downloaded"
    )
    assert not (cloned / ".wringer" / "loops").exists()
    # The warning `wring get` already prints, and the second invocation.
    assert ".wringer.yaml" in captured.out
    assert "wring start" in captured.out


def test_a_clone_records_where_it_came_from(
    repo, tmp_path_factory, monkeypatch, capsys
):
    """The provenance half of §3e: it stops, but it does not stop silently."""
    import json as _json

    launchpad = tmp_path_factory.mktemp("launchpad")
    monkeypatch.chdir(launchpad)

    cli.main(["start", "--clone", f"file://{repo}", "--workspace", "work"])
    capsys.readouterr()

    manifests = sorted((launchpad / ".wringer" / "acquired").rglob("manifest.json"))
    assert len(manifests) == 1
    payload = _json.loads(manifests[0].read_text(encoding="utf-8"))
    assert payload["origin"] == f"file://{repo}"
    assert payload["head_sha"]


def test_cloning_without_a_workspace_exits_2_naming_the_flag(
    tmp_path_factory, monkeypatch, capsys
):
    """Config precedes clone (§4): `wring get` requires `workspace:` before it
    will clone, and there is no default because Wringer does not choose where
    to put your code."""
    launchpad = tmp_path_factory.mktemp("launchpad")
    monkeypatch.chdir(launchpad)

    code = cli.main(["start", "--clone", "file:///nowhere/at/all"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_CONFIG
    assert "--workspace" in captured.err


def test_a_repo_and_a_clone_together_are_refused():
    """Step 3 is EITHER a directory already on disk OR a clone (§1)."""
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["start", "--repo", ".", "--clone", "https://example.invalid/x"]
        )


MISSING_MODULE = """\
version: 1
gates:
  - id: test
    run: "python3 -m nosuchmodule_xyz"
"""


def test_a_gate_whose_module_is_missing_is_diagnosed_too(
    repo, monkeypatch, capsys
):
    """The same failure wears two faces. `pytest -q` with no pytest is
    `command not found` and exit 127; `python3 -m pytest` with no pytest is
    exit 1 and "No module named pytest". A real launch on this machine hit
    the second one, and only the first was diagnosed."""
    (repo / config.CONFIG_FILENAME).write_text(MISSING_MODULE, encoding="utf-8")
    monkeypatch.chdir(repo)

    code = cli.main(["start", "--accept-gates", "--no-agent"])
    captured = capsys.readouterr()

    assert code == cli.EXIT_GATE_FAILED
    assert "not installed in the environment" in captured.out + captured.err
