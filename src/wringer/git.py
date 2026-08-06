"""Git state: what the run was verifying, and what had changed.

Records the repo root, HEAD SHA, branch, dirty flag, the changed and
untracked path lists, and the two captured artifacts a reviewer actually
reads — `diff.patch` and `status.txt`.

Every git call here is read-only, bounded, and never fatal: outside a
repository — or with no git binary at all — `wring verify` still runs the
gates and records nulls. (Formally refusing with exit 3 is a Day-4
decision.)
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# A wedged `git` (a stale index lock, a credential prompt, a network remote)
# must not hang the verifier. Every internal call is bounded; a call that
# overruns is treated exactly like a call that failed.
GIT_TIMEOUT_SECONDS = 10

# Paths git leaves inside .git while an operation is unfinished, and the
# word for what the developer is in the middle of.
_IN_PROGRESS = {
    "MERGE_HEAD": "a merge",
    "rebase-merge": "a rebase",
    "rebase-apply": "a rebase",
    "CHERRY_PICK_HEAD": "a cherry-pick",
    "REVERT_HEAD": "a revert",
    "BISECT_LOG": "a bisect",
}


@dataclass(frozen=True)
class RepoState:
    root: Path
    head_sha: str | None
    branch: str | None
    dirty: bool
    # Paths relative to the repo root. `changed_files` is what git is already
    # tracking; `untracked` is what it has never seen — kept apart because a
    # patch can only describe the first kind.
    changed_files: tuple[str, ...] = ()
    untracked: tuple[str, ...] = ()


def find_root(start: Path) -> Path:
    """The git work-tree root containing `start`, or `start` itself."""
    toplevel = _git(["rev-parse", "--show-toplevel"], cwd=start)
    return Path(toplevel) if toplevel else start


def inspect(root: Path) -> RepoState:
    """Snapshot `root`'s git state. Call before writing the bundle, so the
    bundle's own directory is not what makes the tree look dirty."""
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    # `-uall`, not git's default `-unormal`, and not the repo's preference.
    #
    # By default git collapses an untracked DIRECTORY into a single entry —
    # `newdir/` rather than `newdir/a.txt`, `newdir/b.txt`. A bundle recording
    # the collapsed form describes the tree with a name that stays identical
    # however the directory's contents change, so `wring deliver`'s comparison
    # of the verified file set against the current one could not see a file
    # appear inside it. Reproduced 2026-08-05: a file created AFTER the gates
    # ran was committed and pushed on the delivery branch, at any nesting
    # depth, while the patch shown to the approving human was zero bytes —
    # because `diff_untracked` skips a directory too.
    #
    # Passing the flag explicitly also stops the repo's own
    # `status.showUntrackedFiles` setting from deciding what a bundle records:
    # a machine configured with `all` was accidentally immune to that hole,
    # which is no way to own a safety property.
    porcelain = _git(
        ["status", "--porcelain", "-z", "--untracked-files=all"],
        cwd=root,
        strip=False,
    )
    changed, untracked = _parse_status(porcelain)
    return RepoState(
        root=root,
        head_sha=_git(["rev-parse", "HEAD"], cwd=root),
        branch=None if branch == "HEAD" else branch,  # detached
        dirty=bool(changed or untracked),
        changed_files=changed,
        untracked=untracked,
    )


def is_repo(root: Path) -> bool:
    return _git(["rev-parse", "--is-inside-work-tree"], cwd=root) == "true"


def in_progress(root: Path) -> str | None:
    """The half-finished git operation in this tree, if any.

    Verifying in the middle of a merge or rebase produces evidence about a
    state nobody chose: the tree is a machine's intermediate, HEAD is not
    where the developer thinks it is, and a "passing" run would be a claim
    about a commit that does not exist yet.
    """
    git_dir = _git(["rev-parse", "--git-dir"], cwd=root)
    if git_dir is None:
        return None
    base = Path(git_dir)
    if not base.is_absolute():
        base = root / base

    for marker, description in _IN_PROGRESS.items():
        if (base / marker).exists():
            return description
    return None


def diff(root: Path, head_sha: str | None) -> str | None:
    """Staged and unstaged changes as one patch; None outside a repo.

    Untracked files are deliberately absent — git cannot diff what it has
    never seen. They are listed in `status.txt` and the `git.status` event
    instead, so a reader is never misled into thinking a new file's contents
    were captured here.

    Binary content stays out: git says "Binary files … differ" by default,
    and `--no-textconv` stops a repo's own `.gitattributes` from converting
    a blob into text that would then land in the bundle. An evidence file
    should not be able to grow a megabyte of image on someone else's say-so.
    """
    against = ["HEAD"] if head_sha else []
    return _git(
        ["diff", "--no-color", "--no-ext-diff", "--no-textconv", *against],
        cwd=root,
        strip=False,
    )


