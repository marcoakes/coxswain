"""Render `summary.md` — the human's entry point into a bundle.

Boring, stable, grep-friendly (SPEC_COX_VERIFY_V0.md §The evidence
bundle): one screen that says what ran, against which commit, what it
cost, what failed, where the logs are, and the exact command that reruns
the failure. Machines get `evidence.jsonl` and `manifest.json`; this file
is for the person reviewing the change.
"""

from __future__ import annotations

from pathlib import Path

from cox import evidence
from cox.config import Gate
from cox.evidence import Bundle
from cox.gates import GateResult
from cox.git import RepoState

SUMMARY_FILENAME = "summary.md"


def write(
    bundle: Bundle,
    state: RepoState,
    results: list[GateResult],
    skipped: list[Gate],
    failed_gate: str | None,
    status: str = "passed",
) -> Path:
    """Write `summary.md` into the bundle and return its path."""
    lines = [
        f"# cox verify — {bundle.run_id}",
        "",
        _repo_line(state),
        f"- started: {bundle.started_at.replace(microsecond=0).isoformat()}",
        _result_line(status, failed_gate),
    ]
    changes = _changes_line(state)
    if changes is not None:
        lines.append(changes)
    lines += [
        "",
        "| gate | status | duration | logs |",
        "|---|---|---|---|",
    ]

    for result in results:
        lines.append(
            f"| {result.gate.id} | {_status(result)} "
            f"| {result.duration_ms / 1000:.1f}s | {_logs(bundle, result)} |"
        )
    # Gates after a required failure never ran: named here, absent from
    # evidence.jsonl, so the summary is the one place the whole declared
    # set is visible.
    for gate in skipped:
        lines.append(f"| {gate.id} | skipped | — | — |")

    if failed_gate is not None:
        lines += [
            "",
            "Rerun the failing gate:",
            "",
            "```",
            f"cox verify --gate {failed_gate}",
            "```",
        ]

    path = bundle.directory / SUMMARY_FILENAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _repo_line(state: RepoState) -> str:
    name = state.root.name or str(state.root)
    if state.head_sha is None:
        return f"- repo: **{name}** — not a git repository"
    return (
        f"- repo: **{name}** @ `{state.head_sha[:7]}` "
        f"(branch `{state.branch or 'detached HEAD'}`, "
        f"{'dirty' if state.dirty else 'clean'})"
    )


def _changes_line(state: RepoState) -> str | None:
    """Point the reader at the captured tree, with the counts up front."""
    if state.head_sha is None:
        return None  # nothing was captured, so promise nothing
    counts = [f"{len(state.changed_files)} changed"]
    if state.untracked:
        counts.append(f"{len(state.untracked)} untracked")
    return (
        f"- files: {', '.join(counts)} "
        f"([{evidence.DIFF_FILENAME}]({evidence.DIFF_FILENAME}), "
        f"[{evidence.STATUS_FILENAME}]({evidence.STATUS_FILENAME}))"
    )


def _result_line(status: str, failed_gate: str | None) -> str:
    if status == "interrupted":
        return "- result: **interrupted** — stopped before every gate ran"
    if failed_gate is None:
        return "- result: **passed** — all required gates passed"
    return f"- result: **failed** — required gate `{failed_gate}` failed"


def _status(result: GateResult) -> str:
    if result.passed:
        return "passed"
    label = "timed out" if result.timed_out else "failed"
    return f"{label} (optional)" if result.gate.optional else label


def _logs(bundle: Bundle, result: GateResult) -> str:
    return " · ".join(
        f"[{name}]({bundle.relative(path)})"
        for name, path in (
            ("stdout", result.stdout_path),
            ("stderr", result.stderr_path),
        )
    )
