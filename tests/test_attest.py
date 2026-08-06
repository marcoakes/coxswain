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

from wringer import attest, cli, deliver, evidence, judge

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




# --- wring attest ----------------------------------------------------------


def attested(root: Path) -> Path:
    return only(root, ".wringer", "attestations") / attest.ATTESTATION_FILENAME


def payload_of(root: Path) -> dict:
    return json.loads(attested(root).read_text(encoding="utf-8"))


def verified_and_delivered(project: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["deliver"]) == cli.EXIT_OK
    capsys.readouterr()


def test_attest_over_a_bare_verify_bundle_makes_the_clauses_it_can(
    project, monkeypatch, capsys
):
    """"The clauses it lacks inputs for are absent, not invented." An
    attestation over a bare `wring verify` bundle is small and still worth
    having."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()

    payload = payload_of(project)
    assert payload["schema_version"] == "wringer.attestation.v1"
    assert "proven_by" in payload
    assert "judged_by" not in payload, "a clause was invented"
    assert "delivered_as" not in payload, "a clause was invented"
    assert payload["proven_by"]["gates"][0]["gate_id"] == "check"
    assert [b["role"] for b in payload["bundles"]] == ["run"]


def test_attest_over_the_whole_loop_makes_every_clause(
    project, monkeypatch, capsys
):
    """A spec, a run, a verdict and a delivery — the full claim."""
    monkeypatch.chdir(project)
    (project / "wringer.spec.yaml").write_text(
        "schema_version: wringer.spec.v1\napproved: true\ntitle: t\n"
        "intent: |2\n  words\ncriteria:\n  - id: c1\n    title: T\n"
        "    required: true\n    human: false\n"
        "tasks:\n  - id: t1\n    brief: briefs/t1.md\n    dir: .\n"
        "    objective: o\n",
        encoding="utf-8",
    )
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["judge"]) == cli.EXIT_OK
    capsys.readouterr()
    # a dry-run verdict is refused (below), so make this one live-shaped
    verdict_dir = only(project, ".wringer", "verdicts")
    record = verdict_dir / judge.VERDICT_FILENAME
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["mode"] = "live"
    payload["verdict"] = "pass"
    record.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    evidence.digest_directory(verdict_dir)  # re-anchor after the edit

    assert cli.main(["deliver"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()

    built = payload_of(project)
    assert built["authorized_by"]["approved"] is True
    assert built["proven_by"]["head_sha"]
    assert built["judged_by"]["verdict"] == "pass"
    assert built["delivered_as"]["branch"].startswith("wringer/")
    assert {b["role"] for b in built["bundles"]} == {"run", "verdict", "delivery"}


def test_attest_records_the_digest_of_every_bundle_it_names(
    project, monkeypatch, capsys
):
    """"Bundles link by path; the attestation re-anchors by digest." From the
    moment it is written the linkage is content-addressed."""
    verified_and_delivered(project, monkeypatch, capsys)
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()

    for ref in payload_of(project)["bundles"]:
        recorded = project / ref["path"] / evidence.DIGESTS_FILENAME
        actual = hashlib.sha256(recorded.read_bytes()).hexdigest()
        assert actual == ref["digests_sha256"], ref["path"]


# --- §3: the refusals ------------------------------------------------------


def test_attest_refuses_a_bundle_with_no_digests(project, monkeypatch, capsys):
    """"Cannot attest what cannot be checked." Every pre-0.3 bundle is in
    this shape, which is why the message says what to do."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    (only(project, ".wringer", "runs") / evidence.DIGESTS_FILENAME).unlink()

    assert cli.main(["attest"]) == cli.EXIT_GATE_FAILED
    assert "cannot attest what cannot be checked" in capsys.readouterr().err


def test_attest_refuses_a_bundle_whose_digest_no_longer_matches(
    project, monkeypatch, capsys
):
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    run_dir = only(project, ".wringer", "runs")
    log = next((run_dir / "gates").rglob("stdout.log"))
    log.write_bytes(log.read_bytes() + b"tampered\n")

    assert cli.main(["attest"]) == cli.EXIT_GATE_FAILED
    assert "stdout.log" in capsys.readouterr().err


