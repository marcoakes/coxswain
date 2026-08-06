"""`wring verify --prove` — SPEC_VACUITY_V0.md.

> **"Prove the gates can fail."** The agent wrote tautological tests, its
> gates pass, and the green tick means nothing. The counter is deterministic:
> if the gates still pass *without* the change, they never tested it.

The section that matters most here is §4b, and it is the reason this file
opens with the false-`proven` cases rather than the happy path. A detached
worktree carries **tracked files and nothing else**, so in a repo whose
dependencies are gitignored every pre-change gate fails on a missing
environment — and §1's comparison table reads that as PROOF. The feature built
to catch reward-hacking would certify it, on every run, however tautological
the tests.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from wringer import cli, config, evidence, vacuity

# A gate that genuinely tests the change: it fails without `calc.py`, which is
# untracked, so the pre-change worktree does not have it.
SENSITIVE = """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
"""

# A gate that cannot fail. The tautology this whole feature exists to catch.
TAUTOLOGY = """\
version: 1
gates:
  - id: test
    run: "true"
"""

MIXED = """\
version: 1
gates:
  - id: lint
    run: "true"
  - id: test
    run: "grep -q FIXED calc.py"
"""


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=cwd, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def latest_run(root: Path) -> Path:
    """The newest run — via the repo's own ordering, not by sorting names.

    Sorting the directory names looks right and is not: within one second a
    run id ends in a RANDOM suffix rather than a counter, so `sorted()[-1]`
    picks arbitrarily between two runs from the same second. Two verifies in
    the same second is not a corner case here — it is what every test in this
    file that runs `verify` twice does.
    """
    found = evidence.latest_run(root / evidence.RUNS_DIRNAME)
    assert found is not None
    return found


def verdict_of(root: Path) -> dict:
    return json.loads(
        (latest_run(root) / vacuity.VACUITY_FILENAME).read_text(encoding="utf-8")
    )


@pytest.fixture
def changed(repo: Path) -> Path:
    """A repo with one committed file and one uncommitted change to prove."""
    (repo / "README.md").write_text("a project\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "initial")
    (repo / "calc.py").write_text("FIXED\n", encoding="utf-8")
    return repo


# --- §7: the acceptance checklist, in order --------------------------------


def test_a_planted_tautology_yields_gates_vacuous(changed, monkeypatch, capsys):
    """`assert True`, in shell form. The gate passes on both trees, so it
    proved nothing about the change."""
    (changed / ".wringer.yaml").write_text(TAUTOLOGY, encoding="utf-8")
    monkeypatch.chdir(changed)

    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()

    recorded = verdict_of(changed)
    assert recorded["verdict"] == vacuity.GATES_VACUOUS
    assert recorded["gates"][0]["sensitive"] is False
    assert recorded["gates"][0]["changed"] == "passed"
    assert recorded["gates"][0]["pre_change"] == "passed"


def test_a_real_test_yields_proven(changed, monkeypatch, capsys):
    """The gate reads a file the pre-change tree does not have, so it fails
    there. That is what proof looks like."""
    (changed / ".wringer.yaml").write_text(SENSITIVE, encoding="utf-8")
    monkeypatch.chdir(changed)

    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()

    recorded = verdict_of(changed)
    assert recorded["verdict"] == vacuity.PROVEN
    assert recorded["gates"][0]["sensitive"] is True


def test_a_mixed_set_reports_per_gate_and_proves_as_a_whole(
    changed, monkeypatch, capsys
):
    """"A lint gate passing on both trees is ordinary." Only EVERY gate
    passing on both is the signal."""
    (changed / ".wringer.yaml").write_text(MIXED, encoding="utf-8")
    monkeypatch.chdir(changed)

    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()

    recorded = verdict_of(changed)
    assert recorded["verdict"] == vacuity.PROVEN
    rows = {row["gate_id"]: row for row in recorded["gates"]}
    assert rows["lint"]["sensitive"] is False
    assert rows["test"]["sensitive"] is True


def test_a_failed_normal_run_never_triggers_the_prove_pass(
    changed, monkeypatch, capsys
):
    """There is nothing to prove about a failure — law 3's shape. The pass
    does not run, and the verdict says why rather than staying silent."""
    (changed / ".wringer.yaml").write_text(
        'version: 1\ngates:\n  - id: test\n    run: "false"\n', encoding="utf-8"
    )
    monkeypatch.chdir(changed)

    assert cli.main(["verify", "--prove"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    recorded = verdict_of(changed)
    assert recorded["verdict"] == vacuity.NOT_APPLICABLE
    assert recorded["gates"] == []
    assert not (latest_run(changed) / vacuity.VACUITY_DIRNAME).exists(), (
        "the prove pass ran anyway and left logs"
    )


def test_an_unchanged_tree_is_not_applicable(repo, monkeypatch, capsys):
    """Nothing to be vacuous about."""
    (repo / ".wringer.yaml").write_text(TAUTOLOGY, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "config")
    monkeypatch.chdir(repo)

    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()

    assert verdict_of(repo)["verdict"] == vacuity.NOT_APPLICABLE


# --- §4b: THE MONEY TEST ---------------------------------------------------


def test_gitignored_dependencies_and_a_tautology_must_not_report_proven(
    repo, monkeypatch, capsys
):
    """**The false `proven`.** A repo whose dependencies are gitignored, with
    a completely tautological test.

    The scratch worktree has no `vendor/`, because it is gitignored, so the
    gate fails there — on a missing environment, not on the change. §1's table
    reads *pass on changed, fail on pre-change* and would conclude "the gate
    tests this change". It does not: the gate is `test -f vendor/lib.py`,
    which says nothing whatever about the change.

    Wringer cannot tell the difference automatically and does not try. What it
    must do — and what this test enforces — is make the failure VISIBLE, so
    the row is legible as a broken environment rather than convincing as a
    caught regression.
    """
    (repo / ".gitignore").write_text("vendor/\n.wringer/\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        'version: 1\ngates:\n  - id: test\n    run: "cat vendor/lib.py"\n',
        encoding="utf-8",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "config")
    # the dependency: present here, gitignored, so absent from any worktree
    (repo / "vendor").mkdir()
    (repo / "vendor" / "lib.py").write_text("installed\n", encoding="utf-8")
    (repo / "feature.py").write_text("the actual change\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()

    recorded = verdict_of(repo)
    row = recorded["gates"][0]
    assert row["sensitive"] is True  # the trap: this LOOKS like proof
    assert row["cites"], (
        "a `sensitive` row must cite the failure it rests on — without it a "
        "missing environment is indistinguishable from a caught regression"
    )
    assert "vendor/lib.py" in row["cites"], row["cites"]
    # and the reader is shown it, in the file a human actually opens
    report = (latest_run(repo) / evidence.SUMMARY_FILENAME).read_text("utf-8")
    assert "vendor/lib.py" in report, report


def test_a_failing_prove_setup_is_inconclusive_never_proven(
    changed, monkeypatch, capsys
):
    """"If it fails, the verdict is `inconclusive` — never `proven`, and never
    silently dropped." """
    (changed / ".wringer.yaml").write_text(
        SENSITIVE + 'run:\n  worker: "true"\n  prove_setup: "exit 7"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(changed)

    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()

    recorded = verdict_of(changed)
    assert recorded["verdict"] == vacuity.INCONCLUSIVE
    assert recorded["setup"]["ok"] is False
    assert recorded["setup"]["exit_code"] == 7
    assert "prove_setup" in recorded["reason"]


def test_prove_setup_runs_in_the_worktree_and_makes_proof_honest(
    repo, monkeypatch, capsys
):
    """The other half of §4b: with the setup command declared, the pre-change
    environment is real, so a tautological gate is correctly reported as
    proving nothing."""
    (repo / ".gitignore").write_text("vendor/\n.wringer/\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        'version: 1\ngates:\n  - id: test\n    run: "cat vendor/lib.py"\n'
        'run:\n  worker: "true"\n'
        '  prove_setup: "mkdir -p vendor && echo installed > vendor/lib.py"\n',
        encoding="utf-8",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "config")
    (repo / "vendor").mkdir()
    (repo / "vendor" / "lib.py").write_text("installed\n", encoding="utf-8")
    (repo / "feature.py").write_text("the actual change\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()

    recorded = verdict_of(repo)
    assert recorded["setup"]["ok"] is True
    assert recorded["verdict"] == vacuity.GATES_VACUOUS, (
        "with the environment restored the gate passes on both trees, which "
        "is the truth: it never tested the change"
    )


# --- §3a: config declares, flags may only tighten --------------------------


def test_run_prove_true_makes_every_run_prove(changed, monkeypatch, capsys):
    (changed / ".wringer.yaml").write_text(
        TAUTOLOGY + 'run:\n  worker: "true"\n  prove: true\n', encoding="utf-8"
    )
    monkeypatch.chdir(changed)

    assert cli.main(["verify"]) == cli.EXIT_OK  # no flag at all
    capsys.readouterr()

    assert verdict_of(changed)["verdict"] == vacuity.GATES_VACUOUS


def test_the_flag_proves_once_against_a_config_that_says_nothing(
    changed, monkeypatch, capsys
):
    (changed / ".wringer.yaml").write_text(TAUTOLOGY, encoding="utf-8")
    monkeypatch.chdir(changed)

    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    assert not (latest_run(changed) / vacuity.VACUITY_FILENAME).exists()

    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()
    assert (latest_run(changed) / vacuity.VACUITY_FILENAME).is_file()


def test_no_prove_is_not_a_flag_and_wring_run_exits_2(changed, monkeypatch,
                                                       capsys):
    """"--no-prove does not exist, deliberately." Not silently ignored —
    argparse rejects it, which is exit 2."""
    (changed / ".wringer.yaml").write_text(
        TAUTOLOGY + 'run:\n  worker: "true"\n  prove: true\n', encoding="utf-8"
    )
    monkeypatch.chdir(changed)

    with pytest.raises(SystemExit) as exited:
        cli.main(["run", "--no-prove"])
    assert exited.value.code == 2
    with pytest.raises(SystemExit) as exited:
        cli.main(["verify", "--no-prove"])
    assert exited.value.code == 2


def test_nothing_can_turn_off_what_the_repo_declared(changed, monkeypatch,
                                                      capsys):
    """**The test that matters**, mirroring the one that guards `approved:
    false`. No flag and no environment variable may loosen `run.prove: true`.

    Checked two ways. Behaviourally: every documented flag on `verify`, plus a
    spread of plausible environment variables somebody might reach for, and
    the run still proves. Structurally: `wants_prove` is an `or` over the
    declaration, so there is no expression through which False could win.
    """
    from wringer import verify

    (changed / ".wringer.yaml").write_text(
        TAUTOLOGY + 'run:\n  worker: "true"\n  prove: true\n', encoding="utf-8"
    )
    monkeypatch.chdir(changed)
    for name in (
        "WRINGER_PROVE", "WRINGER_NO_PROVE", "NO_PROVE", "WRING_PROVE",
        "WRINGER_SKIP_PROVE", "CI",
    ):
        monkeypatch.setenv(name, "0")
    monkeypatch.setenv("WRINGER_PROVE", "false")

    assert cli.main(["verify", "--json"]) == cli.EXIT_OK
    capsys.readouterr()
    assert (latest_run(changed) / vacuity.VACUITY_FILENAME).is_file(), (
        "an environment variable turned off what the repository declared"
    )

    # and the rule itself: declared or flag, never declared-and-flag
    loaded = config.load(changed / ".wringer.yaml")
    assert verify.wants_prove(loaded, flag=False) is True
    assert verify.wants_prove(loaded, flag=True) is True


def test_verify_prints_no_warning_when_vacuity_was_not_checked(
    changed, monkeypatch, capsys
):
    """"A warning nobody can act on is one everybody learns to skip." The
    placeholder warning is tolerable because it disappears when you fix it;
    this one would never disappear unless you accept doubled gate time."""
    (changed / ".wringer.yaml").write_text(SENSITIVE, encoding="utf-8")
    monkeypatch.chdir(changed)

    assert cli.main(["verify"]) == cli.EXIT_OK
    captured = capsys.readouterr()

    for noise in ("vacuit", "--prove", "prove"):
        assert noise not in captured.out.lower(), captured.out
        assert noise not in captured.err.lower(), captured.err


def test_the_init_template_names_run_prove_in_a_commented_block(
    repo, monkeypatch, capsys
):
    """"A config-only setting nobody knows about is a setting nobody uses."""
    monkeypatch.chdir(repo)
    assert cli.main(["init"]) == cli.EXIT_OK
    capsys.readouterr()

    written = (repo / config.CONFIG_FILENAME).read_text(encoding="utf-8")
    assert "#   prove: true" in written, written
    assert "prove_setup" in written
    # commented, so `wring init` does not silently double everyone's gate time
    loaded = config.load(repo / config.CONFIG_FILENAME)
    assert loaded.run is None or loaded.run.prove is False


# --- §3b: deliver refuses a vacuous run ------------------------------------


DELIVERY_CONFIG = """\
forge:
  kind: github
  endpoint: https://api.github.com
  repo: owner/name
  token_env: FORGE_TOKEN
deliver:
  branch: "wringer/{run}"
  base: main
  remote: origin
"""


@pytest.fixture
def deliverable(changed: Path) -> Path:
    upstream = changed.parent / f"{changed.name}-vac-upstream.git"
    git(changed, "init", "--bare", "-b", "main", str(upstream))
    git(changed, "remote", "add", "origin", f"file://{upstream}")
    (changed / ".gitignore").write_text(".wringer/\n", encoding="utf-8")
    # `.gitignore` ONLY. `git add -A` here would commit `calc.py`, which is the
    # change being proven — the pre-change tree would then contain it and
    # every gate would read as insensitive for the wrong reason.
    git(changed, "add", ".gitignore")
    git(changed, "commit", "-qm", "ignore")
    git(changed, "push", "-q", "-u", "origin", "main")
    return changed


def test_a_vacuous_bundle_is_refused_by_deliver(deliverable, monkeypatch,
                                                 capsys):
    (deliverable / ".wringer.yaml").write_text(
        TAUTOLOGY + DELIVERY_CONFIG, encoding="utf-8"
    )
    monkeypatch.chdir(deliverable)
    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()
    assert verdict_of(deliverable)["verdict"] == vacuity.GATES_VACUOUS

    assert cli.main(["deliver"]) == cli.EXIT_GATE_FAILED
    message = capsys.readouterr().err

    assert "gates_vacuous" in message
    assert "`test`" in message, "the refusal must name the insensitive gates"
    assert "write a test that fails without your change" in message
    assert vacuity.VACUITY_DIRNAME in message, "and where to look"


def test_a_bundle_with_no_vacuity_json_delivers_exactly_as_today(
    deliverable, monkeypatch, capsys
):
    """"The refusal attaches to the bundle, not to the user or the flag." No
    repo that has not opted in changes behaviour."""
    (deliverable / ".wringer.yaml").write_text(
        TAUTOLOGY + DELIVERY_CONFIG, encoding="utf-8"
    )
    monkeypatch.chdir(deliverable)
    assert cli.main(["verify"]) == cli.EXIT_OK  # no --prove
    capsys.readouterr()
    assert not (latest_run(deliverable) / vacuity.VACUITY_FILENAME).exists()

    assert cli.main(["deliver"]) == cli.EXIT_OK


def test_a_proven_bundle_delivers(deliverable, monkeypatch, capsys):
    (deliverable / ".wringer.yaml").write_text(
        SENSITIVE + DELIVERY_CONFIG, encoding="utf-8"
    )
    monkeypatch.chdir(deliverable)
    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()
    assert verdict_of(deliverable)["verdict"] == vacuity.PROVEN

    assert cli.main(["deliver"]) == cli.EXIT_OK


def test_allow_vacuous_is_not_a_flag(deliverable, monkeypatch, capsys):
    """"There is no `--allow-vacuous`, and that is not an oversight." Ruling 1
    banned loosening flags; this would be the first counter-example one
    section later in the same spec."""
    monkeypatch.chdir(deliverable)
    with pytest.raises(SystemExit) as exited:
        cli.main(["deliver", "--allow-vacuous"])
    assert exited.value.code == 2

    # And no such option is registered anywhere in the CLI. Checked over the
    # parser rather than by grepping the source: `deliver.py` says the words
    # "--allow-vacuous" while explaining why there is no such flag, and a
    # substring grep could only be satisfied by deleting the explanation.
    parser = cli.build_parser()
    registered = {
        option
        for action in _all_actions(parser)
        for option in action.option_strings
    }
    assert not {opt for opt in registered if "vacu" in opt}, sorted(registered)


def _all_actions(parser):
    import argparse

    yield from parser._actions
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                yield from sub._actions


# --- §4a: measured, never capped -------------------------------------------


def test_the_verdict_records_what_the_pass_cost(changed, monkeypatch, capsys):
    (changed / ".wringer.yaml").write_text(SENSITIVE, encoding="utf-8")
    monkeypatch.chdir(changed)
    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()

    recorded = verdict_of(changed)
    assert isinstance(recorded["worktree_ms"], int)
    assert isinstance(recorded["prove_ms"], int)
    assert recorded["worktree_ms"] >= 0 and recorded["prove_ms"] >= 0


def test_no_ceiling_key_exists_anywhere_in_the_config():
    """"Every answer to 'what happens when you hit it' is worse than the
    cost." Skipping the pass re-introduces the vacuity this feature exists to
    catch, which is the single worst outcome available in the spec."""
    source = Path(config.__file__).read_text(encoding="utf-8")
    for banned in (
        "prove_timeout", "prove_ceiling", "max_prove", "prove_limit",
        "prove_budget",
    ):
        assert banned not in source, f"a ceiling key crept in: {banned}"


# --- the worktree, and the bundle ------------------------------------------


def test_the_scratch_worktree_is_gone_afterwards(changed, monkeypatch, capsys):
    (changed / ".wringer.yaml").write_text(SENSITIVE, encoding="utf-8")
    monkeypatch.chdir(changed)
    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()

    listed = git(changed, "worktree", "list")
    assert "prove" not in listed, listed
    assert not (changed / ".wringer" / "worktrees" / "prove").exists()


def test_the_scratch_worktree_is_gone_after_a_failing_gate_too(
    changed, monkeypatch, capsys
):
    """"pass or fail or Ctrl-C". A gate that fails in the worktree is the
    NORMAL case — it is what proof looks like — so cleanup cannot depend on
    the pre-change gates succeeding."""
    (changed / ".wringer.yaml").write_text(SENSITIVE, encoding="utf-8")
    monkeypatch.chdir(changed)
    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()
    assert verdict_of(changed)["gates"][0]["pre_change"] == "failed"

    assert "prove" not in git(changed, "worktree", "list")


def test_digests_cover_the_verdict_and_the_pre_change_logs(
    changed, monkeypatch, capsys
):
    """`digests.json` still writes LAST, after `vacuity.json`, so the
    bundle's own tamper-evidence covers the vacuity evidence too."""
    (changed / ".wringer.yaml").write_text(SENSITIVE, encoding="utf-8")
    monkeypatch.chdir(changed)
    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()

    run_dir = latest_run(changed)
    recorded = json.loads(
        (run_dir / evidence.DIGESTS_FILENAME).read_text(encoding="utf-8")
    )
    assert vacuity.VACUITY_FILENAME in recorded["files"]
    logs = [
        name for name in recorded["files"]
        if name.startswith(f"{vacuity.VACUITY_DIRNAME}/")
    ]
    assert logs, sorted(recorded["files"])


def test_the_pre_change_logs_are_kept_as_evidence(changed, monkeypatch, capsys):
    """"the pre-change gate logs kept under `vacuity/` in the bundle —
    evidence, not summary." A reader who doubts a row can read both trees."""
    (changed / ".wringer.yaml").write_text(SENSITIVE, encoding="utf-8")
    monkeypatch.chdir(changed)
    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()

    run_dir = latest_run(changed)
    row = verdict_of(changed)["gates"][0]
    assert (run_dir / row["pre_change_log"]).is_file()


def test_an_optional_gate_is_not_proved(changed, monkeypatch, capsys):
    """"proving *optional* gates" is a non-goal: they do not decide
    outcomes, so their sensitivity cannot change what a green tick means."""
    (changed / ".wringer.yaml").write_text(
        'version: 1\ngates:\n  - id: lint\n    run: "true"\n'
        '    optional: true\n  - id: test\n    run: "grep -q FIXED calc.py"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(changed)
    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()

    rows = verdict_of(changed)["gates"]
    assert [row["gate_id"] for row in rows] == ["test"]


def test_the_loop_proves_when_the_repo_declared_it(repo, monkeypatch, capsys):
    """"The loop, when the repo opts in." Every iteration's verify proves."""
    (repo / ".gitignore").write_text(".wringer/\n", encoding="utf-8")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "initial")
    (repo / ".wringer.yaml").write_text(
        'version: 1\ngates:\n  - id: test\n    run: "grep -q FIXED calc.py"\n'
        'run:\n  worker: "echo FIXED > calc.py"\n  max_iterations: 3\n'
        "  prove: true\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_OK
    capsys.readouterr()

    proved = [
        run_dir for run_dir in sorted((repo / evidence.RUNS_DIRNAME).iterdir())
        if (run_dir / vacuity.VACUITY_FILENAME).is_file()
    ]
    assert proved, "the loop ran without proving anything"


# --- the honest limit, pinned so nobody rediscovers it in the field --------


def test_prove_cannot_see_a_neutered_failing_test(repo, monkeypatch, capsys):
    """**The limit, recorded as a test rather than as a hope.**

    The pre-change tree is HEAD, so a gate fails there when HEAD was already
    red. That is the loop's own shape and it is what makes `proven` meaningful
    — but it also means an agent that DELETES the failing test gets `proven`,
    for the wrong reason: the gate really did fail at HEAD.

    Catching this needs the new tests applied to the old source, which is
    reverse-patching, which SPEC_VACUITY_V0 §1 rules out by name. So the
    behaviour below is correct-per-spec and is a real limit, and this test
    exists so that stays a written-down fact instead of a field report.
    """
    (repo / ".gitignore").write_text(".wringer/\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        'version: 1\ngates:\n  - id: test\n    run: "sh check.sh"\n',
        encoding="utf-8",
    )
    # HEAD is red: the check asserts something untrue of the code.
    (repo / "check.sh").write_text("grep -q CORRECT value.txt\n", encoding="utf-8")
    (repo / "value.txt").write_text("WRONG\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "a failing check")
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    # the agent "fixes" it by neutering the check rather than the value
    (repo / "check.sh").write_text("true\n", encoding="utf-8")
    assert cli.main(["verify", "--prove"]) == cli.EXIT_OK
    capsys.readouterr()

    recorded = verdict_of(repo)
    assert recorded["verdict"] == vacuity.PROVEN, (
        "if this ever becomes gates_vacuous, the limit has been closed and "
        "docs/prove-the-gates-can-fail.md's last section should say so"
    )
    # and the citation is what a reader has to catch it with
    assert recorded["gates"][0]["cites"]


def test_the_scratch_worktree_is_gone_after_a_ctrl_c(changed, monkeypatch,
                                                      capsys):
    """"pass or fail or Ctrl-C." The third one, which the other two tests
    cannot reach: a KeyboardInterrupt during the pre-change gates must still
    leave the checkout removed, or an interrupted prove pass accumulates
    worktrees until a human notices."""
    from wringer import gates

    (changed / ".wringer.yaml").write_text(SENSITIVE, encoding="utf-8")
    monkeypatch.chdir(changed)

    real = gates.run
    seen: list[str] = []

    def interrupt_the_prove_pass(gate, cwd, *args, **kwargs):
        # the pre-change run is the one in the scratch worktree
        if ".wringer/worktrees" in str(cwd):
            seen.append(gate.id)
            raise KeyboardInterrupt
        return real(gate, cwd, *args, **kwargs)

    monkeypatch.setattr(gates, "run", interrupt_the_prove_pass)

    # the CLI turns Ctrl-C into exit 4 rather than a traceback, so the
    # interrupt is observed there
    assert cli.main(["verify", "--prove"]) == cli.EXIT_INTERRUPTED
    capsys.readouterr()

    assert seen, "the prove pass never reached the worktree"
    assert "prove" not in git(changed, "worktree", "list")
    assert not (changed / ".wringer" / "worktrees").exists() or not list(
        (changed / ".wringer" / "worktrees").iterdir()
    )


def test_the_pre_change_gate_logs_are_redacted_like_every_other_bundle_file(
    repo, write_config, monkeypatch, capsys
):
    """`--prove` runs the gates a second time, in a scratch worktree, and
    writes their output INTO the run bundle — through `gates.run` with no
    redactor at all, so the default `*TOKEN*`/`*SECRET*`/`*KEY*` patterns did
    not apply either. SECURITY.md and AGENTS.md both say redaction happens
    before the write and that every bundle file goes through the Bundle's
    redactor. These did not."""
    secret = "notarealtoken-6b1f09c7d2e4a583"
    monkeypatch.setenv("WRINGER_PROVE_TOKEN", secret)
    write_config(
        repo,
        'version: 1\n'
        'gates:\n'
        '  - id: leaky\n'
        '    run: "echo $WRINGER_PROVE_TOKEN"\n'
        'run:\n'
        '  worker: "true"\n'
        '  prove: true\n',
    )
    (repo / "change.txt").write_text("a change to prove something about\n", "utf-8")
    monkeypatch.chdir(repo)

    cli.main(["verify"])
    capsys.readouterr()

    hits = [
        path.relative_to(repo).as_posix()
        for path in (repo / ".wringer").rglob("*")
        if path.is_file()
        and secret in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert hits == [], f"the pre-change gate logs carried a live secret: {hits}"
