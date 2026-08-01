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

from wringer import acquire, cli, deliver, forge

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
    git(repo, "init", "--bare", str(upstream))
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
        ("https://u:p@example.com/x.git", "credentials"),
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
    git(repo, "init", "--bare", str(upstream))
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
    git(repo, "init", "--bare", str(upstream))
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
    git(repo, "init", "--bare", str(upstream))
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
