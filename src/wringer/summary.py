"""Render `summary.md` — the human's entry point into a bundle.

Boring, stable, grep-friendly (SPEC_VERIFY_V0.md §The evidence
bundle): one screen that says what ran, against which commit, what it
cost, what failed, where the logs are, and the exact command that reruns
the failure. Machines get `evidence.jsonl` and `manifest.json`; this file
is for the person reviewing the change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wringer import detect, evidence
from wringer.config import Gate
from wringer.evidence import Bundle
from wringer.gates import GateResult
from wringer.git import RepoState

# Named in evidence.py with the bundle's other filenames, and re-exported
# here because this module is the one that writes it.
SUMMARY_FILENAME = evidence.SUMMARY_FILENAME


@dataclass(frozen=True)
class Interrupted:
    """The gate that was running when the run stopped.

    It has no `GateResult` and no `result.json`: it never finished, and
    inventing a verdict for it would be a lie. What it does have is a
    directory holding whatever it printed before it was killed.
    """

    gate: Gate
    directory: Path


def write(
    bundle: Bundle,
    state: RepoState,
    results: list[GateResult],
    skipped: list[Gate],
    failed_gate: str | None,
    status: str = "passed",
    interrupted: Interrupted | None = None,
    template_only: bool = False,
    vacuity: Any = None,
) -> Path:
    """Write `summary.md` into the bundle and return its path."""
    lines = [
        f"# wring verify — {bundle.run_id}",
        "",
        _repo_line(state),
        f"- started: {bundle.started_at.replace(microsecond=0).isoformat()}",
        _result_line(status, failed_gate),
    ]
    changes = _changes_line(state)
    if changes is not None:
        lines.append(changes)
    # Before the table, because the table is the part that looks like proof.
    # A bundle whose result says `passed` must not be readable as "verified"
    # when the only gate that ran was the placeholder — the terminal saying
    # so is not enough, since the bundle is what outlives the terminal and
    # what a reviewer is handed.
    if template_only:
        lines += ["", f"> ⚠ **{detect.TEMPLATE_WARNING}**"]
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
    # The gate a Ctrl-C caught mid-flight: it ran, so "skipped" would be
    # false, and it never finished, so no status is available. It gets its
    # own word and keeps its place in the order.
    if interrupted is not None:
        lines.append(
            f"| {interrupted.gate.id} | interrupted | — "
            f"| {_partial_logs(bundle, interrupted.directory)} |"
        )
    # Gates after a required failure never ran: named here, absent from
    # evidence.jsonl, so the summary is the one place the whole declared
    # set is visible.
    for gate in skipped:
        lines.append(f"| {gate.id} | skipped | — | — |")

    if vacuity is not None:
        lines += _vacuity_section(vacuity)

    if failed_gate is not None:
        lines += [
            "",
            "Rerun the failing gate:",
            "",
            "```",
            f"wring verify --gate {failed_gate}",
            "```",
        ]

    path = bundle.directory / SUMMARY_FILENAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _vacuity_section(result: Any) -> list[str]:
    """What `--prove` found, per gate, with each `sensitive` row citing why.

    The citation is the load-bearing part, not decoration. A detached
    worktree carries tracked files only, so in a repo whose dependencies are
    gitignored EVERY pre-change gate fails on a missing environment — and the
    comparison reads that as proof. `ModuleNotFoundError: No module named
    'yourproject'` in the row is what makes a false `proven` legible at a
    glance instead of convincing.
    """
    from wringer import vacuity as vacuity_module

    verdict = result.verdict
    lines = ["", f"## Vacuity — **{verdict}**", "", result.reason, ""]
    if result.setup and not result.setup.get("ok"):
        lines += [
            f"`run.prove_setup` (`{result.setup['command']}`) failed: "
            f"{result.setup.get('cites')}",
            "",
        ]
    if result.rows:
        lines += [
            "| gate | changed tree | pre-change tree | tests this change | "
            "because |",
            "|---|---|---|---|---|",
        ]
        for row in result.rows:
            lines.append(
                f"| {row.gate_id} | {row.changed} | {row.pre_change} "
                f"| {'yes' if row.sensitive else 'NO'} "
                f"| {row.cites or '—'} |"
            )
        lines.append("")
    if verdict == vacuity_module.GATES_VACUOUS:
        lines += [
            "> ⚠ **Every required gate passed without the change too, so they "
            "proved nothing about it.** Write a test that fails without your "
            "change, then verify again.",
            "",
        ]
    lines.append(
        f"Both trees' output: [`{vacuity_module.VACUITY_DIRNAME}/`]"
        f"({vacuity_module.VACUITY_DIRNAME}/) · "
        f"worktree {result.worktree_ms}ms, prove {result.prove_ms}ms"
    )
    return lines


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


def _partial_logs(bundle: Bundle, gate_dir: Path) -> str:
    """Links for a gate that was killed before it finished.

    Only to files that exist: a gate stopped before it wrote anything leaves
    an empty directory, and a link to a missing log is worse than no link.
    """
    links = [
        f"[{name}]({bundle.relative(path)})"
        for name in ("stdout", "stderr")
        if (path := gate_dir / f"{name}.log").is_file()
    ]
    return " · ".join(links) if links else "—"


def _logs(bundle: Bundle, result: GateResult) -> str:
    return " · ".join(
        f"[{name}]({bundle.relative(path)})"
        for name, path in (
            ("stdout", result.stdout_path),
            ("stderr", result.stderr_path),
        )
    )
