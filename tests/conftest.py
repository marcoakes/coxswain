"""Shared fixtures — scratch git repos to run gates in."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wringer import config

# Never inherit the developer's identity, hooks, or signing config: a test
# repo must behave the same on every machine and in CI.
_ISOLATED = [
    "-c",
    "user.name=wringer test",
    "-c",
    "user.email=wringer@example.invalid",
    "-c",
    "commit.gpgsign=false",
]


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    """Run git in a scratch repo. `check=False` for commands whose failure is
    the point — a conflicted merge, say."""
    proc = subprocess.run(
        ["git", *_ISOLATED, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )
    return proc.stdout.strip()


@pytest.fixture
def git_run():
    """Run an isolated git command in a scratch repo; returns its stdout."""
    return _git


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo on `main` with one empty commit — a clean starting point.

    The identity is written into the repo's own config, not just passed with
    `-c` on the fixture's calls: `wring deliver` runs `git commit` the way a
    user's git is configured, and a real user has an identity. Without this the
    suite passes on macOS — where git invents `user@host` — and fails on
    GitHub's Linux runners, where the hostname is not fully qualified and git
    refuses to guess. That divergence cost a red build; keep it.
    """
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "wringer test")
    _git(tmp_path, "config", "user.email", "wringer@example.invalid")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "initial commit")
    return tmp_path


@pytest.fixture
def write_config():
    """Write a `.wringer.yaml` into a directory and return its path."""

    def _write(directory: Path, body: str) -> Path:
        path = directory / config.CONFIG_FILENAME
        path.write_text(body, encoding="utf-8")
        return path

    return _write


def flat(text: str) -> str:
    """Collapse whitespace in captured output before matching on it.

    Refusals are wrapped to the terminal (`cli._wrap_message`), so a phrase can
    legitimately straddle a line break. Asserting on the exact line-breaking of
    prose tests the formatter rather than the message — and the formatter has
    its own tests.
    """
    return " ".join(text.split())
