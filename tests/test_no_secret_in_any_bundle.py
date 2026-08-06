"""One question, asked of the whole program: can a credential reach an artifact?

Every other redaction test in this suite is **per-path** — written by whoever
built that path, covering that path. That is exactly how two leaks shipped:

- `acp.py` handed the agent's stderr a raw file handle and wrote its session
  updates unscrubbed. Found 2026-08-06 while building `wring start`.
- `vacuity.py` ran the pre-change gates through `gates.run` with no redactor
  at all, so `--prove`'s logs got no scrubbing — not even the built-in
  `*TOKEN*`/`*SECRET*`/`*KEY*` defaults. Found the same day.

Both were new write paths into a bundle, and both needed somebody to remember
to test them. Twice nobody did. `AGENTS.md` already states the invariant —
*"If you add a file to the bundle, add it through the `Bundle`, or you have
quietly opted out of the one guarantee SECURITY.md makes"* — and nothing
enforced it.

This file enforces it, and it does so in the one way that survives future
carelessness: it does not enumerate write paths. It plants credentials in the
environment, drives the commands that produce artifacts, then walks **every
file under `.wringer/`** and asserts the values are in none of them. A write
path added next year is covered the day it is added, by nobody's diligence.

Two secrets, deliberately:

- `WRINGER_TEST_API_KEY` matches the redactor's default `*KEY*` pattern, so it
  is protected however the config is read.
- `WRINGER_TEST_CREDENTIAL` matches **none** of the defaults. The only thing
  that can save it is `config.declared_secret_names` reaching the redactor
  that write path used. It is the canary for the whole `env_passthrough`
  promise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from wringer import cli

AGENT = Path(__file__).resolve().parent / "fake_acp_agent.py"

# Long enough to clear `redact.MIN_SECRET_LENGTH`, and obviously fake: a
# fixture credential that could be mistaken for a real one is a hazard in a
# repo whose product is evidence.
PLAIN_NAME = "WRINGER_TEST_CREDENTIAL"
PLAIN_VALUE = "notarealcredential-sweep-0f41c9d2ab73"
KEYED_NAME = "WRINGER_TEST_API_KEY"
KEYED_VALUE = "sk-ant-notarealkey-sweep-77b3e0a4"

RUBRIC = """\
schema_version: wringer.rubric.v1
title: Acceptance criteria
criteria:
  - id: it-works
    title: The change does what it says
    guidance: Say whether it does.
    required: true
"""


def config_body() -> str:
    """A repo that opted into everything that writes an artifact."""
    return f"""\
version: 1
gates:
  - id: leak
    run: "echo ${PLAIN_NAME} ${KEYED_NAME}"
  # Leaks AND is change-sensitive: the echo always runs, the grep decides the
  # exit. That makes it fail on the pre-change tree with the credentials in
  # its log, which is the one input that drives `vacuity._cite` — the
  # function that lifts a line of gate output INTO `vacuity.json`. Without a
  # gate of this shape the sweep never exercises that path.
  - id: fixed
    run: "echo ${PLAIN_NAME} ${KEYED_NAME} && grep -q FIXED calc.py"

run:
  worker:
    acp:
      command: {json.dumps(sys.executable)}
      args: [{json.dumps(str(AGENT))}, "leak"]
      env_passthrough: [{PLAIN_NAME}, {KEYED_NAME}]
  max_iterations: 3
  worker_timeout: 30

judge:
  endpoint: http://127.0.0.1:11434/v1/chat/completions
  model: a-model
  rubric: rubric.yaml
  api_key_env: {KEYED_NAME}

deliver:
  branch: "wringer/{{run}}"
  remote: origin