def test_attest_refuses_a_broken_ledger_chain(project, monkeypatch, capsys):
    """`prev_hash` was written on every event and read by nothing. This is
    the first code that reads it."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    run_dir = only(project, ".wringer", "runs")
    ledger = run_dir / evidence.EVIDENCE_FILENAME
    lines = ledger.read_text(encoding="utf-8").splitlines()
    del lines[1]  # remove one event; every hash after it is now wrong
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    evidence.digest_directory(run_dir)  # digests agree — only the chain breaks

    assert cli.main(["attest"]) == cli.EXIT_GATE_FAILED
    assert "hash chain" in capsys.readouterr().err


def test_attest_refuses_a_dry_run_verdict(project, monkeypatch, capsys):
    """Nothing was judged, so the clause would be theatre."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["judge"]) == cli.EXIT_OK  # dry run: no --send
    capsys.readouterr()

    assert cli.main(["attest"]) == cli.EXIT_GATE_FAILED
    assert "dry run" in capsys.readouterr().err


def test_attest_refuses_gates_that_did_not_pass(project, monkeypatch, capsys):
    """Law 3: no attestation dresses up a failure."""
    (project / ".wringer.yaml").write_text(
        CONFIG.replace('run: "true"', 'run: "false"'), encoding="utf-8"
    )
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    assert cli.main(["attest"]) == cli.EXIT_GATE_FAILED
    assert "did not pass" in capsys.readouterr().err


