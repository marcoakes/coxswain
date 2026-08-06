"""`wring get`, `wring issue`, `wring deliver` (SPEC_GET_V0.md).

**No test here opens a socket and none needs a token.** The forge transport is
one function, and faking it is the difference between a suite that runs
anywhere and one that needs a GitHub account. Clones and pushes use `file://`
remotes, which is a real git push to a real repository — just not a remote one.

Most of this file is about what `wring deliver` refuses. It is the only code
in Wringer that writes git history, and SPEC_GET_V0.md §1 buys that power with
five conditions; each one has a test that fails without it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from wringer import acquire, cli, config, deliver, evidence, forge

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
"""

ISSUE_REPLY = {
    "number": 42,
    "title": "CSV export for the reports page",
    "body": "Finance keeps asking for the numbers in a spreadsheet.",
    "user": {"login": "aperson"},
    "state": "open",
    "html_url": "https://github.com/owner/name/issues/42",
}

MR_REPLY = {"number": 7, "html_url": "https://github.com/owner/name/pull/7"}


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=cwd, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def fake_forge(monkeypatch, reply=None, fail=None):
    """Stand in for the second (and last) function that opens a socket."""
    calls: list[dict] = []

    def fake_request(url, method, sent_headers, body, timeout):
        calls.append(
            {"url": url, "method": method, "headers": sent_headers, "body": body}
        )
        if fail is not None:
            raise forge.ForgeError(fail)
        return reply(len(calls)) if callable(reply) else reply

    monkeypatch.setattr(forge, "request", fake_request)
    return calls