"""


def artifacts(repo: Path) -> list[Path]:
    return [path for path in (repo / ".wringer").rglob("*") if path.is_file()]


def mentions(repo: Path, needle: str) -> list[str]:
    hits = []
    for path in artifacts(repo):
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover - nothing here is unreadable
            continue
        if needle in body:
            hits.append(path.relative_to(repo).as_posix())
    return hits


@pytest.fixture
def leaky_repo(repo: Path, git_run, tmp_path_factory, monkeypatch) -> Path:
    monkeypatch.setenv(PLAIN_NAME, PLAIN_VALUE)
    monkeypatch.setenv(KEYED_NAME, KEYED_VALUE)
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / "rubric.yaml").write_text(RUBRIC, encoding="utf-8")
    (repo / ".wringer.yaml").write_text(config_body(), encoding="utf-8")
    (repo / ".gitignore").write_text(".wringer/\n", encoding="utf-8")
    git_run(repo, "add", "-A")
    git_run(repo, "commit", "-qm", "a repo that leaks from every seam")

    # A real `origin`, on disk. `wring deliver` refuses when the remote's
    # default branch cannot be resolved — one of its five refusals — so
    # without this the delivery bundle is never written and the sweep would
    # silently stop covering that write path.
    origin = tmp_path_factory.mktemp("origin") / "bare.git"
    git_run(repo, "init", "--bare", "-q", str(origin))
    git_run(repo, "remote", "add", "origin", str(origin))
    git_run(repo, "push", "-q", "origin", "main")
    git_run(repo, "remote", "set-head", "origin", "-a")

    monkeypatch.chdir(repo)
    return repo


def test_no_command_writes_a_credential_into_any_artifact(
    leaky_repo: Path, capsys
):
    """The sweep. Every command that produces an artifact runs against a repo
    whose gate echoes two credentials and whose agent echoes them back, and
    then every file is read.

    Deliberately NOT a list of write paths to check — that is the shape that
    failed twice. It is a list of commands to RUN, and an assertion over
    whatever they leave behind.
    """
    repo = leaky_repo

    # The loop: gates fail, the ACP agent leaks and fixes, gates pass. Covers
    # the loop bundle, its worker logs, its ledger, and every verify bundle
    # nested underneath it.
    assert cli.main(["run"]) == cli.EXIT_OK
    # Attested BEFORE the judge runs: `attest` refuses to stand over a dry-run
    # verdict, because a `judged_by` clause about a judgment nobody made would
    # be theatre. The order here is the program's rules, not a preference.
    assert cli.main(["attest"]) == cli.EXIT_OK
    assert cli.main(["judge"]) == cli.EXIT_OK          # dry run: no socket
    assert cli.main(["deliver"]) == cli.EXIT_OK        # dry run: no git write
    # Last, because a vacuity verdict is one more thing `attest` may refuse:
    # the pre-change gate logs are the path that had no redactor at all.
    cli.main(["verify", "--prove"])
    capsys.readouterr()

    assert artifacts(repo), "no artifacts were produced, so nothing was tested"

    leaked = {
        PLAIN_NAME: mentions(repo, PLAIN_VALUE),
        KEYED_NAME: mentions(repo, KEYED_VALUE),
    }
    assert leaked == {PLAIN_NAME: [], KEYED_NAME: []}, (
        "a credential reached an artifact. Whatever wrote those files did not "
        "go through the Bundle's redactor — AGENTS.md: add it through the "
        f"Bundle or you have quietly opted out of SECURITY.md's guarantee.\n"
        f"{json.dumps(leaked, indent=2)}"
    )


def test_the_sweep_would_notice_a_leak(leaky_repo: Path, capsys):
    """The guard on the guard.

    A sweep that passes because nothing was ever written, or because the
    secret never reached the machinery, is a sweep that proves nothing — and
    this repo has thrown away two tests that passed against broken code. So:
    the scrubbing must be visibly happening, and the values must really be in
    the environment the gates and the agent inherit.
    """
    repo = leaky_repo

    assert cli.main(["run"]) == cli.EXIT_OK
    capsys.readouterr()

    assert mentions(repo, "[REDACTED]"), (
        "nothing in the evidence was scrubbed at all — either the gate never "
        "echoed the credentials or the bundle recorded nothing, and the sweep "
        "above would pass over an empty tree"
    )
