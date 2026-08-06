"""`wring attest` and `wring audit` — SPEC_PROVENANCE_V0.md.

> "Who wrote this code, under whose authority, verified how?" — answered by a
> file, checkable offline, by someone who trusts none of us.

Neither command calls an LLM and neither opens a socket, ever. There is no
`--send` here and never will be, so every test in this file runs offline by
construction rather than by faking a transport.

The first section is the spec's §2a prerequisites: before `attest` can claim
"and none of it has been altered since", the bundles it claims about have to
carry the digests that make the claim checkable. Only the verify bundle did.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from wringer import cli, evidence, judge

CONFIG = """\
version: 1
gates:
  - id: check
    run: "true"
forge:
  kind: github
  endpoint: https://api.github.com
  repo: owner/name
  token_env: FORGE_TOKEN
deliver:
  branch: "wringer/{run}"
  base: main
  remote: origin
judge:
  endpoint: https://api.example.invalid/v1/messages
  model: test-model
  rubric: rubric.yaml
"""

RUBRIC = """\
schema_version: wringer.rubric.v1
title: Acceptance criteria
criteria:
  - id: tested
    title: a new behaviour has a test that fails without it
    required: true
"""


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=cwd, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def digests_of(bundle: Path) -> dict:
    return json.loads(
        (bundle / evidence.DIGESTS_FILENAME).read_text(encoding="utf-8")
    )


def files_in(bundle: Path) -> set[str]:
    return {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != evidence.DIGESTS_FILENAME
    }


def digests_cover_everything(bundle: Path) -> None:
    recorded = digests_of(bundle)
    assert set(recorded["files"]) == files_in(bundle), (
        f"{bundle.name}: digests.json does not cover "
        f"{sorted(files_in(bundle) - set(recorded['files']))}"
    )
    for name, expected in recorded["files"].items():
        actual = hashlib.sha256((bundle / name).read_bytes()).hexdigest()
        assert actual == expected, f"{bundle.name}/{name} does not match"


@pytest.fixture
def project(repo: Path) -> Path:
    """A repo with a `file://` origin, a rubric, and a change to ship."""
    upstream = repo.parent / f"{repo.name}-attest-upstream.git"
    git(repo, "init", "--bare", "-b", "main", str(upstream))
    git(repo, "remote", "add", "origin", f"file://{upstream}")
    (repo / ".wringer.yaml").write_text(CONFIG, encoding="utf-8")
    (repo / "rubric.yaml").write_text(RUBRIC, encoding="utf-8")
    (repo / ".gitignore").write_text(".wringer/\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "config")
    git(repo, "push", "-u", "origin", "main")
    (repo / "feature.py").write_text("def added():\n    return 1\n", encoding="utf-8")
    return repo


def only(root: Path, *parts: str) -> Path:
    found = sorted((root.joinpath(*parts)).iterdir())
    assert len(found) == 1, found
    return found[0]


# --- §2a: every bundle carries its own digests -----------------------------
#
# `attest`'s refusal rules say "a referenced bundle has no digests.json ->
# cannot attest what cannot be checked". Before this, only the VERIFY bundle
# had one, so every judged, delivered or looped clause would have been refused
# — the feature would have shipped able to attest almost nothing.


def test_a_verdict_bundle_carries_its_own_digests(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["judge"]) == cli.EXIT_OK
    capsys.readouterr()

    digests_cover_everything(only(project, ".wringer", "verdicts"))


def test_a_delivery_bundle_carries_its_own_digests(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["deliver"]) == cli.EXIT_OK
    capsys.readouterr()

    digests_cover_everything(only(project, ".wringer", "deliveries"))


def test_a_loop_bundle_carries_its_own_digests(repo, monkeypatch, capsys):
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        'version: 1\ngates:\n  - id: test\n    run: "grep -q FIXED calc.py"\n'
        'run:\n  worker: "echo FIXED > calc.py"\n  max_iterations: 3\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)
    assert cli.main(["run"]) == cli.EXIT_OK
    capsys.readouterr()

    digests_cover_everything(only(repo, ".wringer", "loops"))


def test_a_fleet_bundle_carries_its_own_digests(repo, monkeypatch, capsys):
    from test_fleet import FALLBACK_CONFIG, make_task

    task = make_task(repo, "good", "sh -c 'printf FIXED > work.txt'")
    (repo / ".wringer.yaml").write_text(FALLBACK_CONFIG, encoding="utf-8")
    (repo / "tasks.jsonl").write_text(json.dumps(task) + "\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    cli.main(["fleet", "tasks.jsonl"])
    capsys.readouterr()

    digests_cover_everything(only(repo, ".wringer", "fleets"))


def test_the_digest_file_is_written_last_in_every_bundle(project, monkeypatch,
                                                          capsys):
    """It cannot cover a file written after it. The verify bundle's ordering
    already had a test; these three did not exist to have one."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["judge"]) == cli.EXIT_OK
    assert cli.main(["deliver"]) == cli.EXIT_OK
    capsys.readouterr()

    # each bundle's own last-written file, which is the one an ordering bug
    # drops first
    verdicts = digests_of(only(project, ".wringer", "verdicts"))["files"]
    assert judge.VERDICT_FILENAME in verdicts, sorted(verdicts)
    assert evidence.SUMMARY_FILENAME in verdicts, sorted(verdicts)

    deliveries = digests_of(only(project, ".wringer", "deliveries"))["files"]
    assert evidence.MANIFEST_FILENAME in deliveries, sorted(deliveries)
    assert "mr.md" in deliveries, sorted(deliveries)


# --- §2a: the MR body must quote a verdict about THIS run ------------------


def test_the_mr_body_never_quotes_a_verdict_about_another_run(
    project, monkeypatch, capsys
):
    """`_verdict` embedded whichever verdict was NEWEST, matched to nothing.

    A verdict about a different change is worse than no verdict: the merge
    request says a rubric passed, and it passed against other code.
    """
    monkeypatch.chdir(project)
    # run one: verified and judged
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["judge"]) == cli.EXIT_OK
    capsys.readouterr()
    first_verdict = only(project, ".wringer", "verdicts")
    payload = json.loads(
        (first_verdict / judge.VERDICT_FILENAME).read_text(encoding="utf-8")
    )
    payload["verdict"] = "pass"
    payload["note"] = "JUDGED THE OTHER RUN"
    (first_verdict / judge.VERDICT_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )

    # run two: verified only, and it is the one being delivered
    (project / "feature.py").write_text("def added():\n    return 2\n", "utf-8")
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main(["deliver"]) == cli.EXIT_OK
    capsys.readouterr()

    body = (only(project, ".wringer", "deliveries") / "mr.md").read_text("utf-8")
    assert "JUDGED THE OTHER RUN" not in body, (
        "the merge request quoted a verdict about a different change"
    )


def test_the_mr_body_still_quotes_a_verdict_about_this_run(
    project, monkeypatch, capsys
):
    """The control. Matching must not throw away the verdict that belongs."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["judge"]) == cli.EXIT_OK
    capsys.readouterr()
    verdict_dir = only(project, ".wringer", "verdicts")
    payload = json.loads(
        (verdict_dir / judge.VERDICT_FILENAME).read_text(encoding="utf-8")
    )
    payload["verdict"] = "pass"
    payload["note"] = "THIS RUN EXACTLY"
    (verdict_dir / judge.VERDICT_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )

    assert cli.main(["deliver"]) == cli.EXIT_OK
    capsys.readouterr()

    body = (only(project, ".wringer", "deliveries") / "mr.md").read_text("utf-8")
    assert "THIS RUN EXACTLY" in body


