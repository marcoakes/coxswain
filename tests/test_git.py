"""Git root detection and the state recorded in the manifest."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from wringer import git

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


def test_changed_and_untracked_are_recorded_separately(repo: Path, git_run):
    (repo / "tracked.py").write_text("one\n", encoding="utf-8")
    git_run(repo, "add", "tracked.py")
    git_run(repo, "commit", "-q", "-m", "add tracked")

    (repo / "tracked.py").write_text("two\n", encoding="utf-8")  # unstaged edit
    (repo / "staged.py").write_text("new\n", encoding="utf-8")
    git_run(repo, "add", "staged.py")  # staged addition
    (repo / "fresh.py").write_text("hi\n", encoding="utf-8")  # untracked

    state = git.inspect(repo)

    assert sorted(state.changed_files) == ["staged.py", "tracked.py"]
    assert state.untracked == ("fresh.py",)
    assert state.dirty is True


def test_a_rename_records_both_the_new_path_and_the_deleted_one(
    repo: Path, git_run
):
    """This test used to assert `changed_files == ("new.py",)` — it encoded
    the bug rather than the contract. A rename is two changes: a file
    appeared and a file was deleted. Recording only the arrival made
    `wring deliver` commit only the arrival, so the delivered branch kept a
    file the verified tree had removed.
    """
    (repo / "old.py").write_text("x\n", encoding="utf-8")
    git_run(repo, "add", "old.py")
    git_run(repo, "commit", "-q", "-m", "add old")
    git_run(repo, "mv", "old.py", "new.py")

    state = git.inspect(repo)

    assert sorted(state.changed_files) == ["new.py", "old.py"]
    assert state.untracked == ()


def test_paths_with_spaces_survive_parsing(repo: Path, git_run):
    (repo / "a file.py").write_text("x\n", encoding="utf-8")

    state = git.inspect(repo)

    assert state.untracked == ("a file.py",)


def test_a_clean_repo_lists_nothing(repo: Path):
    state = git.inspect(repo)

    assert state.changed_files == ()
    assert state.untracked == ()
    assert state.dirty is False


def test_diff_captures_staged_and_unstaged_but_not_untracked(repo: Path, git_run):
    (repo / "tracked.py").write_text("before\n", encoding="utf-8")
    git_run(repo, "add", "tracked.py")
    git_run(repo, "commit", "-q", "-m", "add tracked")
    (repo / "tracked.py").write_text("after\n", encoding="utf-8")
    (repo / "untracked.py").write_text("invisible\n", encoding="utf-8")

    patch = git.diff(repo, git.inspect(repo).head_sha)

    assert "--- a/tracked.py" in patch
    assert "-before" in patch
    assert "+after" in patch
    # git cannot diff a file it has never seen; status.txt lists it instead
    assert "untracked.py" not in patch


def test_binary_content_never_enters_the_patch(repo: Path, git_run):
    blob = repo / "image.bin"
    blob.write_bytes(b"\x00\x01\x02binary-marker-aaa\x00")
    git_run(repo, "add", "image.bin")
    git_run(repo, "commit", "-q", "-m", "add binary")
    blob.write_bytes(b"\x00\x01\x02binary-marker-bbb\x00\xff")

    patch = git.diff(repo, git.inspect(repo).head_sha)

    assert "Binary files" in patch
    assert "binary-marker-bbb" not in patch


def test_a_repo_cannot_force_binary_content_in_with_textconv(repo: Path, git_run):
    """`.gitattributes` can name a textconv driver that turns a blob into
    text. That is the repo deciding what goes in *our* evidence file, so we
    decline."""
    blob = repo / "image.bin"
    blob.write_bytes(b"\x00\x01\x02binary-marker-aaa\x00")
    (repo / ".gitattributes").write_text("*.bin diff=leak\n", encoding="utf-8")
    git_run(repo, "config", "diff.leak.textconv", "cat")
    git_run(repo, "add", "image.bin", ".gitattributes")
    git_run(repo, "commit", "-q", "-m", "add binary with a textconv driver")
    blob.write_bytes(b"\x00\x01\x02binary-marker-bbb\x00\xff")

    patch = git.diff(repo, git.inspect(repo).head_sha)

    assert "binary-marker-bbb" not in patch


def test_status_is_the_porcelain_form(repo: Path):
    (repo / "fresh.py").write_text("x\n", encoding="utf-8")

    # verbatim, including the trailing newline and the two status columns
    assert git.status(repo) == "?? fresh.py\n"


def test_diff_and_status_are_none_outside_a_repo(tmp_path: Path):
    assert git.diff(tmp_path, None) is None
    assert git.status(tmp_path) is None


def test_detached_head_records_no_branch(repo: Path, git_run):
    sha = git_run(repo, "rev-parse", "HEAD")
    git_run(repo, "checkout", "-q", "--detach", sha)

    state = git.inspect(repo)
    assert state.head_sha == sha
    assert state.branch is None


def test_is_repo_recognises_a_repo(repo: Path):
    assert git.is_repo(repo) is True


def test_is_repo_rejects_a_plain_directory(tmp_path: Path):
    assert git.is_repo(tmp_path) is False


def test_a_settled_tree_has_nothing_in_progress(repo: Path):
    assert git.in_progress(repo) is None


@pytest.mark.parametrize(
    "marker, described",
    [
        ("MERGE_HEAD", "a merge"),
        ("rebase-merge", "a rebase"),
        ("rebase-apply", "a rebase"),
        ("CHERRY_PICK_HEAD", "a cherry-pick"),
        ("REVERT_HEAD", "a revert"),
        ("BISECT_LOG", "a bisect"),
    ],
)
def test_every_half_finished_operation_is_named(
    repo: Path, marker: str, described: str
):
    """git leaves one of these behind mid-operation; each must be recognised,
    because verifying then describes a state nobody chose."""
    left_behind = repo / ".git" / marker
    if marker.startswith("rebase"):
        left_behind.mkdir()  # git uses a directory for these two
    else:
        left_behind.write_text("x\n", encoding="utf-8")

    assert git.in_progress(repo) == described


def test_a_real_conflicted_merge_is_detected(repo: Path, git_run):
    (repo / "shared.txt").write_text("base\n", encoding="utf-8")
    git_run(repo, "add", "shared.txt")
    git_run(repo, "commit", "-q", "-m", "base")

    git_run(repo, "checkout", "-q", "-b", "other")
    (repo / "shared.txt").write_text("theirs\n", encoding="utf-8")
    git_run(repo, "commit", "-q", "-am", "theirs")

    git_run(repo, "checkout", "-q", "main")
    (repo / "shared.txt").write_text("ours\n", encoding="utf-8")
    git_run(repo, "commit", "-q", "-am", "ours")
    git_run(repo, "merge", "other", check=False)

    assert git.in_progress(repo) == "a merge"


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


# --- a rename's source is evidence -----------------------------------------
#
# `_parse_status` used to skip the source path of an R/C porcelain entry, on
# the reasoning that "the new path is the one that exists now, so the source
# is not evidence". That is true of the source as a FILE and false of the
# source as a CHANGE: `git mv src.py dst.py` deletes src.py, and a bundle
# that does not record the deletion describes a tree that is not the one
# verified.
#
# It was not a cosmetic gap. `wring deliver` builds its commit pathspec from
# exactly this list (deliver.py), so with the source missing the deletion was
# never committed: the delivered branch carried BOTH files while the run's
# own diff.patch recorded a rename. Reproduced end to end before this fix —
# see tests/test_deliver.py's rename test.


def test_a_staged_rename_records_both_paths(repo: Path, git_run):
    (repo / "src.py").write_text("def original():\n    return 1\n", encoding="utf-8")
    git_run(repo, "add", "-A")
    git_run(repo, "commit", "-qm", "add source")
    git_run(repo, "mv", "src.py", "dst.py")

    state = git.inspect(repo)

    assert "dst.py" in state.changed_files, state.changed_files
    assert "src.py" in state.changed_files, (
        "the rename's source is deleted, and a bundle that omits the deletion "
        "describes a tree that was never verified"
    )


def test_a_rename_source_is_not_confused_with_an_untracked_file(repo: Path, git_run):
    """The two paths of an R entry are both *changed*; neither is untracked,
    and the entry after it must not be parsed as a status line."""
    (repo / "src.py").write_text("x = 1\n", encoding="utf-8")
    git_run(repo, "add", "-A")
    git_run(repo, "commit", "-qm", "add source")
    git_run(repo, "mv", "src.py", "dst.py")
    (repo / "loose.txt").write_text("untracked\n", encoding="utf-8")

    state = git.inspect(repo)

    assert set(state.changed_files) == {"src.py", "dst.py"}, state.changed_files
    assert state.untracked == ("loose.txt",), state.untracked