def test_attest_refuses_an_unapproved_spec(project, monkeypatch, capsys):
    """`spec_sha256` hashes the file without parsing it, so an unapproved
    spec hashes exactly like an approved one. The interlock has to be READ."""
    (project / "wringer.spec.yaml").write_text(
        "schema_version: wringer.spec.v1\napproved: false\ntitle: t\n"
        "intent: |2\n  words\ncriteria:\n  - id: c1\n    title: T\n"
        "    required: true\n    human: false\n"
        "tasks:\n  - id: t1\n    brief: briefs/t1.md\n    dir: .\n"
        "    objective: o\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["attest"]) == cli.EXIT_GATE_FAILED
    assert "approved: false" in capsys.readouterr().err


def test_attest_refuses_a_vacuous_run(project, monkeypatch, capsys):
    """The hook lands with attest, not with the feature that writes the file.
    A bundle with no `vacuity.json` is unaffected — see the control below."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    run_dir = only(project, ".wringer", "runs")
    (run_dir / "vacuity.json").write_text(
        json.dumps({"schema_version": "wringer.vacuity.v1",
                    "verdict": "gates_vacuous", "gates": []}),
        encoding="utf-8",
    )
    evidence.digest_directory(run_dir)

    assert cli.main(["attest"]) == cli.EXIT_GATE_FAILED
    err = capsys.readouterr().err
    assert "gates_vacuous" in err
    assert "test that fails without your change" in err


def test_a_proven_vacuity_verdict_attests_normally(project, monkeypatch, capsys):
    """The control for the hook above."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    run_dir = only(project, ".wringer", "runs")
    (run_dir / "vacuity.json").write_text(
        json.dumps({"schema_version": "wringer.vacuity.v1",
                    "verdict": "proven", "gates": []}),
        encoding="utf-8",
    )
    evidence.digest_directory(run_dir)

    assert cli.main(["attest"]) == cli.EXIT_OK


# --- §1a: the artifact states its own limit --------------------------------


def test_the_limits_sentence_is_in_the_artifact_and_on_the_terminal(
    project, monkeypatch, capsys
):
    """Delete the limits sentence and this fails — the spec's acceptance
    test, spelled out."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main(["attest"]) == cli.EXIT_OK
    out = capsys.readouterr().out

    assert attest.UNSIGNED_LIMIT.startswith("unsigned — this proves the named")
    assert payload_of(project)["limits"][0] == attest.UNSIGNED_LIMIT
    assert payload_of(project)["signature"] is None
    assert attest.UNSIGNED_LIMIT in out
    # `!`, doctor's mark for "worth knowing, not a problem" — never ✗
    assert f"! {attest.UNSIGNED_LIMIT}" in out
    assert "✗" not in out
    summary = (attested(project).parent / attest.SUMMARY_FILENAME).read_text("utf-8")
    assert attest.UNSIGNED_LIMIT in summary


def test_the_limits_sentence_reaches_json_for_both_commands(
    project, monkeypatch, capsys
):
    """An agent consuming this is the reader most likely to over-read a bare
    `"ok": true`."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["attest", "--json"]) == cli.EXIT_OK
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["signature"] is None
    assert attest.UNSIGNED_LIMIT in emitted["limits"]

    assert cli.main(["audit", "--json", emitted["attestation"]]) == cli.EXIT_OK
    checked = json.loads(capsys.readouterr().out)
    assert checked["ok"] is True
    assert attest.UNSIGNED_LIMIT in checked["limits"]


def test_audit_repeats_the_limit_on_success(project, monkeypatch, capsys):
    """A passing audit must not read as a stronger claim than it is."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["audit", str(attested(project))]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "✓" in out
    assert f"! {attest.UNSIGNED_LIMIT}" in out


def test_an_attestation_stripped_of_its_limits_does_not_audit(
    project, monkeypatch, capsys
):
    """Removing the sentence makes the artifact claim more than it should, so
    it stops verifying. That is what makes §1a enforceable rather than
    aspirational."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()
    path = attested(project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["limits"] = []
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    assert cli.main(["audit", str(path)]) == cli.EXIT_GATE_FAILED
    assert "does not claim" in capsys.readouterr().err


# --- §4: wring audit -------------------------------------------------------


def test_audit_passes_on_untouched_bundles(project, monkeypatch, capsys):
    verified_and_delivered(project, monkeypatch, capsys)
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["audit", str(attested(project))]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "verifies" in out


def test_flipping_one_byte_in_one_gate_log_names_that_file_and_fails(
    project, monkeypatch, capsys
):
    """**The money test.** A single byte, in a file nothing else reads back,
    long after the run — and audit names it."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()

    log = next((only(project, ".wringer", "runs") / "gates").rglob("*.log"))
    raw = bytearray(log.read_bytes() or b"x")
    raw[0] = raw[0] ^ 0x01  # one bit, in one byte
    log.write_bytes(bytes(raw))

    assert cli.main(["audit", str(attested(project))]) == cli.EXIT_GATE_FAILED
    err = capsys.readouterr().err
    assert log.name in err, err
    assert "does not match" in err


def test_audit_catches_a_file_added_to_a_bundle_after_the_fact(
    project, monkeypatch, capsys
):
    """The other direction: adding content, not changing it."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()
    (only(project, ".wringer", "runs") / "planted.txt").write_text("x\n", "utf-8")

    assert cli.main(["audit", str(attested(project))]) == cli.EXIT_GATE_FAILED
    assert "planted.txt" in capsys.readouterr().err


def test_audit_catches_a_rewritten_bundle_and_its_rewritten_digests(
    project, monkeypatch, capsys
):
    """Whoever owns the disk can rewrite a bundle AND its digests.json
    consistently — the limit the artifact states. What they cannot rewrite is
    the attestation's copy of that digest file's own sha256, so a
    self-consistent forgery still fails."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()

    run_dir = only(project, ".wringer", "runs")
    log = next((run_dir / "gates").rglob("*.log"))
    log.write_bytes(b"a completely different story\n")
    evidence.digest_directory(run_dir)  # rewrite the record to match

    assert cli.main(["audit", str(attested(project))]) == cli.EXIT_GATE_FAILED
    assert "not the one that was attested" in capsys.readouterr().err


def test_audit_catches_a_hand_edited_verdict_in_the_attestation(
    project, monkeypatch, capsys
):
    """The digests prove the BUNDLES are unaltered. This proves the
    attestation still says what they say — a forged `verdict: pass` over an
    untouched verdict.json is what a digest check alone waves through."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["judge"]) == cli.EXIT_OK
    capsys.readouterr()
    verdict_dir = only(project, ".wringer", "verdicts")
    record = verdict_dir / judge.VERDICT_FILENAME
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["mode"] = "live"
    payload["verdict"] = "fail"
    record.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    evidence.digest_directory(verdict_dir)

    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()
    path = attested(project)
    built = json.loads(path.read_text(encoding="utf-8"))
    assert built["judged_by"]["verdict"] == "fail"
    built["judged_by"]["verdict"] = "pass"  # the forgery
    path.write_text(json.dumps(built, indent=2), encoding="utf-8")

    assert cli.main(["audit", str(path)]) == cli.EXIT_GATE_FAILED
    assert "the verdict bundle records" in capsys.readouterr().err


def test_audit_needs_no_config(project, monkeypatch, capsys, tmp_path):
    """"An auditor may not have a `.wringer.yaml` and must not need one."""
    verified_and_delivered(project, monkeypatch, capsys)
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()
    path = attested(project)
    (project / ".wringer.yaml").unlink()
    monkeypatch.chdir(tmp_path)  # and from somewhere else entirely

    assert cli.main(["audit", str(path)]) == cli.EXIT_OK


# --- §1b: the signature seat ----------------------------------------------


def test_a_stray_signature_file_is_ignored_not_choked_on(
    project, monkeypatch, capsys
):
    """v1 signing must be purely additive: every v0 attestation stays valid
    byte-for-byte and audit gains a clause rather than needing a migration."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()
    path = attested(project)
    (path.parent / attest.SIGNATURE_FILENAME).write_text(
        "-----BEGIN SSH SIGNATURE-----\nnot checked in v0\n", encoding="utf-8"
    )

    assert cli.main(["audit", str(path)]) == cli.EXIT_OK


def test_v0_writes_no_signature_file(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()

    assert not (attested(project).parent / attest.SIGNATURE_FILENAME).exists()


# --- §1c: free attribution -------------------------------------------------


def test_an_unsigned_repo_records_N_and_loses_nothing(
    project, monkeypatch, capsys
):
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()

    signature = payload_of(project)["change"]["commit_signature"]
    assert signature["status"] == "N"
    assert signature["means"] == "no signature"
    assert signature["commit"]


def test_audit_reports_the_recorded_signature_without_re_verifying(
    project, monkeypatch, capsys
):
    """Re-verification would need the verifier's keyring and would put a
    network-shaped dependency on a command that must work on a plane."""
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()
    # a status this machine could not possibly have produced or checked
    path = attested(project)
    built = json.loads(path.read_text(encoding="utf-8"))
    built["change"]["commit_signature"]["status"] = "G"
    built["change"]["commit_signature"]["signer"] = "someone@example.invalid"
    path.write_text(json.dumps(built, indent=2), encoding="utf-8")

    # audit does not re-verify it, so it does not fail over it
    assert cli.main(["audit", str(path)]) == cli.EXIT_OK
    summary = attest.SIGNATURE_MEANINGS
    assert summary["G"] == "a good signature" and summary["N"] == "no signature"


def test_the_summary_says_the_signature_is_never_re_verified(
    project, monkeypatch, capsys
):
    monkeypatch.chdir(project)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()

    summary = (attested(project).parent / attest.SUMMARY_FILENAME).read_text("utf-8")
    assert "never re-verified here" in summary


# --- the structural promise ------------------------------------------------


def test_attest_never_opens_a_socket():
    """These commands prove things, so they live on the never-reaches-a-
    network side of the line the README draws. There is no `--send` here.

    Checked over the parsed IMPORTS rather than the raw text: the module
    docstring says the word "socket" while promising not to open one, and a
    substring grep would have to be satisfied by deleting the promise.
    """
    import ast

    tree = ast.parse(Path(attest.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    for forbidden in ("urllib", "socket", "requests", "http", "ssl", "ftplib"):
        assert forbidden not in imported, f"{forbidden} reached wringer/attest.py"
    # and the transport module itself, which is the one that does open one
    assert "forge" not in imported


def test_attest_defaults_to_the_newest_delivery_then_the_newest_run(
    project, monkeypatch, capsys
):
    verified_and_delivered(project, monkeypatch, capsys)
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()
    assert "delivered_as" in payload_of(project)

    # with the deliveries gone, the newest run is the anchor
    import shutil
    shutil.rmtree(project / deliver.DELIVERIES_DIRNAME)
    shutil.rmtree(project / ".wringer" / "attestations")
    assert cli.main(["attest"]) == cli.EXIT_OK
    capsys.readouterr()
    assert "delivered_as" not in payload_of(project)


def test_the_committed_pre_0_2_example_bundle_is_refused(project, monkeypatch,
                                                          capsys):
    """`.wringer.example/` is a real 0.1.0 bundle — the receipt the README
    points at — and it predates `digests.json` entirely. It is the honest
    worked example of "cannot attest what cannot be checked"."""
    example = Path(__file__).resolve().parent.parent / ".wringer.example" / "runs"
    source = sorted(example.iterdir())[0]
    assert not (source / evidence.DIGESTS_FILENAME).exists(), (
        "the committed example bundle grew a digests.json; this test now "
        "proves nothing"
    )

    import shutil
    target = project / evidence.RUNS_DIRNAME / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    monkeypatch.chdir(project)

    assert cli.main(["attest", str(target)]) == cli.EXIT_GATE_FAILED
    err = capsys.readouterr().err
    assert "cannot attest what cannot be checked" in err
    assert "digests.json" in err


def test_attest_refuses_a_really_vacuous_run_end_to_end(
    project, monkeypatch, capsys
):
    """The hook in `attest` and the file `wring verify --prove` actually
    writes, joined up — not a hand-written sibling. The two features were
    built in separate commits and this is the only test that proves they
    agree on the verdict string.
    """
    (project / ".wringer.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.chdir(project)

    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()
    recorded = json.loads(
        (only(project, ".wringer", "runs") / "vacuity.json").read_text("utf-8")
    )
    assert recorded["verdict"] == "gates_vacuous", recorded
    # the gate is `true`, which passes on any tree at all

    assert cli.main(["attest"]) == cli.EXIT_GATE_FAILED
    assert "gates_vacuous" in capsys.readouterr().err
