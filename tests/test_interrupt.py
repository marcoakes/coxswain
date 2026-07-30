"""Ctrl-C: exit 4, a bundle that admits it stopped, and no surviving gate."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from wringer import cli, evidence, gates

TWO_GATES = """\
version: 1
gates:
  - id: first
    run: "true"
  - id: second
    run: "true"
"""


def only_bundle(root: Path) -> Path:
    runs = sorted((root / evidence.RUNS_DIRNAME).iterdir())
    assert len(runs) == 1, runs
    return runs[0]


def test_an_interrupted_run_exits_four_and_marks_the_bundle(
    repo, write_config, monkeypatch, capsys
):
    write_config(repo, TWO_GATES)
    monkeypatch.chdir(repo)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(gates, "run", interrupt)

    assert cli.main(["verify"]) == cli.EXIT_INTERRUPTED

    bundle = only_bundle(repo)
    recorded = [
        json.loads(line)
        for line in (bundle / evidence.EVIDENCE_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    finished = recorded[-1]
    assert finished["type"] == "run.finished"
    assert finished["status"] == "interrupted"
    # the gate that was running started and never finished — that is the
    # honest record, so no gate.finished is invented for it
    assert [event["type"] for event in recorded].count("gate.finished") == 0

    manifest = json.loads(
        (bundle / evidence.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest["result"] == {"status": "interrupted", "failed_gate": None}

    summary = (bundle / "summary.md").read_text(encoding="utf-8")
    assert "**interrupted**" in summary
    assert "| second | skipped |" in summary  # the gate that never got a turn

    assert "interrupted" in capsys.readouterr().out


def test_json_reports_the_interruption_too(
    repo, write_config, monkeypatch, capfd
):
    write_config(repo, TWO_GATES)
    monkeypatch.chdir(repo)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(gates, "run", interrupt)

    assert cli.main(["verify", "--json"]) == cli.EXIT_INTERRUPTED

    payload = json.loads(capfd.readouterr().out)
    assert payload["status"] == "interrupted"
    assert payload["failed_gate"] is None


def test_a_real_sigint_kills_the_gate_and_exits_four(repo, write_config):
    """The gate runs in its own process group, so Ctrl-C never reaches it.
    If Wringer does not stop it, it outlives the verifier."""
    write_config(
        repo,
        """\
version: 1
gates:
  - id: slow
    run: echo $$ > gate.pid; sleep 30
""",
    )

    proc = subprocess.Popen(
        [sys.executable, "-m", "wringer", "verify"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    pid_file = repo / "gate.pid"
    deadline = time.monotonic() + 20
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert pid_file.exists(), "the gate never started"

    proc.send_signal(signal.SIGINT)
    proc.communicate(timeout=20)

    assert proc.returncode == cli.EXIT_INTERRUPTED

    gate_pid = int(pid_file.read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(gate_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"gate process {gate_pid} survived the interrupt")

    bundle = only_bundle(repo)
    manifest = json.loads(
        (bundle / evidence.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest["result"]["status"] == "interrupted"
