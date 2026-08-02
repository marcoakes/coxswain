"""Bring work in — `wring get` and `wring issue` (SPEC_GET_V0.md §§3-4).

Two commands that turn a URL into something on disk. Neither runs anything it
fetched: a fresh clone is untrusted input, and `.wringer.yaml` is code
(SECURITY.md). Cloning a repository and then running its gates would be the
whole warning, ignored.

`wring get` is the one place Wringer writes a git repository — but it *creates*
one rather than changing one, so the amended law 6 is not even reached. The
history it writes is the history it just downloaded.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wringer import evidence

ACQUIRED_DIRNAME = Path(".wringer") / "acquired"
SCHEMA_VERSION = "wringer.acquired.v1"
MANIFEST_FILENAME = "manifest.json"

# A clone can be slow, but it cannot be unbounded — the fleet's lesson.
CLONE_TIMEOUT_SECONDS = 900

# Schemes a repository may be cloned from. `file://` is here because it is how
# the test suite clones without a network; git's own transport list is much
# longer and includes several nobody should reach by accident.
ALLOWED_SCHEMES = ("https", "ssh", "file")

# `git@host:owner/name.git` — scp-style, which has no scheme at all.
_SCP_STYLE = re.compile(r"^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:[^/].*$")


class AcquireError(Exception):
    """The work could not be brought in (CLI exit code 2)."""


@dataclass(frozen=True)
class Acquired:
    directory: Path
    origin: str
    head_sha: str | None
    default_branch: str | None


def check_url(url: str) -> None:
    """Refuse a clone URL before it reaches a subprocess.

    Credentials in a URL are refused for `judge.endpoint`'s reason: this
    string is recorded. An unexpected scheme is refused because git speaks
    more transports than anyone means to enable.
    """
    if not url.strip():
        raise AcquireError("no URL given")
    if _SCP_STYLE.match(url.strip()):
        if "@" in url.split(":", 1)[0] and url.count("@") > 1:
            raise AcquireError("the URL must not carry credentials")
        return

    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise AcquireError(
            f"'{parsed.scheme or 'no scheme'}' is not a scheme Wringer clones "
            f"from — use one of: {', '.join(ALLOWED_SCHEMES)}, or git@host:path"
        )
    # A password is always a credential. A *username* is one only over http(s),
    # where `https://<token>@host/...` is exactly how people paste tokens — over
    # ssh, `ssh://git@host/...` is the ordinary form and carries no secret.
    # Refusing that would have refused the commonest clone URL there is.
    if parsed.password:
        raise AcquireError(
            "the URL must not carry a password — it is recorded in the "
            "acquisition manifest. Let git's own credential helper answer"
        )
    if parsed.username and parsed.scheme in ("http", "https"):
        raise AcquireError(
            "the URL must not carry a username over http(s) — that is how a "
            "token gets pasted, and this URL is recorded in the acquisition "
            "manifest. Let git's own credential helper answer"
        )


def destination(url: str, workspace: Path, into: str | None) -> Path:
    """Where the clone lands. Named from the URL unless a human said."""
    if into:
        return Path(into).expanduser()
    tail = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    name = tail[:-4] if tail.endswith(".git") else tail
    if not name or name in (".", ".."):
        raise AcquireError(f"cannot work out a directory name from {url!r}")
    return workspace / name


def clone(url: str, target: Path) -> Acquired:
    """Clone, then record where the working copy came from.

    A full clone, not a shallow one: delivery needs history, and a repo that
    cannot be branched from is not much of an acquisition.
    """
    if target.exists() and any(target.iterdir()):
        raise AcquireError(
            f"{target} exists and is not empty — refusing to clone over it"
        )
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        proc = subprocess.run(
            ["git", "clone", "--", url, str(target)],
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AcquireError(
            f"the clone did not finish in {CLONE_TIMEOUT_SECONDS}s"
        ) from exc
    except OSError as exc:
        raise AcquireError(f"could not run git: {exc}") from exc

    if proc.returncode != 0:
        raise AcquireError(
            f"git clone failed (exit {proc.returncode}): "
            f"{proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else ''}"
        )

    return Acquired(
        directory=target,
        origin=url,
        head_sha=_read(["rev-parse", "HEAD"], target),
        default_branch=default_branch(target),
    )


def default_branch(root: Path, remote: str = "origin") -> str | None:
    """The remote's default branch, or None if it cannot be determined.

    None is a refusal upstream, never a guess: SPEC_GET_V0.md §1 forbids
    touching the default branch, and a branch you could not name is not one
    you can be sure you avoided.
    """
    head = _read(["symbolic-ref", f"refs/remotes/{remote}/HEAD"], root)
    if head:
        return head.rsplit("/", 1)[-1]
    shown = _read(["remote", "show", remote], root)
    if shown:
        for line in shown.splitlines():
            if "HEAD branch:" in line:
                name = line.split("HEAD branch:", 1)[1].strip()
                return name if name and name != "(unknown)" else None
    return None


def _read(args: list[str], cwd: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def record(root: Path, acquired: Acquired, redactor: object = None) -> Path:
    """Write `.wringer/acquired/<id>/manifest.json`.

    A working copy that cannot say where it came from is the provenance gap
    P5 closes. This is the half of it that costs nothing today.
    """
    started = datetime.now().astimezone()
    directory = root / ACQUIRED_DIRNAME / evidence.new_run_id(started)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AcquireError(f"cannot create {directory}: {exc}") from exc

    payload = {
        "schema_version": SCHEMA_VERSION,
        "acquired_at": started.replace(microsecond=0).isoformat(),
        "origin": acquired.origin,
        "directory": str(acquired.directory),
        "head_sha": acquired.head_sha,
        "default_branch": acquired.default_branch,
    }
    path = directory / MANIFEST_FILENAME
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
