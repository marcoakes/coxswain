"""`wring doctor` — diagnose, never repair.

This command exists for the agent setting Wringer up for somebody. Its
contract is therefore narrow and testable: one line per question, a fix
line whenever the answer is wrong, machine-readable under --json, and an
exit code a setup script can branch on without parsing prose.
"""

from __future__ import annotations

import json
from pathlib import Path

from wringer import cli, doctor


def by_name(checks: list[doctor.Check]) -> dict[str, doctor.Check]:
    return {check.name: check for check in checks}


def test_a_healthy_repo_passes_every_blocking_check(repo, write_config):
    write_config(repo, 'version: 1\ngates:\n  - id: t\n    run: "true"\n')

    checks = doctor.run_checks(repo)

    assert all(check.passed for check in checks)
    named = by_name(checks)
    assert named["git repository"].status == doctor.OK
    assert named["gates"].status == doctor.OK
    assert named["workspace writable"].status == doctor.OK


def test_outside_a_repository_the_repo_checks_are_skipped(tmp_path):
    """Was: a blocking failure. A real first run showed that made the runbook
    stop on a false problem — `wring doctor` in a workspace directory is a
    question about the MACHINE, and "this is not a repo" does not block it."""
    checks = by_name(doctor.run_checks(tmp_path))

    assert checks["git repository"].status == doctor.SKIP
    assert checks["git repository"].scope == doctor.REPO
    assert "run from your repo" in checks["git repository"].detail
    # and nothing about the machine was skipped along with it
    assert checks["python"].scope == doctor.MACHINE
    assert checks["python"].status in (doctor.OK, doctor.FAIL)


def test_a_missing_config_is_a_warning_not_a_failure(repo):
    """A fresh clone has no gates yet. That is the next step, not a fault."""
    checks = by_name(doctor.run_checks(repo))

    assert checks["gates"].status == doctor.WARN
    assert "wring init" in checks["gates"].fix
    assert checks["gates"].passed


def test_a_broken_config_is_a_blocking_failure(repo, write_config):
    write_config(repo, "version: 99\ngates: []\n")

    checks = by_name(doctor.run_checks(repo))

    assert checks["gates"].status == doctor.FAIL


def test_an_unwritable_workspace_is_caught_early(repo, monkeypatch):
    """A read-only mount is a common container mistake, and without this
    check it surfaces much later as a confusing write error."""
    def refuse(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(Path, "mkdir", refuse)

    checks = by_name(doctor.run_checks(repo))

    assert checks["workspace writable"].status == doctor.FAIL
    assert ":ro" in checks["workspace writable"].fix


def test_the_api_key_value_is_never_printed(repo, monkeypatch):
    secret = "sk-hushhush12345"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)

    checks = doctor.run_checks(repo)
    rendered = doctor.report(checks) + doctor.as_json(checks)

    assert "ANTHROPIC_API_KEY" in rendered  # the NAME is the answer
    assert secret not in rendered           # the value never is


