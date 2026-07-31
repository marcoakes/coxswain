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


def test_outside_a_repository_is_a_blocking_failure(tmp_path):
    checks = by_name(doctor.run_checks(tmp_path))

    assert checks["git repository"].status == doctor.FAIL
    assert "git init" in checks["git repository"].fix


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
    """Outside a repo there is a blocking problem, so doctor must say so in
    its exit code — an agent should not have to read English to find out."""
    monkeypatch.chdir(tmp_path)

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
