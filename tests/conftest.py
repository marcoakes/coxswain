"""Shared fixtures — scratch git repos to run gates in."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cox import config

# Never inherit the developer's identity, hooks, or signing config: a test
# repo must behave the same on every machine and in CI.
_ISOLATED = [
    "-c",
    "user.name=cox test",
    "-c",
    "user.email=cox@example.invalid",
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
    """A git repo on `main` with one empty commit — a clean starting point."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "initial commit")
    return tmp_path


@pytest.fixture
def write_config():
    """Write a `.cox.yaml` into a directory and return its path."""

    def _write(directory: Path, body: str) -> Path:
        path = directory / config.CONFIG_FILENAME
        path.write_text(body, encoding="utf-8")
        return path

    return _write