def diff_untracked(root: Path, paths: tuple[str, ...]) -> str:
    """A new-file patch for files git has never seen.

    `git diff` cannot show them — the reason `diff.patch` is deliberately
    silent about untracked content in an evidence bundle. But a *delivery*
    plan is read by a human deciding whether to publish, and a change made
    entirely of new files rendered an empty patch: approving `--send` on it
    meant approving nothing.

    `--no-index` gets a real diff without staging anything, so the dry run
    still touches git's index not at all. Binary files come back as git's own
    "Binary files differ" line rather than as bytes.
    """
    chunks: list[str] = []
    for path in paths:
        if not (root / path).is_file():
            continue
        # --no-index exits 1 when the files differ, which is always here.
        text = _git(
            ["diff", "--no-color", "--no-ext-diff", "--no-textconv",
             "--no-index", "--", os.devnull, path],
            cwd=root,
            strip=False,
            allow_failure=True,
        )
        if text:
            chunks.append(text)
    return "".join(chunks)


def status(root: Path) -> str | None:
    """`git status --porcelain`; None outside a repo.

    The porcelain form, not the prose one: it is stable across git versions
    and locales, which a bundle needs more than it needs friendly wording.
    """
    return _git(["status", "--porcelain"], cwd=root, strip=False)


def _parse_status(porcelain: str | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split `git status --porcelain -z` into changed and untracked paths.

    NUL-separated because paths may contain spaces or quotes, which the
    default porcelain format escapes and we would then have to unescape.
    """
    if not porcelain:
        return (), ()

    entries = [entry for entry in porcelain.split("\0") if entry]
    changed: list[str] = []
    untracked: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        code, path = entry[:2], entry[3:]  # "XY path"
        index += 1
        if "R" in code or "C" in code:
            # A rename or copy is followed by its source path in the NEXT
            # NUL-separated entry. Both paths are changes.
            #
            # BOTH columns are tested, not just the index one. Measured on
            # git 2.50.1, a rename wears three codes — `R ` from `git mv`,
            # ` R` from a rename made in an editor and then declared with
            # `git add -N`, and `RM` from `git mv` plus an edit. Reading the
            # index column alone missed the middle one, and missing it did
            # not merely lose a path: with the two-entry shape unrecognised
            # the source was parsed as a status line of its own, so
            # `entry[3:]` sliced a 3-character path down to the empty string.
            # That empty string then vanished into the NUL join that builds
            # `wring deliver`'s pathspec, `git commit --only` never named the
            # deletion, and the delivered branch kept a file the gates had
            # seen removed — silently, which is the whole problem.
            #
            # This used to skip the source, reasoning that the new path is
            # the one that exists now. True of the source as a *file*, false
            # of it as a *change*: `git mv src dst` deletes src, and a bundle
            # that omits the deletion describes a tree nobody verified.
            #
            # The cost was not cosmetic. `wring deliver` builds its commit
            # pathspec from this list, so an unrecorded deletion was never
            # committed: the delivered branch carried BOTH files while the
            # run's own diff.patch recorded a rename — the merge request
            # attesting a rename its branch did not contain.
            #
            # A copy's source is not deleted, so recording it is redundant
            # rather than wrong; git only emits `C` with -C/--find-copies
            # enabled, which this call does not pass, so the branch is
            # effectively rename-only. Kept together because the porcelain
            # two-entry shape is identical and splitting them would invite
            # the next reader to "simplify" one of them away.
            if index < len(entries):
                changed.append(entries[index])
                index += 1
        if code == "??":
            untracked.append(path)
        else:
            changed.append(path)
    return tuple(changed), tuple(untracked)


def _git(
    args: list[str],
    cwd: Path,
    strip: bool = True,
    allow_failure: bool = False,
) -> str | None:
    """Run a read-only git command; None if git or the repo is unavailable.

    `strip=False` matters for anything whose leading whitespace is data:
    porcelain status codes are two columns, and ` M file` means something
    different from `M  file`.

    `allow_failure` is for the commands whose *non-zero* exit is the normal
    answer — `diff --no-index` exits 1 whenever the files differ, which for a
    new-file diff is always.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except OSError:  # no git on PATH, cwd gone
        return None
    except subprocess.TimeoutExpired:  # wedged git — record nulls, keep going
        return None
    if proc.returncode != 0 and not allow_failure:
        return None
    return proc.stdout.strip() if strip else proc.stdout
