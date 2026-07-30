"""Git state for the evidence manifest.

Day 1 records only what `manifest.json` declares: repo root, HEAD SHA,
branch, and whether the tree is dirty. The richer git evidence (changed
files, `diff.patch`, `status.txt`, untracked list) is the Day-3 bolt.

Every git call here is read-only, and a failure is never fatal: outside a
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


def find_root(start: Path) -> Path:
    """The git work-tree root containing `start`, or `start` itself."""
    toplevel = _git(["rev-parse", "--show-toplevel"], cwd=start)
    return Path(toplevel) if toplevel else start


def inspect(root: Path) -> RepoState:
    """Snapshot `root`'s git state. Call before writing the bundle, so the
    bundle's own directory is not what makes the tree look dirty."""
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    return RepoState(
        root=root,
        head_sha=_git(["rev-parse", "HEAD"], cwd=root),
        branch=None if branch == "HEAD" else branch,  # detached
        dirty=bool(_git(["status", "--porcelain"], cwd=root)),
    )


def _git(args: list[str], cwd: Path) -> str | None:
    """Run a read-only git command; None if git or the repo is unavailable."""
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
    return proc.stdout.strip()
