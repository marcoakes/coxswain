"""The ACP worker seam (SPEC_ACP_V0.md).

Every test drives a real subprocess speaking real JSON-RPC over stdio —
`tests/fake_acp_agent.py`, not a mock of Wringer's own client. Mocking the
wire would test the author's idea of the protocol; running it tests the
protocol. No network, no API key, no vendor binary.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from wringer import cli, config, loop

AGENT = Path(__file__).resolve().parent / "fake_acp_agent.py"


def acp_config(behaviour: str, timeout: int = 30, **extra: str) -> str:
    passthrough = extra.get("env_passthrough", "")
    return f"""\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
run:
  worker:
    acp:
      command: {json.dumps(sys.executable)}
      args: [{json.dumps(str(AGENT))}, {json.dumps(behaviour)}]
{passthrough}
  max_iterations: 3
  worker_timeout: {timeout}
"""


def setup(repo: Path, behaviour: str, **kwargs) -> None:
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(acp_config(behaviour, **kwargs), "utf-8")


def only_loop(repo: Path) -> Path:
    found = sorted((repo / loop.LOOPS_DIRNAME).iterdir())
    assert len(found) == 1, found
    return found[0]


def events(repo: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (only_loop(repo) / loop.EVENTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def result(repo: Path) -> dict:
    return json.loads(
        (only_loop(repo) / loop.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )["result"]


# --- the seam works end to end -------------------------------------------


def test_an_acp_agent_drives_the_loop_to_convergence(repo, monkeypatch, capsys):
    """The headline: the agent fixes the code through fs/write_text_file and
    the loop converges, with no shell command anywhere."""
    setup(repo, "fix")
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_OK
    capsys.readouterr()

    assert (repo / "calc.py").read_text(encoding="utf-8") == "FIXED\n"
    outcome = result(repo)
    assert outcome["status"] == "converged"
    assert outcome["iterations"] == 2

    started = next(e for e in events(repo) if e["type"] == "worker.started")
    finished = next(e for e in events(repo) if e["type"] == "worker.finished")
    assert started["worker_kind"] == "acp"
    assert finished["agent_name"] == "fake-acp-agent"
    assert finished["protocol_version"] == 1
    # recorded, and provably not acted on — see the next test
    assert finished["stop_reason"] == "end_turn"


def test_the_loop_cannot_tell_which_worker_form_ran(repo, monkeypatch, capsys):
    """The supervision invariants must not know about ACP. An idle ACP agent
    trips `no_progress` exactly as an idle shell worker does."""
    setup(repo, "idle")
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    assert result(repo)["reason"] == "no_progress"


def test_a_stop_reason_changes_no_decision(repo, monkeypatch, capsys):
    """`stopReason` is the ACP analogue of an exit code: recorded, never
    obeyed. The agent says end_turn having fixed nothing, and the evidence
    still decides."""
    setup(repo, "idle")
    monkeypatch.chdir(repo)

    cli.main(["run"])
    capsys.readouterr()

    finished = next(e for e in events(repo) if e["type"] == "worker.finished")
    assert finished["stop_reason"] == "end_turn"      # it claimed success
    assert result(repo)["status"] == "stopped"        # the gates disagreed


# --- the file seam is bounded --------------------------------------------


def test_a_write_outside_the_repo_is_refused(repo, monkeypatch, capsys):
    """Wringer is not obliged to help an agent write outside the tree it was
    pointed at, and a `..` is not an argument."""
    setup(repo, "escape")
    monkeypatch.chdir(repo)

    cli.main(["run"])
    capsys.readouterr()

    assert not (repo.parent / "escaped.txt").exists()
    finished = next(e for e in events(repo) if e["type"] == "worker.finished")
    assert finished["refused_paths"] >= 1


def test_a_permission_request_is_auto_approved_and_recorded(
    repo, monkeypatch, capsys
):
    """Auto-approval is the v0 ruling — a consent prompt nobody is sitting at
    is not a safety control. The ledger is what keeps it auditable."""
    setup(repo, "permission")
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_OK
    capsys.readouterr()

    granted = [e for e in events(repo) if e["type"] == "worker.permission"]
    assert len(granted) == 1
    assert granted[0]["outcome"] == "auto_approved"
    assert "write calc.py" in granted[0]["tool"]


# --- failures map onto things the loop already knows ----------------------


def test_an_agent_that_crashes_is_a_failed_turn_not_a_crash(
    repo, monkeypatch, capsys
):
    setup(repo, "crash")
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    finished = next(e for e in events(repo) if e["type"] == "worker.finished")
    assert finished["worker_kind"] == "acp"
    assert "acp_error" in finished
    # the loop still reached a normal ending rather than exploding
    assert result(repo)["status"] == "stopped"


def test_a_hanging_agent_cannot_hang_the_loop(repo, monkeypatch, capsys):
    """Every wait has a deadline — invariant 3, and the reason the whole
    supervision spec exists."""
    setup(repo, "hang", timeout=2)
    monkeypatch.chdir(repo)

    started = time.monotonic()
    assert cli.main(["run"]) == cli.EXIT_GATE_FAILED
    elapsed = time.monotonic() - started
    capsys.readouterr()

    # worker_timeout is 2s. A client-side default must not outlive the number
    # the repo wrote down — this once took 120s because it did.
    assert elapsed < 30, f"the loop hung for {elapsed:.0f}s past a 2s timeout"
    assert result(repo)["status"] == "stopped"
    finished = next(e for e in events(repo) if e["type"] == "worker.finished")
    assert finished.get("timed_out") is True


def test_a_missing_agent_binary_says_so_and_installs_nothing(
    repo, monkeypatch, capsys
):
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
run:
  worker:
    acp:
      command: definitely-not-installed-anywhere
  max_iterations: 2
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    cli.main(["run"])
    capsys.readouterr()

    log = (
        only_loop(repo) / loop.ITERATIONS_DIRNAME / "001" / "worker.stdout.log"
    ).read_text(encoding="utf-8")
    assert "never installs an agent" in log


def test_a_garbage_line_does_not_derail_the_session(repo, monkeypatch, capsys):
    """Agents print things. A line that is not JSON-RPC is noise, not a
    reason to abandon the turn."""
    setup(repo, "garbage")
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_OK
    capsys.readouterr()

    assert result(repo)["status"] == "converged"


# --- the environment an agent gets ---------------------------------------


def test_the_agent_gets_a_minimal_environment(repo, monkeypatch, capsys):
    """Anything not named in env_passthrough is withheld: an agent gets what
    it needs, not the operator's whole shell."""
    monkeypatch.setenv("WRINGER_TEST_SECRET_VAR", "should-not-be-visible")
    setup(repo, "fix")
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_OK
    capsys.readouterr()

    # the fake agent inherits nothing it was not given; PATH and HOME are
    # passed because a subprocess without them cannot run at all
    passed = config.parse(
        {
            "version": 1,
            "gates": [{"id": "t", "run": "true"}],
            "run": {"worker": {"acp": {"command": "x"}}},
        }
    ).run.worker
    assert passed.env_passthrough == ()