def test_a_missing_key_is_only_a_warning(repo, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    checks = by_name(doctor.run_checks(repo))

    assert checks["llm key"].status == doctor.WARN
    assert "never paste it to an agent" in checks["llm key"].fix


def test_json_is_machine_readable_and_complete(repo, write_config, monkeypatch,
                                               capfd):
    write_config(repo, 'version: 1\ngates:\n  - id: t\n    run: "true"\n')
    monkeypatch.chdir(repo)

    assert cli.main(["doctor", "--json"]) == cli.EXIT_OK

    payload = json.loads(capfd.readouterr().out)
    assert payload["ok"] is True
    assert payload["wringer_version"]
    names = {c["name"] for c in payload["checks"]}
    assert {"python", "git", "git repository", "gates",
            "workspace writable"} <= names
    for check in payload["checks"]:
        assert check["status"] in (doctor.OK, doctor.WARN, doctor.FAIL)


def test_the_exit_code_is_what_a_setup_script_branches_on(
    tmp_path, monkeypatch, capsys
):
    """A real blocking problem must reach the exit code — an agent should not
    have to read English to find out. Not being in a repo is not one of
    those; a missing git binary is."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(doctor.shutil, "which",
                        lambda name: None if name == "git" else "/usr/bin/x")

    assert cli.main(["doctor"]) == cli.EXIT_GATE_FAILED

    out = capsys.readouterr().out
    assert "blocking problem" in out
    assert "✗" in out


def test_the_report_offers_a_fix_for_everything_imperfect(repo):
    checks = doctor.run_checks(repo)
    rendered = doctor.report(checks)

    for check in checks:
        if check.status != doctor.OK:
            assert check.fix, f"{check.name} has no fix line"
            assert check.fix in rendered


def test_doctor_repairs_nothing(repo, monkeypatch, capsys):
    """Diagnosis and repair are different jobs. A doctor that silently
    changes the machine is one nobody can reason about."""
    monkeypatch.chdir(repo)
    before = sorted(p.name for p in repo.iterdir())

    cli.main(["doctor"])
    capsys.readouterr()

    after = sorted(p.name for p in repo.iterdir())
    # the write probe cleans up after itself; .wringer/ may be created as
    # the probe's parent, but nothing else may appear
    assert set(after) - set(before) <= {".wringer"}
    assert not (repo / "config.CONFIG_FILENAME").exists()


# --- the runbook must describe the tool that exists -----------------------
#
# A real first run on a fresh Mac (2026-08-04) found SETUP.md illustrating
# `wring doctor` output containing an image check and a platform check that
# do not exist, and `✗ api key` where the real check is a `! llm key` warn.
# The transcript had been WRITTEN rather than captured — law 8's failure mode,
# in the one document whose whole job is to be followed literally.
#
# Consequence: SETUP claimed doctor "is how every later step gets checked",
# but doctor cannot see the image pull, and exits 0 with no runtime at all.
# These tests make the documentation testable so the class cannot recur.

DOCS_WITH_DOCTOR_OUTPUT = ("SETUP.md", "QUICKSTART.md", "README.md")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def cited_check_names(text: str) -> set[str]:
    """Every check name a document illustrates in a doctor transcript.

    Scoped to fenced blocks that actually show a `wring doctor` run, because
    a prose bullet starting with "- " has the same shape as a skipped check
    and markdown is full of them.
    """
    import re

    names: set[str] = set()
    for block in re.findall(r"```[^\n]*\n(.*?)```", text, re.DOTALL):
        if "wring doctor" not in block and "doctor" not in block.split("\n")[0]:
            # a transcript of some other command
            if not re.search(r"^[✓!]\s+(python|git|wring|container runtime)\b",
                             block, re.MULTILINE):
                continue
        for line in block.splitlines():
            m = re.match(r"^([✓!✗-])\s+([a-z][a-z ]{1,28}?)\s{2,}\S", line)
            if m:
                names.add(m.group(2).strip())
    return names


def test_every_doctor_check_a_doc_illustrates_actually_exists():
    """The guard. If a document shows a check, `wring doctor` must have it."""
    real = set(doctor.check_names())
    offenders: list[str] = []
    for name in DOCS_WITH_DOCTOR_OUTPUT:
        path = repo_root() / name
        if not path.is_file():
            continue
        for cited in cited_check_names(path.read_text(encoding="utf-8")):
            if cited not in real:
                offenders.append(f"{name} illustrates '{cited}'")
    assert not offenders, (
        "documentation shows doctor checks that do not exist: "
        + "; ".join(sorted(offenders))
        + f"\nreal checks: {sorted(real)}"
    )


def test_check_names_matches_what_run_checks_emits(repo, monkeypatch):
    """`check_names()` is what the guard above trusts, so it must not drift
    from the checks actually produced."""
    monkeypatch.chdir(repo)
    emitted = [c.name for c in doctor.run_checks(repo)]
    assert sorted(emitted) == sorted(doctor.check_names())


# --- doctor outside a repository ------------------------------------------


def test_doctor_outside_a_repo_skips_repo_checks_and_exits_zero(
    tmp_path, monkeypatch, capsys
):
    """The fresh-Mac failure. The runbook says to create a workspace and then
    run doctor; doing so exited 1 on a blocking ✗ that meant only 'you are
    not in a repo', and the runbook's own stop rule then halted setup on a
    problem that did not exist."""
    monkeypatch.chdir(tmp_path)

    assert cli.main(["doctor"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    for repo_check in ("git repository", "gates", "workspace writable"):
        assert f"- {repo_check}" in out, f"{repo_check} should be skipped, not failed"
    assert "not a git repository — run from your repo" in out
    assert "This machine is ready" in out
    # the machine checks still ran and still answer
    assert "✓ python" in out
    assert "✗" not in out


def test_doctor_inside_a_repo_still_runs_every_check(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)

    assert cli.main(["doctor"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "✓ git repository" in out
    assert "- git repository" not in out
    assert "workspace writable" in out


def test_a_real_machine_failure_still_blocks(tmp_path, monkeypatch, capsys):
    """Skipping repo checks must not have made doctor unable to fail."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(doctor.shutil, "which",
                        lambda name: None if name == "git" else "/usr/bin/x")

    assert cli.main(["doctor"]) == cli.EXIT_GATE_FAILED

    assert "✗ git" in capsys.readouterr().out


def test_the_json_shape_carries_skip(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert cli.main(["doctor", "--json"]) == cli.EXIT_OK

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    statuses = {c["name"]: c["status"] for c in payload["checks"]}
    assert statuses["git repository"] == doctor.SKIP
    assert statuses["python"] == doctor.OK
