"""Check the preconditions, one line each — `wring doctor`.

This exists for the agent that is setting Wringer up for somebody. An agent
with a broken environment and no diagnosis will guess, and a guessing agent
burns a person's afternoon. Every check here answers one question, says what
to do when the answer is wrong, and is machine-readable under `--json`.

It never fixes anything. Diagnosis and repair are different jobs, and a tool
that silently "fixes" a machine is a tool nobody can reason about.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from wringer import __version__, config, evidence

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class Check:
    """One question, its answer, and what to do about it.

    `status` is `ok`, `warn` (usable but worth knowing) or `fail` (this will
    stop you). Only `fail` changes the exit code — a warning that blocks a
    setup script is a warning nobody keeps.
    """

    name: str
    status: str
    detail: str
    fix: str = ""

    @property
    def passed(self) -> bool:
        return self.status != FAIL


def run_checks(root: Path) -> list[Check]:
    return [
        _python(),
        _wring(),
        _git(),
        _runtime(),
        _repo(root),
        _config(root),
        _workspace(root),
        _api_key(),
    ]


def _python() -> Check:
    major, minor = platform.python_version_tuple()[:2]
    version = platform.python_version()
    if (int(major), int(minor)) < (3, 11):
        return Check(
            "python", FAIL, f"Python {version} — Wringer needs 3.11 or newer",
            "Install Python 3.11+ (or use the container image, which bundles it)",
        )
    return Check("python", OK, f"Python {version}")


def _wring() -> Check:
    found = shutil.which("wring")
    if found is None:
        # Reachable when someone runs `python -m wringer doctor` from a
        # source tree without installing — worth flagging, not fatal.
        return Check(
            "wring", WARN, f"wringer {__version__} is importable but `wring` "
            "is not on PATH",
            "pip install wringer, or add the venv's bin directory to PATH",
        )
    return Check("wring", OK, f"wring {__version__} at {found}")


def _git() -> Check:
    if shutil.which("git") is None:
        return Check(
            "git", FAIL, "git is not on PATH — Wringer records which commit "
            "was verified, so it needs one",
            "Install git",
        )
    try:
        proc = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=10
        )
        return Check("git", OK, proc.stdout.strip() or "git present")
    except (OSError, subprocess.TimeoutExpired):
        return Check("git", FAIL, "git is on PATH but did not run", "Reinstall git")


def _runtime() -> Check:
    """A container runtime, if the user wants one. Not required to run
    Wringer directly — only to run it in the box."""
    apple = shutil.which("container")
    docker = shutil.which("docker")
    mac_arm = platform.system() == "Darwin" and platform.machine() == "arm64"

    if apple is not None:
        return Check("container runtime", OK, f"apple container at {apple}")
    if docker is not None:
        return Check("container runtime", OK, f"docker at {docker}")
    if mac_arm:
        return Check(
            "container runtime", WARN,
            "no container runtime found (Apple silicon detected)",
            "Install apple/container (needs macOS 26) or Docker Desktop — "
            "or skip the container and run wring directly",
        )
    return Check(
        "container runtime", WARN, "no container runtime found",
        "Install Docker, or run wring directly on this machine",
    )


def _repo(root: Path) -> Check:
    inside = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=root, capture_output=True, text=True,
    )
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return Check(
            "git repository", FAIL, f"{root} is not a git repository",
            "cd into your repo, or run: git init",
        )
    return Check("git repository", OK, f"{root}")


def _config(root: Path) -> Check:
    path = root / config.CONFIG_FILENAME
    if not path.is_file():
        return Check(
            "gates", WARN, f"no {config.CONFIG_FILENAME} here yet",
            "Run: wring init",
        )
    try:
        cfg = config.load(path)
    except config.ConfigError as exc:
        return Check("gates", FAIL, f"{config.CONFIG_FILENAME} is invalid: {exc}",
                     f"Fix {config.CONFIG_FILENAME}")
    gates = ", ".join(gate.id for gate in cfg.gates)
    extras = [
        name for name, present in
        (("run", cfg.run), ("judge", cfg.judge), ("fleet", cfg.fleet))
        if present is not None
    ]
    detail = f"{len(cfg.gates)} gate(s): {gates}"
    if extras:
        detail += f"; also configured: {', '.join(extras)}"
    return Check("gates", OK, detail)


def _workspace(root: Path) -> Check:
    """Wringer writes evidence. A read-only mount is a common container
    mistake and produces a confusing failure much later."""
    probe = root / evidence.RUNS_DIRNAME.parts[0]
    try:
        probe.mkdir(parents=True, exist_ok=True)
        token = probe / ".doctor-write-probe"
        token.write_text("ok", encoding="utf-8")
        token.unlink()
    except OSError as exc:
        return Check(
            "workspace writable", FAIL, f"cannot write to {probe}: {exc}",
            "Mount the workspace read-write (a container -v mount defaults "
            "to read-write; check for :ro)",
        )
    return Check("workspace writable", OK, f"{probe} is writable")


def _api_key() -> Check:
    """Only relevant once a judge or spec step is configured, so its absence
    is never fatal. Values are never printed — the name is the answer."""
    named = [
        name for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")
        if os.environ.get(name)
    ]
    if named:
        return Check("llm key", OK, f"set: {', '.join(named)} (value not shown)")
    return Check(
        "llm key", WARN, "no LLM API key in the environment",
        "Only needed for `wring judge --send`. Provide it when you launch, "
        "and never paste it to an agent",
    )


def report(checks: list[Check]) -> str:
    mark = {OK: "✓", WARN: "!", FAIL: "✗"}
    lines = []
    for check in checks:
        label = f"{mark[check.status]} {check.name}"
        lines.append(f"{label:<24}{check.detail}")
        if check.fix and check.status != OK:
            lines.append(f"{'':<24}→ {check.fix}")
    failed = [c for c in checks if c.status == FAIL]
    warned = [c for c in checks if c.status == WARN]
    lines.append("")
    if failed:
        lines.append(
            f"{len(failed)} blocking problem"
            f"{'' if len(failed) == 1 else 's'} — fix the ✗ lines above."
        )
    elif warned:
        lines.append("Ready. The ! lines are optional extras, not problems.")
    else:
        lines.append("Ready.")
    return "\n".join(lines)


def as_json(checks: list[Check]) -> str:
    return json.dumps(
        {
            "wringer_version": __version__,
            "ok": all(check.passed for check in checks),
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "detail": c.detail,
                    **({"fix": c.fix} if c.fix else {}),
                }
                for c in checks
            ],
        }
    )
