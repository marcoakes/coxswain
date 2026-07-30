"""Git root detection and the state recorded in the manifest."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from cox import git

SHA = re.compile(r"^[0-9a-f]{40}$")


def test_find_root_from_the_root_and_from_a_subdirectory(repo: Path):
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)

    assert git.find_root(repo).resolve() == repo.resolve()
    assert git.find_root(nested).resolve() == repo.resolve()


def test_find_root_outside_a_repo_falls_back_to_the_starting_directory(tmp_path: Path):
    assert git.find_root(tmp_path) == tmp_path


def test_inspect_a_clean_repo(repo: Path):
    state = git.inspect(repo)

    assert SHA.match(state.head_sha), state.head_sha
    assert state.branch == "main"
    assert state.dirty is False


def test_untracked_files_make_the_tree_dirty(repo: Path):
    (repo / "scratch.txt").write_text("wip\n", encoding="utf-8")

    assert git.inspect(repo).dirty is True


def test_uncommitted_edits_make_the_tree_dirty(repo: Path, git_run):
    (repo / "tracked.txt").write_text("one\n", encoding="utf-8")
    git_run(repo, "add", "tracked.txt")
    git_run(repo, "commit", "-q", "-m", "add tracked file")
    assert git.inspect(repo).dirty is False

    (repo / "tracked.txt").write_text("two\n", encoding="utf-8")
    assert git.inspect(repo).dirty is True


def test_detached_head_records_no_branch(repo: Path, git_run):
    sha = git_run(repo, "rev-parse", "HEAD")
    git_run(repo, "checkout", "-q", "--detach", sha)

    state = git.inspect(repo)
    assert state.head_sha == sha
    assert state.branch is None


def test_a_wedged_git_call_is_bounded_and_treated_as_a_failure(
    tmp_path: Path, monkeypatch
):
    """The one failure we cannot provoke for real: a `git` that never
    returns (stale index lock, credential prompt). We simulate the timeout
    and assert the verifier records nulls instead of hanging — and that the
    bound is actually passed, since dropping it would be silent.
    """
    calls: list[dict] = []

    def hang(*args, **kwargs):
        calls.append(kwargs)
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(git.subprocess, "run", hang)

    state = git.inspect(tmp_path)

    assert state.head_sha is None
    assert state.branch is None
    assert state.dirty is False
    assert calls, "git was never invoked"
    assert all(call["timeout"] == git.GIT_TIMEOUT_SECONDS for call in calls)


def test_inspect_outside_a_repo_records_nulls(tmp_path: Path):
    state = git.inspect(tmp_path)

    assert state.head_sha is None
    assert state.branch is None
    assert state.dirty is False
