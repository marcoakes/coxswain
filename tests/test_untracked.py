"""`untracked.json` records what git will COMMIT, not what a gate could read.

The file answers exactly one question — *is the delivered tree the verified
tree?* — so it has to be keyed on the delivered object. The first version
opened each path with `target.open("rb")`, which follows symlinks, and that
is a different object from the one git puts in the commit:

| path on disk        | git commits              | `open("rb")` gave    |
|---------------------|--------------------------|----------------------|
| regular file        | `100644` + content       | the content          |
| executable          | `100755` + content       | the content          |
| symlink -> file     | `120000` + the LINK TEXT | the referent's bytes |
| symlink -> missing  | `120000` + the LINK TEXT | OSError              |
| symlink -> dir      | `120000` + the LINK TEXT | OSError              |
| symlink -> FIFO     | `120000` + the LINK TEXT | **blocks forever**   |

Every row after the second was wrong, and wrong in both directions at once:
too loose (retarget a symlink and delivery saw nothing), too strict (a
dangling link recorded `unreadable`, which `wring deliver` refuses — and
re-verifying records `unreadable` again, so the refusal is permanent), and
one outright hang. Recording git's identity instead fixes all of them with
one change, which is why they are one commit and one test file.
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import threading
from pathlib import Path

import pytest

from wringer import evidence


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def hashed(root: Path, *names: str) -> dict[str, str]:
    return evidence.hash_untracked(root, names)


def bounded(call, seconds: float = 10.0):
    """Run `call` on a daemon thread and fail rather than hang.

    A regression here does not make a test fail, it makes the SUITE never
    finish — which reads as a hung machine rather than as a bug. The thread
    is a daemon so even a wedged one cannot keep the interpreter alive.
    """
    box: dict[str, object] = {}

    def run() -> None:
        try:
            box["value"] = call()
        except BaseException as exc:  # noqa: BLE001 — reported, not swallowed
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        pytest.fail(
            f"hash_untracked did not return within {seconds}s — it followed "
            "the symlink and blocked on the pipe behind it"
        )
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]


# --- what a regular file records -------------------------------------------


def test_a_regular_file_records_its_mode_and_its_content(tmp_path: Path):
    content = b"hello\n"
    (tmp_path / "plain.txt").write_bytes(content)

    assert hashed(tmp_path, "plain.txt") == {"plain.txt": f"100644:{sha(content)}"}


def test_an_executable_file_records_the_mode_git_would_commit(tmp_path: Path):
    content = b"#!/bin/sh\n"
    (tmp_path / "run.sh").write_bytes(content)
    (tmp_path / "run.sh").chmod(0o755)

    assert hashed(tmp_path, "run.sh") == {"run.sh": f"100755:{sha(content)}"}


def test_chmod_alone_changes_what_is_recorded(tmp_path: Path):
    """The bytes are identical and the committed object is not. Recording
    content alone made a `chmod +x` between verify and deliver invisible."""
    target = tmp_path / "run.sh"
    target.write_bytes(b"#!/bin/sh\n")
    target.chmod(0o644)
    before = hashed(tmp_path, "run.sh")["run.sh"]

    target.chmod(0o755)

    assert hashed(tmp_path, "run.sh")["run.sh"] != before


def test_only_the_owner_execute_bit_makes_it_executable(tmp_path: Path):
    """git tests `st_mode & 0100`, not "any x bit" — measured on git 2.50.1,
    where a 0654 file is added as 100644. Recording 100755 for it would
    refuse a delivery over a mode git was never going to commit."""
    target = tmp_path / "odd.txt"
    target.write_bytes(b"x\n")
    target.chmod(0o654)  # group-executable, owner not

    assert hashed(tmp_path, "odd.txt")["odd.txt"].startswith("100644:")


def test_a_repo_that_ignores_file_modes_records_what_it_would_commit(
    tmp_path: Path,
):
    """`core.fileMode = false` — the default on filesystems that cannot hold
    the bit — makes git add even a 0755 file as `100644`. Measured. Recording
    100755 there would refuse deliveries over a distinction git is not
    making."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "core.fileMode", "false"], cwd=tmp_path,
                   check=True, capture_output=True)
    target = tmp_path / "run.sh"
    target.write_bytes(b"#!/bin/sh\n")
    target.chmod(0o755)

    assert hashed(tmp_path, "run.sh")["run.sh"].startswith("100644:")