@pytest.fixture
def delivery_repo(repo: Path) -> Path:
    """A repo with a `file://` origin, a passing run, and a change to ship."""
    # Named after this test's own tmp dir: `repo.parent` is shared across the
    # session, and a bare repo reused between tests takes the first one's
    # history and then rejects everyone else's push as non-fast-forward.
    upstream = repo.parent / f"{repo.name}-upstream.git"
    git(repo, "init", "--bare", "-b", "main", str(upstream))
    git(repo, "remote", "add", "origin", f"file://{upstream}")
    (repo / ".wringer.yaml").write_text(CONFIG, encoding="utf-8")
    # As `wring init` would: evidence stays local, and an un-ignored .wringer/
    # would make every tree permanently dirty.
    (repo / ".gitignore").write_text(".wringer/\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "config")
    git(repo, "push", "-u", "origin", "main")
    (repo / "feature.py").write_text("def added():\n    return 1\n", encoding="utf-8")
    return repo


def verified(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()


# --- wring get -----------------------------------------------------------


def test_get_clones_and_records_where_it_came_from(repo, monkeypatch, capsys):
    source = repo.parent / "source"
    source.mkdir()
    git(source, "init", "-q", "-b", "main", ".")
    (source / "hello.txt").write_text("hi\n", encoding="utf-8")
    git(source, "add", "-A")
    git(source, "commit", "-m", "first")
    (repo / ".wringer.yaml").write_text(
        CONFIG + "workspace: work\n", encoding="utf-8"
    )
    monkeypatch.chdir(repo)

    assert cli.main(["get", f"file://{source}"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "Cloned" in out and "Nothing in it has been run" in out
    assert (repo / "work" / "source" / "hello.txt").is_file()

    recorded = sorted((repo / acquire.ACQUIRED_DIRNAME).glob("*/manifest.json"))
    assert len(recorded) == 1
    manifest = json.loads(recorded[0].read_text(encoding="utf-8"))
    assert manifest["schema_version"] == acquire.SCHEMA_VERSION
    assert manifest["origin"].endswith(str(source))
    assert len(manifest["head_sha"]) == 40


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://u:p@example.com/x.git", "must not carry a password"),
        ("https://ghp_tokentoken@example.com/x.git", "username over http(s)"),
        ("ftp://example.com/x.git", "not a scheme"),
        ("ext::sh -c whoami", "not a scheme"),
    ],
)
def test_get_refuses_a_url_it_should_not_clone(repo, monkeypatch, capsys, url,
                                                expected):
    (repo / ".wringer.yaml").write_text(CONFIG + "workspace: work\n", "utf-8")
    monkeypatch.chdir(repo)

    assert cli.main(["get", url]) == cli.EXIT_CONFIG

    assert expected in capsys.readouterr().err


def test_get_refuses_to_clone_over_someones_work(repo, monkeypatch, capsys):
    (repo / ".wringer.yaml").write_text(CONFIG + "workspace: work\n", "utf-8")
    (repo / "work" / "source").mkdir(parents=True)
    (repo / "work" / "source" / "mine.txt").write_text("mine\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    assert cli.main(["get", "file:///nowhere/source"]) == cli.EXIT_CONFIG

    assert "not empty" in capsys.readouterr().err
    assert (repo / "work" / "source" / "mine.txt").is_file()


def test_get_without_a_workspace_refuses_to_choose(repo, monkeypatch, capsys):
    (repo / ".wringer.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.chdir(repo)

    assert cli.main(["get", "file:///x"]) == cli.EXIT_CONFIG

    assert "does not choose where to put your code" in capsys.readouterr().err


# --- wring issue ---------------------------------------------------------


def test_issue_writes_a_file_a_human_reads(repo, monkeypatch, capsys):
    (repo / ".wringer.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.setenv("FORGE_TOKEN", "ghp_secretsecret123")
    monkeypatch.chdir(repo)
    calls = fake_forge(monkeypatch, reply=ISSUE_REPLY)

    assert cli.main(["issue", "42"]) == cli.EXIT_OK

    written = (repo / "issues" / "42.md").read_text(encoding="utf-8")
    assert forge.ISSUE_MARKER in written
    assert "# CSV export for the reports page" in written
    assert "Finance keeps asking" in written
    assert "author: aperson" in written
    # the token reaches the transport and no artifact
    assert calls[0]["headers"]["Authorization"] == "Bearer ghp_secretsecret123"
    assert "ghp_secretsecret123" not in written
    assert "wring spec issues/42.md" in capsys.readouterr().out


def test_issue_refuses_a_url_for_a_different_repo(repo, monkeypatch, capsys):
    """Fetching from somewhere the repo never declared is the same mistake as
    contacting an endpoint it never declared."""
    (repo / ".wringer.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.setenv("FORGE_TOKEN", "t123456")
    monkeypatch.chdir(repo)
    fake_forge(monkeypatch, reply=ISSUE_REPLY)

    assert cli.main(
        ["issue", "https://github.com/someone/else/issues/9"]
    ) == cli.EXIT_CONFIG

    assert "'forge.repo' declares" in capsys.readouterr().err
    assert not (repo / "issues").exists()


def test_issue_will_not_overwrite_a_file_a_person_wrote(repo, monkeypatch,
                                                         capsys):
    (repo / ".wringer.yaml").write_text(CONFIG, encoding="utf-8")
    (repo / "issues").mkdir()
    (repo / "issues" / "42.md").write_text("my own notes\n", encoding="utf-8")
    monkeypatch.setenv("FORGE_TOKEN", "t123456")
    monkeypatch.chdir(repo)
    fake_forge(monkeypatch, reply=ISSUE_REPLY)

    assert cli.main(["issue", "42"]) == cli.EXIT_CONFIG

    assert "did not write it" in capsys.readouterr().err
    assert (repo / "issues" / "42.md").read_text("utf-8") == "my own notes\n"


def test_a_repo_without_a_forge_section_cannot_reach_one(repo, monkeypatch,
                                                          capsys):
    (repo / ".wringer.yaml").write_text(
        'version: 1\ngates:\n  - id: c\n    run: "true"\n', encoding="utf-8"
    )
    monkeypatch.chdir(repo)

    assert cli.main(["issue", "1"]) == cli.EXIT_CONFIG

    assert "no default host and never will be" in capsys.readouterr().err


def test_the_gitlab_mapping_speaks_gitlab(monkeypatch):
    """Vendor strings live in one file; this is the check that it holds two
    dialects rather than one with a flag."""
    from wringer import config

    gitlab = config.Forge(
        kind="gitlab", endpoint="https://gitlab.com", repo="group/proj",
        token_env=None,
    )
    assert forge.headers(gitlab, "tok")["PRIVATE-TOKEN"] == "tok"
    assert forge.issue_number(
        "https://gitlab.com/group/proj/-/issues/13", gitlab
    ) == 13


# --- wring deliver: the dry run ------------------------------------------


def test_deliver_dry_run_writes_everything_and_touches_git_not_at_all(
    delivery_repo, monkeypatch, capsys
):
    verified(delivery_repo, monkeypatch, capsys)
    before = git(delivery_repo, "rev-parse", "HEAD")

    assert cli.main(["deliver"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "dry run — nothing was written to git" in out
    written = sorted((delivery_repo / deliver.DELIVERIES_DIRNAME).iterdir())[0]
    for name in (deliver.PATCH_FILENAME, deliver.COMMIT_FILENAME,
                 deliver.BRANCH_FILENAME, deliver.MR_FILENAME,
                 deliver.COMMANDS_FILENAME):
        assert (written / name).is_file(), name
    # git is exactly where it was: same commit, same branch, no new branches
    assert git(delivery_repo, "rev-parse", "HEAD") == before
    assert git(delivery_repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(delivery_repo, "branch", "--list").strip() == "* main"


def test_the_mr_body_carries_receipts_but_never_gate_logs(
    delivery_repo, monkeypatch, capsys
):
    """A bundle may hold whatever a gate printed (SECURITY.md); an MR body is
    public. The gate TABLE travels; the logs do not."""
    (delivery_repo / ".wringer.yaml").write_text(
        CONFIG.replace('run: "true"', 'run: "echo SECRET-GATE-CHATTER"'),
        encoding="utf-8",
    )
    verified(delivery_repo, monkeypatch, capsys)

    assert cli.main(["deliver"]) == cli.EXIT_OK
    capsys.readouterr()

    body = (
        sorted((delivery_repo / deliver.DELIVERIES_DIRNAME).iterdir())[0]
        / deliver.MR_FILENAME
    ).read_text(encoding="utf-8")
    assert "| check | passed |" in body
    assert "SECRET-GATE-CHATTER" not in body
    assert "deliberately not reproduced here" in body


# --- wring deliver: §1's five conditions ---------------------------------


def test_an_unverified_change_gets_no_branch(delivery_repo, monkeypatch,
                                              capsys):
    (delivery_repo / ".wringer.yaml").write_text(
        CONFIG.replace('run: "true"', 'run: "false"'), encoding="utf-8"
    )
    monkeypatch.chdir(delivery_repo)
    assert cli.main(["verify"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    assert cli.main(["deliver"]) == cli.EXIT_GATE_FAILED

    assert "gates did not pass" in capsys.readouterr().err
    assert not (delivery_repo / deliver.DELIVERIES_DIRNAME).exists()


def test_a_clean_tree_has_nothing_to_deliver(delivery_repo, monkeypatch,
                                              capsys):
    (delivery_repo / "feature.py").unlink()
    verified(delivery_repo, monkeypatch, capsys)

    assert cli.main(["deliver"]) == cli.EXIT_GATE_FAILED

    assert "nothing to deliver" in capsys.readouterr().err


def test_an_existing_branch_is_never_checked_out(delivery_repo, monkeypatch,
                                                  capsys):
    """Condition 1: only a branch Wringer created."""
    verified(delivery_repo, monkeypatch, capsys)
    assert cli.main(["deliver", "--json"]) == cli.EXIT_OK
    planned = json.loads(capsys.readouterr().out)["branch"]
    git(delivery_repo, "branch", planned)

    assert cli.main(["deliver"]) == cli.EXIT_REFUSED

    assert "already exists" in capsys.readouterr().err


def test_the_base_branch_is_never_the_target(delivery_repo, monkeypatch,
                                              capsys):
    """Condition 2: never the default branch."""
    (delivery_repo / ".wringer.yaml").write_text(
        CONFIG.replace('branch: "wringer/{run}"', 'branch: "main"'),
        encoding="utf-8",
    )
    verified(delivery_repo, monkeypatch, capsys)

    assert cli.main(["deliver"]) == cli.EXIT_REFUSED

    err = capsys.readouterr().err
    assert "which is the base branch" in err


def test_an_unresolvable_default_branch_is_a_refusal_not_a_guess(
    delivery_repo, monkeypatch, capsys
):
    """Condition 2, the other half: a branch you could not name is not one you
    can be sure you avoided."""
    (delivery_repo / ".wringer.yaml").write_text(
        CONFIG.replace("  base: main\n", ""), encoding="utf-8"
    )
    verified(delivery_repo, monkeypatch, capsys)
    monkeypatch.setattr(acquire, "default_branch", lambda *a, **k: None)

    assert cli.main(["deliver"]) == cli.EXIT_REFUSED

    assert "could not be determined" in capsys.readouterr().err


def test_no_force_push_can_be_assembled_anywhere_in_the_program():
    """Condition 3, tested as the invariant rather than as prose.

    Greps trip over the docstring that documents the rule. This walks every
    module's AST instead and looks at the argument lists that actually reach a
    subprocess: no list that says `push` may also carry a force flag, and no
    literal anywhere may be a `+refs/` refspec.
    """
    import ast

    forcing = {"--force", "-f", "--force-with-lease", "--mirror"}
    offenders: list[str] = []
    for path in (Path(__file__).resolve().parent.parent / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.startswith("+refs/"):
                    offenders.append(f"{path.name}:{node.lineno} refspec")
            if not isinstance(node, (ast.List, ast.Tuple)):
                continue
            literals = {
                element.value
                for element in node.elts
                if isinstance(element, ast.Constant)
                and isinstance(element.value, str)
            }
            if "push" in literals and literals & forcing:
                offenders.append(f"{path.name}:{node.lineno} force push")
    assert not offenders, offenders


def test_a_tree_mid_merge_is_refused(delivery_repo, monkeypatch, capsys):
    verified(delivery_repo, monkeypatch, capsys)
    git_dir = Path(git(delivery_repo, "rev-parse", "--git-dir"))
    if not git_dir.is_absolute():
        git_dir = delivery_repo / git_dir
    (git_dir / "MERGE_HEAD").write_text("x\n", encoding="utf-8")

    assert cli.main(["deliver"]) == cli.EXIT_REFUSED

    assert "in the middle of a merge" in capsys.readouterr().err


def test_a_repo_without_a_deliver_section_cannot_write_history(
    repo, monkeypatch, capsys
):
    (repo / ".wringer.yaml").write_text(
        'version: 1\ngates:\n  - id: c\n    run: "true"\n', encoding="utf-8"
    )
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["deliver"]) == cli.EXIT_CONFIG

    assert "makes writing git history unreachable" in capsys.readouterr().err


# --- wring deliver --send ------------------------------------------------


def test_send_branches_commits_pushes_and_opens_an_mr(
    delivery_repo, monkeypatch, capsys
):
    """End to end against a real `file://` remote and a fake forge."""
    verified(delivery_repo, monkeypatch, capsys)
    monkeypatch.setenv("FORGE_TOKEN", "ghp_livetokenvalue1")
    calls = fake_forge(monkeypatch, reply=MR_REPLY)

    assert cli.main(["deliver", "--send"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "pull/7" in out
    branch = git(delivery_repo, "rev-parse", "--abbrev-ref", "HEAD")
    assert branch.startswith("wringer/")
    # the change is committed on the new branch, and pushed to the remote
    assert "feature.py" in git(delivery_repo, "show", "--name-only", "--format=")
    assert branch in git(delivery_repo, "branch", "-r", "--list", f"origin/{branch}")
    # main is untouched
    assert git(delivery_repo, "log", "--oneline", "main", "-1").endswith("config")

    posted = calls[0]
    assert posted["method"] == "POST"
    assert posted["body"]["head"] == branch and posted["body"]["base"] == "main"
    assert "| check | passed |" in posted["body"]["body"]


def test_every_git_write_is_on_the_ledger_before_it_happens(
    delivery_repo, monkeypatch, capsys
):
    """Condition 5. The order matters: a crash mid-delivery must still say
    what was attempted."""
    verified(delivery_repo, monkeypatch, capsys)
    monkeypatch.setenv("FORGE_TOKEN", "t123456")
    fake_forge(monkeypatch, reply=MR_REPLY)
    assert cli.main(["deliver", "--send"]) == cli.EXIT_OK
    capsys.readouterr()

    written = sorted((delivery_repo / deliver.DELIVERIES_DIRNAME).iterdir())[0]
    events = [
        json.loads(line)
        for line in (written / deliver.EVENTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    kinds = [e["type"] for e in events]
    assert kinds == [
        "branch.planned", "branch.created",
        "commit.planned", "commit.written",
        "push.planned", "push.done",
        "mr.planned", "mr.opened",
    ]
    # hash-chained, like every other ledger in the program
    assert all("prev_hash" in e for e in events)
    # the branch name is recorded BEFORE the branch exists
    assert kinds.index("branch.planned") < kinds.index("branch.created")


def test_a_token_never_reaches_an_artifact(delivery_repo, monkeypatch, capsys):
    secret = "ghp_supersecretvalue99"
    verified(delivery_repo, monkeypatch, capsys)
    monkeypatch.setenv("FORGE_TOKEN", secret)
    calls = fake_forge(monkeypatch, reply=MR_REPLY)

    assert cli.main(["deliver", "--send"]) == cli.EXIT_OK
    capsys.readouterr()

    assert secret in json.dumps(calls[0]["headers"])
    written = sorted((delivery_repo / deliver.DELIVERIES_DIRNAME).iterdir())[0]
    for path in written.iterdir():
        assert secret not in path.read_text(encoding="utf-8"), path.name


def test_an_edited_commit_message_is_the_one_that_is_used(
    delivery_repo, monkeypatch, capsys
):
    """The dry run wrote it and invited the human to edit it. Reading the
    object instead of the file would quietly discard that edit."""
    verified(delivery_repo, monkeypatch, capsys)
    assert cli.main(["deliver"]) == cli.EXIT_OK
    capsys.readouterr()
    written = sorted((delivery_repo / deliver.DELIVERIES_DIRNAME).iterdir())[0]
    (written / deliver.COMMIT_FILENAME).write_text(
        "I wrote this myself\n", encoding="utf-8"
    )

    # a second run makes its own bundle, so edit that one instead
    monkeypatch.setenv("FORGE_TOKEN", "t123456")
    fake_forge(monkeypatch, reply=MR_REPLY)
    planned = deliver.plan(
        delivery_repo,
        __import__("wringer").config.load(delivery_repo / ".wringer.yaml"),
        sorted((delivery_repo / ".wringer" / "runs").iterdir())[0],
        "manual",
    )
    bundle = deliver.Bundle.create(delivery_repo / deliver.DELIVERIES_DIRNAME)
    bundle.write_plan(planned)
    (bundle.directory / deliver.COMMIT_FILENAME).write_text(
        "I wrote this myself\n", encoding="utf-8"
    )
    deliver.send(delivery_repo, bundle, planned, push=False)

    assert git(delivery_repo, "log", "-1", "--format=%B").strip() == (
        "I wrote this myself"
    )


def test_a_failed_mr_leaves_the_branch_and_says_so(delivery_repo, monkeypatch,
                                                    capsys):
    """A push that landed and an MR that did not is a real state, and naming
    it beats failing the whole command over it."""
    verified(delivery_repo, monkeypatch, capsys)
    monkeypatch.setenv("FORGE_TOKEN", "t123456")
    fake_forge(monkeypatch, fail="422 Unprocessable")

    assert cli.main(["deliver", "--send"]) == cli.EXIT_OK

    captured = capsys.readouterr()
    assert "the branch is pushed" in captured.err
    assert "could not be opened" in captured.err
    written = sorted((delivery_repo / deliver.DELIVERIES_DIRNAME).iterdir())[0]
    manifest = json.loads(
        (written / deliver.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest["result"]["pushed"] is True
    assert manifest["result"]["merge_request"] is None


def test_a_delivery_never_carries_the_evidence_bundle(repo, monkeypatch, capsys):
    """A repo that ran `wring init` has `.wringer/` gitignored — but `wring
    verify` alone never writes a .gitignore, so a plain `git add --all` swept
    the whole bundle into a commit and pushed it to a public branch.

    SECURITY.md is explicit that a bundle may hold whatever a gate printed,
    and the README promises nothing uploads, ever. An MR body that carefully
    omits gate logs is pointless beside a commit that carries them.
    """
    secret = "hunter2-printed-by-a-gate"
    upstream = repo.parent / f"{repo.name}-leak.git"
    git(repo, "init", "--bare", "-b", "main", str(upstream))
    git(repo, "remote", "add", "origin", f"file://{upstream}")
    (repo / ".wringer.yaml").write_text(
        CONFIG.replace('run: "true"', f'run: "echo {secret}"'), encoding="utf-8"
    )
    # deliberately NO .gitignore: this repo ran verify, never init
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "config")
    git(repo, "push", "-u", "origin", "main")
    (repo / "feature.py").write_text("y = 2\n", encoding="utf-8")

    monkeypatch.chdir(repo)
    monkeypatch.setenv("FORGE_TOKEN", "t1234567")
    assert cli.main(["verify"]) == cli.EXIT_OK
    fake_forge(monkeypatch, reply=MR_REPLY)
    assert cli.main(["deliver", "--send"]) == cli.EXIT_OK
    capsys.readouterr()

    committed = git(repo, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert committed == ["feature.py"], committed
    assert not [p for p in committed if p.startswith(".wringer/")]
    # the bundle really did exist and really did hold the gate's output, or
    # this test would pass against a repo that had nothing to leak
    bundle = sorted((repo / ".wringer" / "runs").iterdir())[0]
    assert secret in (bundle / "gates" / "001_check" / "stdout.log").read_text(
        encoding="utf-8"
    )


def test_the_plan_counts_only_what_it_will_carry(repo, monkeypatch, capsys):
    """The count in the report and the MR body must describe the commit that
    will happen, not the working tree that happens to be dirty."""
    upstream = repo.parent / f"{repo.name}-count.git"
    git(repo, "init", "--bare", "-b", "main", str(upstream))
    git(repo, "remote", "add", "origin", f"file://{upstream}")
    (repo / ".wringer.yaml").write_text(CONFIG, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "config")
    git(repo, "push", "-u", "origin", "main")
    (repo / "feature.py").write_text("y = 2\n", encoding="utf-8")

    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main(["deliver", "--json"]) == cli.EXIT_OK

    payload = json.loads(capsys.readouterr().out)
    # one file, not one-plus-a-bundle
    assert payload["files"] == 1


def test_a_tree_dirty_only_with_evidence_has_nothing_to_deliver(
    repo, monkeypatch, capsys
):
    """The mirror of the above: if the ONLY thing that changed is Wringer's
    own bundle, there is genuinely nothing to deliver — and delivering an
    empty commit describing someone's evidence would be worse than refusing."""
    upstream = repo.parent / f"{repo.name}-onlyev.git"
    git(repo, "init", "--bare", "-b", "main", str(upstream))
    git(repo, "remote", "add", "origin", f"file://{upstream}")
    (repo / ".wringer.yaml").write_text(CONFIG, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "config")
    git(repo, "push", "-u", "origin", "main")

    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["deliver"]) == cli.EXIT_GATE_FAILED
    assert "nothing to deliver" in capsys.readouterr().err


def test_no_git_identity_is_refused_before_the_branch_exists(
    delivery_repo, monkeypatch, capsys
):
    """A commit with no author fails AFTER the branch is created, leaving a
    half-delivered branch for a reason that had nothing to do with the change.
    Refuse first.

    macOS hides this by inventing `user@host`; Linux with an unqualified
    hostname does not. That divergence turned this suite red on CI and green
    locally, which is the worst way to find out.
    """
    git(delivery_repo, "config", "--unset", "user.email")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.useConfigOnly")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    monkeypatch.setenv("HOME", str(delivery_repo / "nohome"))
    verified(delivery_repo, monkeypatch, capsys)

    assert cli.main(["deliver", "--send"]) == cli.EXIT_CONFIG

    err = capsys.readouterr().err
    assert "user.email" in err
    assert "does not invent one" in err
    # and no branch was created, which is the whole point of checking early
    assert git(delivery_repo, "branch", "--list") == "* main"


# --- config values that reach git's argv or someone else's URL -----------
#
# Found by probing the P3 slice after it shipped. Both are the same shape: a
# string from `.wringer.yaml` arriving somewhere it is read as syntax rather
# than as a name. `.wringer.yaml` is code by design (SECURITY.md), so neither
# is a privilege escalation — but SPEC_GET_V0.md §1's third condition says no
# force push is assemblable ANYWHERE in the program, and a remote of
# `--force` assembled one without the word appearing in the source.


@pytest.mark.parametrize(
    "value",
    ["--force", "-f", "--mirror", "--receive-pack=touch /tmp/pwned", "-", "--"],
)
@pytest.mark.parametrize("key", ["remote", "base"])
def test_a_deliver_name_can_never_look_like_a_git_option(key, value):
    from wringer import config

    with pytest.raises(config.ConfigError, match="plain name"):
        config.parse(
            {
                "version": 1,
                "gates": [{"id": "t", "run": "true"}],
                "deliver": {key: value},
            }
        )


@pytest.mark.parametrize("value", ["origin", "upstream", "my-fork", "main",
                                   "release/2.0", "a_b.c"])
def test_ordinary_remote_and_branch_names_still_parse(value):
    from wringer import config

    parsed = config.parse(
        {
            "version": 1,
            "gates": [{"id": "t", "run": "true"}],
            "deliver": {"remote": value, "base": value},
        }
    )
    assert parsed.deliver is not None
    assert parsed.deliver.remote == value and parsed.deliver.base == value


@pytest.mark.parametrize(
    "repo_name",
    ["../..", "owner/../../admin", "a/b/../../c", "-x/y", "./x", "owner/.."],
)
def test_a_forge_repo_can_never_escape_the_declared_repository(repo_name):
    """It is interpolated into a path on someone else's API. GitLab
    percent-encodes the whole string and would have been safe; GitHub does
    not, and being safe on one of the two forges is not a rule."""
    from wringer import config

    with pytest.raises(config.ConfigError, match="owner/name"):
        config.parse(
            {
                "version": 1,
                "gates": [{"id": "t", "run": "true"}],
                "forge": {
                    "kind": "github",
                    "endpoint": "https://api.github.com",
                    "repo": repo_name,
                },
            }
        )


def test_the_declared_repo_is_the_only_one_a_url_can_reach():
    """Belt to the parse-time braces: even a well-formed repo cannot be
    swapped by the URL a human pastes."""
    from wringer import config

    forge_cfg = config.parse(
        {
            "version": 1,
            "gates": [{"id": "t", "run": "true"}],
            "forge": {
                "kind": "github",
                "endpoint": "https://api.github.com",
                "repo": "acme/reports",
            },
        }
    ).forge
    assert forge_cfg is not None
    url = forge._url(forge_cfg, "/repos/{repo}/issues/{number}", number=1)
    assert url == "https://api.github.com/repos/acme/reports/issues/1"
    with pytest.raises(forge.ForgeError, match="declares"):
        forge.issue_number("https://github.com/evil/other/issues/1", forge_cfg)


@pytest.mark.parametrize(
    "url",
    ["user:pw@host:path/x.git", "a@b@evil.com:x.git", "ssh://u:p@h/x.git",
     "https://u:p@example.com/x.git", "ext::sh -c whoami", "-u/x.git",
     # the way a token actually gets pasted
     "https://ghp_tokentokentoken@github.com/o/n.git"],
)
def test_a_clone_url_that_carries_credentials_or_a_transport_is_refused(url):
    with pytest.raises(acquire.AcquireError):
        acquire.check_url(url)


@pytest.mark.parametrize(
    "url",
    ["git@github.com:owner/name.git", "https://github.com/o/n.git",
     "ssh://git@host/o/n.git", "file:///tmp/x"],
)
def test_the_clone_urls_people_actually_use_are_accepted(url):
    acquire.check_url(url)


# --- Phase 1: the claims must be true (WRINGER_RELEASE_PLAN.md §2) -------
#
# `gates_passed` reads a bundle's STATUS. It says nothing about WHAT passed.
# Without the checks below, a user could verify, keep working, and deliver —
# and the merge request would carry that run's gate table over code the gates
# never saw. Reproduced before it was fixed: a tree whose gate greps for GOOD
# shipped a file containing BROKEN, under an MR body reading "check | passed".


def test_delivering_a_tree_the_gates_never_saw_is_refused(
    delivery_repo, monkeypatch, capsys
):
    """THE test. Verify, keep working, deliver — the second must refuse."""
    verified(delivery_repo, monkeypatch, capsys)
    # keep working after the gates ran
    (delivery_repo / "feature.py").write_text("def added():\n    return 2\n",
                                              encoding="utf-8")
    (delivery_repo / "afterwards.py").write_text("late = True\n", encoding="utf-8")

    assert cli.main(["deliver", "--send"]) == cli.EXIT_GATE_FAILED

    err = capsys.readouterr().err
    assert "working tree has moved" in err
    assert "code it never saw" in err
    assert git(delivery_repo, "branch", "--list").strip() == "* main"


def test_an_edit_to_an_already_changed_file_is_refused(
    delivery_repo, monkeypatch, capsys
):
    """The file list can match while the bytes do not — the commonest way a
    tree moves without its shape moving. The captured patch catches it."""
    verified(delivery_repo, monkeypatch, capsys)
    tracked = delivery_repo / ".wringer.yaml"
    tracked.write_text(
        tracked.read_text(encoding="utf-8") + "\n# edited after verifying\n",
        encoding="utf-8",
    )
    # same file list as the run, different contents
    assert cli.main(["deliver", "--send"]) == cli.EXIT_GATE_FAILED

    err = capsys.readouterr().err
    assert "differ from what" in err or "working tree has moved" in err


def test_a_new_head_since_the_run_is_refused(delivery_repo, monkeypatch, capsys):
    verified(delivery_repo, monkeypatch, capsys)
    (delivery_repo / "committed.py").write_text("z = 1\n", encoding="utf-8")
    git(delivery_repo, "add", "committed.py")
    git(delivery_repo, "commit", "-m", "moved HEAD")

    assert cli.main(["deliver", "--send"]) == cli.EXIT_GATE_FAILED

    assert "but HEAD is now" in capsys.readouterr().err


def test_the_commit_carries_only_the_planned_paths(
    delivery_repo, monkeypatch, capsys
):
    """`git commit` commits the whole index, so anything staged beforehand
    rode along — into a public branch, under an MR claiming it was verified.
    `--only` makes the plan's file list the commit."""
    (delivery_repo / "staged-earlier.txt").write_text("mine\n", encoding="utf-8")
    git(delivery_repo, "add", "staged-earlier.txt")
    verified(delivery_repo, monkeypatch, capsys)
    monkeypatch.setenv("FORGE_TOKEN", "t1234567")
    fake_forge(monkeypatch, reply=MR_REPLY)

    assert cli.main(["deliver", "--send"]) == cli.EXIT_OK
    capsys.readouterr()

    shipped = git(delivery_repo, "show", "--name-only", "--format=",
                  "HEAD").splitlines()
    # it was staged before the run, so the run DID see it and it is delivered;
    # what matters is that the commit is exactly the plan's list
    written = sorted((delivery_repo / deliver.DELIVERIES_DIRNAME).iterdir())[0]
    planned = json.loads(
        (written / deliver.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )["files"]
    assert sorted(shipped) == sorted(planned)


def test_deliver_base_cannot_unlock_the_default_branch(
    delivery_repo, monkeypatch, capsys
):
    """Condition 2 was defeated by a config key: naming a different `base`
    skipped the default-branch lookup entirely."""
    (delivery_repo / ".wringer.yaml").write_text(
        CONFIG.replace('branch: "wringer/{run}"', 'branch: "main"')
        .replace("base: main", "base: release"),
        encoding="utf-8",
    )
    # stand somewhere else: "you are standing on it" is also a correct
    # refusal, and it would fire first and hide the one under test
    git(delivery_repo, "switch", "--create", "sidebar")
    verified(delivery_repo, monkeypatch, capsys)

    assert cli.main(["deliver"]) == cli.EXIT_REFUSED

    assert "remote's default branch" in capsys.readouterr().err


def test_a_branch_that_exists_only_on_the_remote_is_refused(
    delivery_repo, monkeypatch, capsys
):
    """Condition 1 said *only a branch Wringer created*; checking local refs
    alone let it push into a branch someone else already had."""
    verified(delivery_repo, monkeypatch, capsys)
    assert cli.main(["deliver", "--json"]) == cli.EXIT_OK
    planned = json.loads(capsys.readouterr().out)["branch"]

    git(delivery_repo, "branch", planned)
    git(delivery_repo, "push", "origin", planned)
    git(delivery_repo, "branch", "-D", planned)
    git(delivery_repo, "update-ref", "-d", f"refs/remotes/origin/{planned}")

    assert cli.main(["deliver"]) == cli.EXIT_REFUSED
    assert "already exists" in capsys.readouterr().err

def test_a_delivery_records_the_spec_that_authorised_it(
    delivery_repo, monkeypatch, capsys
):
    """`approved: true` in wringer.spec.yaml is the authority the whole build
    runs on, and nothing recorded WHICH spec that was — so `wring attest`'s
    first clause had nothing to point at, and an approved spec could be
    edited afterwards with no trace."""
    import hashlib

    from wringer import spec as spec_module

    approved = (
        "schema_version: wringer.spec.v1\napproved: true\ntitle: t\n"
        "intent: |2\n  words\ncriteria:\n  - id: c1\n    title: T\n"
        "    required: true\n    human: false\n"
        "tasks:\n  - id: t1\n    brief: briefs/t1.md\n    dir: .\n"
        "    objective: o\n"
    )
    (delivery_repo / spec_module.SPEC_FILENAME).write_text(approved, "utf-8")
    verified(delivery_repo, monkeypatch, capsys)

    assert cli.main(["deliver"]) == cli.EXIT_OK
    capsys.readouterr()

    written = sorted((delivery_repo / deliver.DELIVERIES_DIRNAME).iterdir())[0]
    manifest = json.loads(
        (written / deliver.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest["spec_sha256"] == hashlib.sha256(
        approved.encode("utf-8")
    ).hexdigest()


def test_a_delivery_with_no_spec_says_so_rather_than_guessing(
    delivery_repo, monkeypatch, capsys
):
    """A delivery can be a plain verified change. Null is the honest value."""
    verified(delivery_repo, monkeypatch, capsys)

    assert cli.main(["deliver"]) == cli.EXIT_OK
    capsys.readouterr()

    written = sorted((delivery_repo / deliver.DELIVERIES_DIRNAME).iterdir())[0]
    manifest = json.loads(
        (written / deliver.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest["spec_sha256"] is None


# --- the delivered tree must BE the verified tree ---------------------------
#
# Three holes, each confirmed by reproduction on 2026-08-05 before being
# fixed, all with the same consequence: `wring deliver` published a branch
# whose tree differed from the one the gates ran against. That is law 1 and
# law 2 broken by the one command that speaks to the outside world — the
# same class as the 2026-08-02 finding where an MR body reported a gate table
# for a tree it had never seen.


def test_a_renamed_file_is_not_resurrected_on_the_delivered_branch(
    delivery_repo, monkeypatch, capsys
):
    """A staged rename deletes the source. The delivered branch must not
    carry it.

    Before the fix: `git mv src dst` -> verify -> deliver produced
    changed_files == ("dst.py",), so deliver's commit pathspec omitted the
    deletion entirely. The branch shipped BOTH files while the run's own
    diff.patch recorded `rename from src.py / rename to dst.py` — the merge
    request attesting a rename its own branch did not contain.
    """
    (delivery_repo / "feature.py").unlink()  # start from the fixture's clean base
    (delivery_repo / "src.py").write_text("def original():\n    return 1\n", "utf-8")
    git(delivery_repo, "add", "-A")
    git(delivery_repo, "commit", "-m", "add source")
    git(delivery_repo, "mv", "src.py", "dst.py")

    verified(delivery_repo, monkeypatch, capsys)
    run_dir = sorted((delivery_repo / ".wringer" / "runs").iterdir())[-1]
    cfg = config.load(delivery_repo / ".wringer.yaml")
    planned = deliver.plan(delivery_repo, cfg, run_dir, "rename")
    bundle = deliver.Bundle.create(delivery_repo / deliver.DELIVERIES_DIRNAME)
    bundle.write_plan(planned)
    deliver.send(delivery_repo, bundle, planned, push=False)

    shipped = set(
        git(delivery_repo, "ls-tree", "-r", "--name-only", "wringer/rename").split()
    )
    assert "dst.py" in shipped
    assert "src.py" not in shipped, (
        "the delivered branch resurrected a file the verified tree deleted"
    )
    # and nothing is left stranded in the index afterwards
    assert "src.py" not in git(delivery_repo, "status", "--porcelain")


def test_a_rename_made_in_an_editor_is_not_resurrected_either(
    delivery_repo, monkeypatch, capsys
):
    """The same hole, reached through the porcelain's OTHER column.

    A rename done by `git mv` flags the index column; a rename done in an
    editor and then declared with `git add -N` flags the worktree column
    (` R b.c\\0a.c\\0`), and the parser used to test the index column alone.
    With the two-entry shape unrecognised the source was read as a status
    line of its own, so a 3-character path sliced to the empty string, which
    then vanished from the NUL-joined pathspec. `git commit --only` never
    named the deletion and the delivered branch kept `a.c` — no refusal, no
    error, exactly the outcome the rename fix above existed to prevent.
    """
    (delivery_repo / "feature.py").unlink()  # start from the fixture's clean base
    (delivery_repo / "a.c").write_text("int original(void) { return 1; }\n", "utf-8")
    git(delivery_repo, "add", "-A")
    git(delivery_repo, "commit", "-m", "add source")
    (delivery_repo / "a.c").rename(delivery_repo / "b.c")
    git(delivery_repo, "add", "-N", "b.c")

    verified(delivery_repo, monkeypatch, capsys)
    run_dir = sorted((delivery_repo / ".wringer" / "runs").iterdir())[-1]
    cfg = config.load(delivery_repo / ".wringer.yaml")
    planned = deliver.plan(delivery_repo, cfg, run_dir, "editorrename")
    bundle = deliver.Bundle.create(delivery_repo / deliver.DELIVERIES_DIRNAME)
    bundle.write_plan(planned)
    deliver.send(delivery_repo, bundle, planned, push=False)

    shipped = set(
        git(
            delivery_repo, "ls-tree", "-r", "--name-only", "wringer/editorrename"
        ).split()
    )
    assert "b.c" in shipped
    assert "a.c" not in shipped, (
        "the delivered branch resurrected a file the verified tree deleted"
    )
    assert "a.c" not in git(delivery_repo, "status", "--porcelain")


def test_a_file_added_inside_an_untracked_directory_is_refused(
    delivery_repo, monkeypatch, capsys
):
    """`git status --porcelain` collapses an untracked directory to ONE
    entry, so a set-compare of names cannot see a file appearing inside it.

    Before the fix this shipped: a file created AFTER the gates ran was
    pushed on the delivery branch, at arbitrary nesting depth, while the
    patch shown to the approving human was zero bytes — because the
    untracked *directory* was skipped by the diff too.
    """
    (delivery_repo / "feature.py").unlink()
    newdir = delivery_repo / "newdir"
    newdir.mkdir()
    (newdir / "a.txt").write_text("first\n", encoding="utf-8")

    verified(delivery_repo, monkeypatch, capsys)
    run_dir = sorted((delivery_repo / ".wringer" / "runs").iterdir())[-1]

    (newdir / "b.txt").write_text("SMUGGLED AFTER VERIFY\n", encoding="utf-8")

    cfg = config.load(delivery_repo / ".wringer.yaml")
    with pytest.raises(deliver.Refused) as refusal:
        deliver.plan(delivery_repo, cfg, run_dir, "smuggle")
    assert "b.txt" in str(refusal.value), str(refusal.value)


def test_the_smuggle_is_caught_at_any_nesting_depth(
    delivery_repo, monkeypatch, capsys
):
    """The checker who re-reproduced this found it reached arbitrary depth,
    not just direct children — so the guard is asserted at depth too."""
    (delivery_repo / "feature.py").unlink()
    deep = delivery_repo / "newdir" / "deep" / "deeper"
    deep.mkdir(parents=True)
    (delivery_repo / "newdir" / "a.txt").write_text("first\n", encoding="utf-8")

    verified(delivery_repo, monkeypatch, capsys)
    run_dir = sorted((delivery_repo / ".wringer" / "runs").iterdir())[-1]

    (deep / "evil.txt").write_text("SMUGGLED\n", encoding="utf-8")

    cfg = config.load(delivery_repo / ".wringer.yaml")
    with pytest.raises(deliver.Refused) as refusal:
        deliver.plan(delivery_repo, cfg, run_dir, "deep")
    assert "evil.txt" in str(refusal.value), str(refusal.value)


def test_untracked_content_that_did_not_change_still_delivers(
    delivery_repo, monkeypatch, capsys
):
    """The control. Enumerating untracked files per-file must not make an
    honest delivery refuse — only a changed one."""
    (delivery_repo / "feature.py").unlink()
    newdir = delivery_repo / "newdir"
    newdir.mkdir()
    (newdir / "a.txt").write_text("first\n", encoding="utf-8")

    verified(delivery_repo, monkeypatch, capsys)
    run_dir = sorted((delivery_repo / ".wringer" / "runs").iterdir())[-1]

    cfg = config.load(delivery_repo / ".wringer.yaml")
    planned = deliver.plan(delivery_repo, cfg, run_dir, "honest")
    bundle = deliver.Bundle.create(delivery_repo / deliver.DELIVERIES_DIRNAME)
    bundle.write_plan(planned)
    deliver.send(delivery_repo, bundle, planned, push=False)

    shipped = set(
        git(delivery_repo, "ls-tree", "-r", "--name-only", "wringer/honest").split()
    )
    assert "newdir/a.txt" in shipped
    # and the human was shown a real patch, not an empty one
    patch = (bundle.directory / deliver.PATCH_FILENAME).read_text(encoding="utf-8")
    assert "newdir/a.txt" in patch, "the approving human was shown an empty patch"


def test_editing_an_untracked_file_after_verify_is_refused(
    delivery_repo, monkeypatch, capsys
):
    """The gap this closes, stated as it used to be stated in the source:
    "an *untracked* file's contents are not in the bundle — git cannot diff
    what it has never seen — so a content-only edit to an untracked file is
    not detected here."

    The file list is unchanged, every tracked byte is unchanged, and the
    delivered content is different from the verified content. Nothing else in
    check_verified_tree could see it.
    """
    (delivery_repo / "feature.py").unlink()
    loose = delivery_repo / "notes.txt"
    loose.write_text("verified content\n", encoding="utf-8")

    verified(delivery_repo, monkeypatch, capsys)
    run_dir = sorted((delivery_repo / ".wringer" / "runs").iterdir())[-1]
    assert (run_dir / evidence.UNTRACKED_FILENAME).is_file()

    loose.write_text("EDITED AFTER VERIFY\n", encoding="utf-8")

    cfg = config.load(delivery_repo / ".wringer.yaml")
    with pytest.raises(deliver.Refused) as refusal:
        deliver.plan(delivery_repo, cfg, run_dir, "edited")
    assert "notes.txt" in str(refusal.value)
    assert "git never saw" in str(refusal.value)


def test_an_unchanged_untracked_file_still_delivers(
    delivery_repo, monkeypatch, capsys
):
    """The control: recording untracked bytes must not refuse an honest
    delivery."""
    (delivery_repo / "feature.py").unlink()
    (delivery_repo / "notes.txt").write_text("stable\n", encoding="utf-8")

    verified(delivery_repo, monkeypatch, capsys)
    run_dir = sorted((delivery_repo / ".wringer" / "runs").iterdir())[-1]
    cfg = config.load(delivery_repo / ".wringer.yaml")

    planned = deliver.plan(delivery_repo, cfg, run_dir, "stable")
    assert "notes.txt" in planned.changed_files


def test_a_bundle_without_untracked_json_keeps_its_old_behaviour(
    delivery_repo, monkeypatch, capsys
):
    """Bundles written before this file existed never made the claim, so
    retro-fitting a refusal onto them would fail deliveries that were always
    fine. Names are still compared; bytes are not."""
    (delivery_repo / "feature.py").unlink()
    loose = delivery_repo / "notes.txt"
    loose.write_text("verified content\n", encoding="utf-8")

    verified(delivery_repo, monkeypatch, capsys)
    run_dir = sorted((delivery_repo / ".wringer" / "runs").iterdir())[-1]
    (run_dir / evidence.UNTRACKED_FILENAME).unlink()  # as a pre-0.3 bundle

    loose.write_text("EDITED AFTER VERIFY\n", encoding="utf-8")

    cfg = config.load(delivery_repo / ".wringer.yaml")
    planned = deliver.plan(delivery_repo, cfg, run_dir, "legacy")
    assert "notes.txt" in planned.changed_files


def test_an_unreadable_untracked_file_is_refused_not_ignored(
    delivery_repo, monkeypatch, capsys
):
    """A file whose bytes could not be read has not been verified. Skipping
    it would let an unreadable file deliver as if it had been checked."""
    (delivery_repo / "feature.py").unlink()
    (delivery_repo / "notes.txt").write_text("x\n", encoding="utf-8")
    verified(delivery_repo, monkeypatch, capsys)
    run_dir = sorted((delivery_repo / ".wringer" / "runs").iterdir())[-1]

    recorded = run_dir / evidence.UNTRACKED_FILENAME
    payload = json.loads(recorded.read_text(encoding="utf-8"))
    payload["files"]["notes.txt"] = evidence.UNREADABLE
    recorded.write_text(json.dumps(payload), encoding="utf-8")

    cfg = config.load(delivery_repo / ".wringer.yaml")
    with pytest.raises(deliver.Refused) as refusal:
        deliver.plan(delivery_repo, cfg, run_dir, "unreadable")
    assert "notes.txt" in str(refusal.value)


def test_untracked_json_is_covered_by_the_digests(
    delivery_repo, monkeypatch, capsys
):
    """Write order matters: untracked.json before digests.json, or the
    bundle's own tamper-evidence would not cover it."""
    (delivery_repo / "feature.py").unlink()
    (delivery_repo / "notes.txt").write_text("x\n", encoding="utf-8")
    verified(delivery_repo, monkeypatch, capsys)
    run_dir = sorted((delivery_repo / ".wringer" / "runs").iterdir())[-1]

    digests = json.loads(
        (run_dir / evidence.DIGESTS_FILENAME).read_text(encoding="utf-8")
    )
    assert evidence.UNTRACKED_FILENAME in digests["files"]


def test_an_unreachable_remote_refuses_rather_than_assuming_no_branch(
    delivery_repo, monkeypatch, capsys
):
    """`ls-remote` failing is not "the branch does not exist".

    Both were folded into `False`, so an unreachable remote silently
    satisfied condition 1 — Wringer only ever commits to a branch it
    created — and delivery planned a branch that might already be someone
    else's history.
    """
    verified(delivery_repo, monkeypatch, capsys)
    run_dir = sorted((delivery_repo / ".wringer" / "runs").iterdir())[-1]
    # a remote that is syntactically fine and cannot be reached
    git(delivery_repo, "remote", "set-url", "origin",
        f"file://{delivery_repo.parent}/does-not-exist.git")
    # and no remote-tracking ref to answer from cache
    subprocess.run(["git", "update-ref", "-d", "refs/remotes/origin/main"],
                   cwd=delivery_repo, capture_output=True)

    cfg = config.load(delivery_repo / ".wringer.yaml")
    with pytest.raises(deliver.Refused) as refusal:
        deliver.plan(delivery_repo, cfg, run_dir, "unreachable")
    assert "cannot" in str(refusal.value).lower()


def test_base_does_not_smuggle_past_the_default_branch_check(
    repo, monkeypatch, capsys, git_run
):
    """`deliver.base` says which branch the MR targets. It has never meant
    "skip condition 2", and an unresolvable default used to make it do
    exactly that: the None short-circuited plan's guard and delivery would
    plan to create and push the remote's own default branch.
    """
    upstream = repo.parent / f"{repo.name}-c2-upstream.git"
    git_run(repo, "init", "--bare", "-b", "trunk", str(upstream))
    git_run(repo, "remote", "add", "origin", f"file://{upstream}")
    (repo / ".wringer.yaml").write_text(
        'version: 1\ngates:\n  - id: check\n    run: "true"\n'
        'deliver:\n  branch: "trunk"\n  base: develop\n  remote: origin\n',
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text(".wringer/\n", encoding="utf-8")
    git_run(repo, "add", "-A")
    git_run(repo, "commit", "-m", "config")
    (repo / "feature.py").write_text("def added():\n    return 1\n", "utf-8")

    verified(repo, monkeypatch, capsys)
    run_dir = sorted((repo / ".wringer" / "runs").iterdir())[-1]
    # never fetched, so there is no refs/remotes/origin/HEAD to resolve from
    git_run(repo, "remote", "set-url", "origin",
            f"file://{repo.parent}/nowhere.git")

    cfg = config.load(repo / ".wringer.yaml")
    with pytest.raises(deliver.Refused) as refusal:
        deliver.plan(repo, cfg, run_dir, "smuggled")
    assert "default branch" in str(refusal.value)
