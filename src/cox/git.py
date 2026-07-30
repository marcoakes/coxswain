"""Git state: what the run was verifying, and what had changed.

Records the repo root, HEAD SHA, branch, dirty flag, the changed and
untracked path lists, and the two captured artifacts a reviewer actually
reads — `diff.patch` and `status.txt`.

Every git call here is read-only, bounded, and never fatal: outside a
repository — or with no git binary at all — `cox verify` still runs the
gates and records nulls. (Formally refusing with exit 3 is a Day-4
decision.)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# A wedged `git` (a stale index lock, a credential prompt, a network remote)
# must not hang the verifier. Every internal call is bounded; a call that
# overruns is treated exactly like a call that failed.
GIT_TIMEOUT_SECONDS = 10


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
    porcelain = _git(["status", "--porcelain", "-z"], cwd=root, strip=False)
    changed, untracked = _parse_status(porcelain)
    return RepoState(
        root=root,
        head_sha=_git(["rev-parse", "HEAD"], cwd=root),
        branch=None if branch == "HEAD" else branch,  # detached
        dirty=bool(changed or untracked),
        changed_files=changed,
        untracked=untracked,
    )


def diff(root: Path, head_sha: str | None) -> str | None:
    """Staged and unstaged changes as one patch; None outside a repo.

    Untracked files are deliberately absent — git cannot diff what it has
    never seen. They are listed in `status.txt` and the `git.status` event
    instead, so a reader is never misled into thinking a new file's contents
    were captured here.
    """
    against = ["HEAD"] if head_sha else []
    return _git(
        ["diff", "--no-color", "--no-ext-diff", *against], cwd=root, strip=False
    )


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
        if code[:1] in ("R", "C"):
            # A rename or copy is followed by its source path; the new path
            # is the one that exists now, so the source is not evidence.
            index += 1
        if code == "??":
            untracked.append(path)
        else:
            changed.append(path)
    return tuple(changed), tuple(untracked)


def _git(args: list[str], cwd: Path, strip: bool = True) -> str | None:
    """Run a read-only git command; None if git or the repo is unavailable.

    `strip=False` matters for anything whose leading whitespace is data:
    porcelain status codes are two columns, and ` M file` means something
    different from `M  file`.
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
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() if strip else proc.stdout