# --- what a symlink records ------------------------------------------------


def test_a_symlink_records_its_link_text_not_the_referent(tmp_path: Path):
    (tmp_path / "target.txt").write_bytes(b"referent bytes\n")
    (tmp_path / "link").symlink_to("target.txt")

    assert hashed(tmp_path, "link") == {"link": f"120000:{sha(b'target.txt')}"}


def test_retargeting_a_symlink_at_identical_bytes_is_still_a_change(
    tmp_path: Path,
):
    """**The too-loose one.** Two files with the same content, and a link
    moved from one to the other. git commits a different blob — the link
    text — so the delivered tree is not the verified tree, and recording what
    the link POINTED AT could not tell them apart."""
    (tmp_path / "one.txt").write_bytes(b"same\n")
    (tmp_path / "two.txt").write_bytes(b"same\n")
    link = tmp_path / "link"
    link.symlink_to("one.txt")
    before = hashed(tmp_path, "link")["link"]

    link.unlink()
    link.symlink_to("two.txt")

    assert hashed(tmp_path, "link")["link"] != before, (
        "the link now names a different path, so git commits a different "
        "blob — identical referent bytes do not make it the same object"
    )


def test_a_file_replaced_by_a_symlink_to_itself_is_a_change(tmp_path: Path):
    """A type flip: `100644` + content becomes `120000` + link text. Reading
    through the link gave the same bytes both times."""
    (tmp_path / "real.txt").write_bytes(b"payload\n")
    (tmp_path / "thing").write_bytes(b"payload\n")
    before = hashed(tmp_path, "thing")["thing"]

    (tmp_path / "thing").unlink()
    (tmp_path / "thing").symlink_to("real.txt")

    assert hashed(tmp_path, "thing")["thing"] != before
    assert hashed(tmp_path, "thing")["thing"].startswith("120000:")


def test_a_dangling_symlink_is_recorded_not_called_unreadable(tmp_path: Path):
    """**A permanent refusal, before this.** git commits a dangling link
    perfectly happily — the link text is right there. Recording `unreadable`
    made `wring deliver` refuse, and re-running `wring verify` recorded
    `unreadable` again, so nothing the user could do cleared it."""
    (tmp_path / "link").symlink_to("nowhere-at-all")

    assert hashed(tmp_path, "link") == {
        "link": f"120000:{sha(b'nowhere-at-all')}"
    }


def test_a_symlink_to_a_directory_is_recorded_too(tmp_path: Path):
    (tmp_path / "adir").mkdir()
    (tmp_path / "link").symlink_to("adir")

    assert hashed(tmp_path, "link") == {"link": f"120000:{sha(b'adir')}"}


def test_a_symlink_to_a_fifo_does_not_hang(tmp_path: Path):
    """**The hang.** `open("rb")` on a link to a pipe blocks until someone
    writes, and nobody ever does — `wring verify` never returned. `readlink`
    never touches the pipe.

    Bounded on a daemon thread: a regression must fail this test, not wedge
    the suite.
    """
    os.mkfifo(tmp_path / "pipe")
    (tmp_path / "link").symlink_to("pipe")

    assert bounded(lambda: hashed(tmp_path, "link")) == {
        "link": f"120000:{sha(b'pipe')}"
    }


# --- what cannot be recorded ----------------------------------------------


def test_a_path_git_would_not_commit_records_unsupported(tmp_path: Path):
    """Neither a regular file nor a symlink. git will not put it in a commit
    either — `git add` on a bare FIFO stores nothing — so `unsupported` is
    the honest record and `wring deliver` refuses on it.

    Unreachable through `git status`, which does not list such paths at all
    (measured). It is here because `hash_untracked` must not be able to
    invent a digest for an object that has none.
    """
    os.mkfifo(tmp_path / "pipe")

    assert bounded(lambda: hashed(tmp_path, "pipe")) == {
        "pipe": evidence.UNSUPPORTED
    }