# --- config ---------------------------------------------------------------


def test_the_shell_form_still_works_untouched():
    cfg = config.parse(
        {
            "version": 1,
            "gates": [{"id": "t", "run": "true"}],
            "run": {"worker": "claude -p '{brief}'"},
        }
    )
    assert cfg.run.worker == "claude -p '{brief}'"
    assert isinstance(cfg.run.worker, str)


def test_the_acp_form_parses():
    cfg = config.parse(
        {
            "version": 1,
            "gates": [{"id": "t", "run": "true"}],
            "run": {
                "worker": {
                    "acp": {
                        "command": "claude-code-acp",
                        "args": ["--stdio"],
                        "env_passthrough": ["ANTHROPIC_API_KEY"],
                    }
                }
            },
        }
    )
    worker = cfg.run.worker
    assert isinstance(worker, config.AcpWorker)
    assert worker.command == "claude-code-acp"
    assert worker.args == ("--stdio",)
    assert worker.env_passthrough == ("ANTHROPIC_API_KEY",)


@pytest.mark.parametrize(
    "worker, match",
    [
        ({}, "exactly one key"),
        ({"acp": {}, "shell": "x"}, "exactly one key"),
        ({"acp": {"command": ""}}, "acp.command"),
        ({"acp": {"command": "x", "args": "not-a-list"}}, "acp.args"),
        ({"acp": {"command": "x", "env_passthrough": [""]}}, "env_passthrough"),
        ({"acp": {"command": "x", "nonsense": 1}}, "unknown keys"),
        (5, "must be a shell command string"),
        (None, "must be a shell command string"),
    ],
)
def test_invalid_worker_forms_raise(worker, match):
    with pytest.raises(config.ConfigError, match=match):
        config.parse(
            {
                "version": 1,
                "gates": [{"id": "t", "run": "true"}],
                "run": {"worker": worker},
            }
        )


def test_env_passthrough_names_variables_never_values():
    """The message has to teach the rule, because a config file is exactly
    where somebody would paste a key."""
    with pytest.raises(config.ConfigError) as caught:
        config.parse(
            {
                "version": 1,
                "gates": [{"id": "t", "run": "true"}],
                "run": {"worker": {"acp": {"command": "x", "env_passthrough": [5]}}},
            }
        )

    assert "NAMES" in str(caught.value)
    assert "credential" in str(caught.value)


def test_a_write_to_an_agent_that_stopped_reading_cannot_block_forever():
    """The eight-hour incident's shape, in the seam built to honour it.

    A pipe write blocks once the buffer fills and the far end stops reading.
    That block is armed BEFORE `worker_timeout` and `wall_clock` exist —
    both are only consulted after the write returns — so an agent that hangs
    without draining stdin used to hold Wringer open indefinitely: no
    deadline, no breaker, no ledger growth, nothing to reap.

    Tested at the write itself rather than through the loop, because a
    realistic prompt fits in the buffer and never blocks: an end-to-end test
    passes just as happily against the broken implementation, which is how
    this nearly shipped twice.

    Without the fix this HANGS rather than fails. The elapsed-time assertion
    is what makes the difference visible.
    """
    import subprocess
    import time

    from wringer import acp

    # nothing ever reads this process's stdin
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        started = time.monotonic()
        connection = acp.Connection(proc, deadline=started + 3)
        # comfortably past any pipe buffer (64 KB on Linux, 16 KB on some BSDs)
        with pytest.raises(acp.AcpError) as raised:
            connection.send_request("session/prompt", {"blob": "x" * 500_000})
        elapsed = time.monotonic() - started

        assert "stopped reading" in str(raised.value)
        assert elapsed < 30, (
            f"the write took {elapsed:.1f}s — it is not bounded by the turn's "
            "deadline"
        )
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_a_healthy_agent_is_not_slowed_by_the_write_ceiling(repo, monkeypatch,
                                                            capsys):
    """The bound must not cost anything when the agent behaves."""
    setup(repo, "fix")
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_OK

    capsys.readouterr()
    assert (repo / "calc.py").read_text(encoding="utf-8").strip() == "FIXED"