def test_a_regular_file_that_cannot_be_read_is_still_unreadable(tmp_path: Path):
    """`unreadable` survives, but it now means what it says: a real OSError
    on a real file. It stopped being the answer for three cases that were
    perfectly readable."""
    target = tmp_path / "secret.txt"
    target.write_bytes(b"x\n")
    target.chmod(0o000)
    try:
        if os.access(target, os.R_OK):  # root, or a filesystem without modes
            pytest.skip("this user can read a 0000 file")
        assert hashed(tmp_path, "secret.txt") == {
            "secret.txt": evidence.UNREADABLE
        }
    finally:
        target.chmod(0o644)


def test_a_path_that_is_not_there_at_all_is_unreadable(tmp_path: Path):
    assert hashed(tmp_path, "gone.txt") == {"gone.txt": evidence.UNREADABLE}


# --- the recorded shape ----------------------------------------------------


def test_every_recorded_value_names_the_mode_and_the_payload(tmp_path: Path):
    """Mode and digest in ONE string, so the schema's `additionalProperties`
    stays a simple pattern and a type flip is a digest change by
    construction rather than by a reader remembering to compare two keys."""
    (tmp_path / "plain.txt").write_bytes(b"a\n")
    (tmp_path / "run.sh").write_bytes(b"b\n")
    (tmp_path / "run.sh").chmod(0o755)
    (tmp_path / "link").symlink_to("plain.txt")

    recorded = hashed(tmp_path, "plain.txt", "run.sh", "link")

    modes = {path: value.split(":")[0] for path, value in recorded.items()}
    assert modes == {
        "plain.txt": "100644", "run.sh": "100755", "link": "120000"
    }
    for value in recorded.values():
        digest = value.split(":")[1]
        assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")


def test_the_recorded_payload_is_the_one_git_would_store(tmp_path: Path):
    """The end of the argument: hash what `git cat-file` prints for the blob
    git actually wrote. If these agree, `untracked.json` is keyed on the
    delivered object by construction rather than by assertion.
    """
    root = tmp_path / "repo"
    root.mkdir()
    run = ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid"]
    subprocess.run([*run, "init", "-q", "-b", "main", "."], cwd=root, check=True,
                   capture_output=True)
    (root / "plain.txt").write_bytes(b"hello\n")
    (root / "run.sh").write_bytes(b"#!/bin/sh\n")
    (root / "run.sh").chmod(0o755)
    (root / "link").symlink_to("plain.txt")
    (root / "dangling").symlink_to("nowhere")
    names = ["plain.txt", "run.sh", "link", "dangling"]
    subprocess.run([*run, "add", "--", *names], cwd=root, check=True,
                   capture_output=True)

    listed = subprocess.run(
        [*run, "ls-files", "-s"], cwd=root, check=True, capture_output=True,
        text=True,
    ).stdout
    from_git = {}
    for line in listed.splitlines():
        mode, blob, rest = line.split(" ", 2)
        path = rest.split("\t", 1)[1]
        payload = subprocess.run(
            [*run, "cat-file", "-p", blob], cwd=root, check=True,
            capture_output=True,
        ).stdout
        from_git[path] = f"{mode}:{sha(payload)}"

    assert hashed(root, *names) == from_git


def test_the_stored_mode_matches_what_lstat_says(tmp_path: Path):
    """A symlink is never followed — proved by the mode, which is the one
    thing `stat` and `lstat` disagree about for every link."""
    (tmp_path / "target.txt").write_bytes(b"x\n")
    (tmp_path / "link").symlink_to("target.txt")

    assert stat.S_ISLNK(os.lstat(tmp_path / "link").st_mode)
    assert stat.S_ISREG(os.stat(tmp_path / "link").st_mode)
    assert hashed(tmp_path, "link")["link"].startswith("120000:")
