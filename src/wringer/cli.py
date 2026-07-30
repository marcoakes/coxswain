"""wring — command-line entry points.

Exit codes are contract (SPEC_VERIFY_V0.md):
0 = all required gates passed · 1 = a required gate failed ·
2 = config or environment error · 3 = unsafe dirty state / refused
precondition · 4 = interrupted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wringer import (
    __version__,
    config,
    detect,
    evidence,
    gates,
    git,
    loop,
    summary,
    verify,
)

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_CONFIG = 2
EXIT_REFUSED = 3
EXIT_INTERRUPTED = 4

# How much of a failing gate's logs to put on the console. The whole log is
# in the bundle; this is just enough to see what broke without opening it.
LOG_TAIL_LINES = 20

# `wring explain` is meant to be compact; a 400-file diff is a scroll, not a
# diagnosis.
EXPLAIN_FILE_LIMIT = 20


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wring",
        description=(
            "One command that proves whether this change is mergeable, "
            "and leaves behind evidence a human or agent can inspect."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"wring {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_init = subparsers.add_parser(
        "init", help=f"write a commented {config.CONFIG_FILENAME} template"
    )
    parser_init.set_defaults(func=cmd_init)

    parser_verify = subparsers.add_parser(
        "verify", help="run the declared gates and write an evidence bundle"
    )
    parser_verify.add_argument(
        "--gate",
        metavar="ID",
        help="run only this gate instead of every declared gate",
    )
    parser_verify.add_argument(
        "--output",
        metavar="DIR",
        help="write the bundle here instead of a new .wringer/runs/<run_id>/",
    )
    parser_verify.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human report",
    )
    parser_verify.set_defaults(func=cmd_verify)

    parser_run = subparsers.add_parser(
        "run",
        help="loop: verify, hand the failure to your worker, verify again",
    )
    parser_run.add_argument(
        "--max-iterations",
        type=int,
        metavar="N",
        help="override the config's max_iterations for this run",
    )
    parser_run.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human report",
    )
    parser_run.set_defaults(func=cmd_run)

    parser_explain = subparsers.add_parser(
        "explain",
        help="diagnose the latest (or a named) run — no LLM involved",
    )
    parser_explain.add_argument(
        "run",
        nargs="?",
        metavar="RUN_DIR",
        help="a run directory; defaults to the most recent one",
    )
    parser_explain.set_defaults(func=cmd_explain)

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    root = Path.cwd()
    target = root / config.CONFIG_FILENAME
    if target.exists():
        print(
            f"wring init: refusing to overwrite existing {target.name}",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    detection = detect.detect(root)
    target.write_text(detect.template(detection), encoding="utf-8")

    if detection.found:
        gates = ", ".join(candidate.id for candidate in detection.candidates)
        print(
            f"Wrote {target.name} from {', '.join(detection.sources)} — "
            f"gates: {gates}"
        )
        print("Check they are the commands you want proven, then: wring verify")
    else:
        print(
            f"Wrote {target.name} — nothing to detect here, so it is a "
            "template. Replace the example gates, then run: wring verify"
        )

    ignored = _ignore_runs(root)
    if ignored is not None:
        print(f"Added {evidence.RUNS_DIRNAME.parts[0]}/ to {ignored}")
    return EXIT_OK


def _ignore_runs(root: Path) -> str | None:
    """Keep evidence out of git.

    Bundles hold raw gate output, so a repo that commits them is one
    `git push` away from publishing whatever a gate printed. Returns the
    file written, or None if it was already handled.
    """
    entry = f"{evidence.RUNS_DIRNAME.parts[0]}/"
    gitignore = root / ".gitignore"

    if gitignore.is_file():
        existing = gitignore.read_text(encoding="utf-8")
        if entry in existing.split():
            return None
        separator = "" if existing.endswith("\n") or not existing else "\n"
        gitignore.write_text(
            f"{existing}{separator}\n# Wringer evidence stays local\n{entry}\n",
            encoding="utf-8",
        )
        return ".gitignore"

    gitignore.write_text(
        f"# Wringer evidence stays local\n{entry}\n", encoding="utf-8"
    )
    return ".gitignore"


def cmd_verify(args: argparse.Namespace) -> int:
    root = git.find_root(Path.cwd())

    refused = _refuse_unverifiable(root, "verify")
    if refused is not None:
        return refused

    try:
        cfg = config.load(root / config.CONFIG_FILENAME)
        planned = verify.plan(cfg, args.gate)
    except config.ConfigError as exc:
        print(f"wring verify: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    try:
        outcome = verify.run(
            root,
            cfg,
            planned,
            output=args.output,
            # Printed as each gate finishes, so a long run reports as it
            # happens; --json wants one object and nothing else.
            on_gate=None if args.json else _report_gate,
        )
    except evidence.EvidenceError as exc:
        print(f"wring verify: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if args.json:
        _report_json(outcome.bundle, root, outcome.failed_gate, outcome.status)
    else:
        _report_run(
            outcome.bundle, root, outcome.results, outcome.failed_gate, outcome.status
        )

    if outcome.interrupted is not None:
        return EXIT_INTERRUPTED
    return EXIT_GATE_FAILED if outcome.failed_gate is not None else EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    """Loop until the evidence says stop (SPEC_RUN_V0.md)."""
    root = git.find_root(Path.cwd())

    refused = _refuse_unverifiable(root, "run")
    if refused is not None:
        return refused

    try:
        cfg = config.load(root / config.CONFIG_FILENAME)
        verify.plan(cfg, None)  # fail on a broken gate list before any work
    except config.ConfigError as exc:
        print(f"wring run: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if cfg.run is None:
        print(
            f"wring run: no 'run:' section in {config.CONFIG_FILENAME} — "
            "the loop needs to know what edits the code. Add one:\n\n"
            "  run:\n"
            '    worker: claude -p "$(cat {brief})"\n\n'
            "There is no default worker: Wringer runs the command you wrote "
            "down, never one it guessed.",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    if args.max_iterations is not None and args.max_iterations < 1:
        print(
            f"wring run: --max-iterations must be at least 1 "
            f"(got {args.max_iterations})",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    quiet = args.json
    try:
        outcome = loop.run(
            root,
            cfg,
            max_iterations=args.max_iterations,
            on_iteration=None if quiet else _report_iteration,
            on_gate=None if quiet else _report_gate,
            on_worker=None if quiet else _report_worker,
        )
    except evidence.EvidenceError as exc:
        print(f"wring run: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if args.json:
        print(
            json.dumps(
                {
                    "status": outcome.status,
                    "reason": outcome.reason,
                    "iterations": outcome.iterations,
                    "loop_dir": _relative(outcome.directory, root),
                    "final": (
                        verify.json_summary(outcome.final, root)
                        if outcome.final is not None
                        else None
                    ),
                }
            )
        )
    else:
        _report_loop(outcome, root)

    if outcome.status == "interrupted":
        return EXIT_INTERRUPTED
    return EXIT_OK if outcome.converged else EXIT_GATE_FAILED


def _report_iteration(iteration: int, budget: int) -> None:
    print(f"\niteration {iteration}/{budget}", flush=True)


def _report_worker(result: gates.GateResult) -> None:
    """One line for the worker's turn, shaped like a gate's so the two read
    as one transcript."""
    note = "timed out" if result.timed_out else f"exit {result.exit_code}"
    label = "→ worker"
    padding = " " * max(1, 21 - len(label))
    print(f"{label}{padding}{_duration(result.duration_ms)}  ({note})", flush=True)


def _duration(duration_ms: int) -> str:
    """Seconds for a gate, minutes once a worker has been thinking a while."""
    seconds = duration_ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}m {seconds:02d}s"


_LOOP_ENDINGS = {
    "converged": "Converged in {n} iteration{s}.",
    "max_iterations": "Stopped after {n} iteration{s} — the budget ran out and "
    "the gates still fail.",
    "no_progress": "Stopped after {n} iteration{s} — the worker changed nothing, "
    "so the gates would say the same again.",
    "interrupted": "Interrupted after {n} iteration{s}.",
}


def _report_loop(outcome: loop.Outcome, root: Path) -> None:
    ending = _LOOP_ENDINGS.get(outcome.reason, "Stopped after {n} iteration{s}.")
    print(
        "\n"
        + ending.format(n=outcome.iterations, s="" if outcome.iterations == 1 else "s")
    )
    print(f"Loop evidence: {_relative(outcome.directory, root)}/")
    if not outcome.converged and outcome.final is not None:
        print(f"Last verification: {verify.bundle_path(outcome.final.bundle, root)}/")


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _refuse_unverifiable(root: Path, command: str) -> int | None:
    """The preconditions every verifying command shares, or None to proceed.

    A bundle that describes an unsafe or unknowable state is worse than no
    bundle, so neither one gets written.
    """
    if not git.is_repo(root):
        print(
            f"wring {command}: {Path.cwd()} is not a git repository — verification "
            "records which commit and which changes were proven, so it needs "
            "one. Run 'git init', or verify from inside your repo.",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    unfinished = git.in_progress(root)
    if unfinished is not None:
        print(
            f"wring {command}: refusing to verify in the middle of {unfinished} — "
            "HEAD and the working tree describe a state nobody chose. Finish "
            "or abort it, then verify.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    return None


def cmd_explain(args: argparse.Namespace) -> int:
    """Read a finished run and say what happened, without an LLM.

    Everything printed here is already in the bundle — this command exists
    so a human (or an agent shelling out) does not have to open four files
    to learn which gate failed and how to rerun it.
    """
    root = git.find_root(Path.cwd())

    if args.run is not None:
        run_dir = Path(args.run)
        if not run_dir.is_dir():
            print(f"wring explain: no run directory at {args.run}", file=sys.stderr)
            return EXIT_CONFIG
    else:
        runs_root = root / evidence.RUNS_DIRNAME
        found = evidence.latest_run(runs_root)
        if found is None:
            print(
                f"wring explain: no runs under {runs_root.as_posix()} — "
                "run 'wring verify' first",
                file=sys.stderr,
            )
            return EXIT_CONFIG
        run_dir = found

    try:
        manifest = evidence.read_manifest(run_dir)
        recorded = evidence.read_events(run_dir)
        rows = evidence.read_gate_results(run_dir)
    except evidence.EvidenceError as exc:
        print(f"wring explain: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    _explain(run_dir, manifest, recorded, rows)
    return EXIT_OK


def _explain(
    run_dir: Path,
    manifest: dict,
    recorded: list[dict],
    rows: list[tuple[Path, dict]],
) -> None:
    result = manifest.get("result", {})
    status = result.get("status", "unknown")
    failed_gate = result.get("failed_gate")
    repo = manifest.get("repo", {})
    started = next(
        (event for event in recorded if event.get("type") == "run.started"), {}
    )

    print(f"Run {manifest.get('run_id', run_dir.name)} — {status}")
    print(_explain_repo_line(started, repo, manifest))
    print()

    for _, row in rows:
        print(
            _gate_line(
                row.get("gate_id", "?"),
                row.get("status") == "passed",
                bool(row.get("timed_out")),
                int(row.get("duration_ms", 0)),
                bool(row.get("optional")),
            )
        )

    if failed_gate is not None:
        _explain_failure(run_dir, failed_gate, rows)
    elif status == "interrupted":
        # An interrupted run has no failing gate, but "nothing to diagnose"
        # would be a lie: gates after the interruption never ran at all.
        _explain_interruption(run_dir, recorded)
    else:
        print("\nEvery required gate passed — nothing to diagnose.")

    _explain_changes(recorded)

    report = run_dir / summary.SUMMARY_FILENAME
    try:
        shown = report.relative_to(Path.cwd()).as_posix()
    except ValueError:
        shown = report.as_posix()
    print(f"\nFull report:\n  {shown}")
    if failed_gate is not None:
        print(f"\nRerun:\n  wring verify --gate {failed_gate}")
    elif status == "interrupted":
        # The whole run, not one gate: an interrupt leaves everything from
        # the stopped gate onwards unproven.
        print("\nRerun:\n  wring verify")


def _explain_repo_line(started: dict, repo: dict, manifest: dict) -> str:
    name = started.get("repo") or "repo"
    sha = repo.get("head_sha")
    where = f"{name} @ {sha[:7]}" if sha else f"{name} (not a git repository)"
    if repo.get("branch"):
        tree = "dirty" if repo.get("dirty") else "clean"
        where += f" (branch {repo['branch']}, {tree})"
    at = manifest.get("started_at")
    return f"{where} · started {at}" if at else where


def _explain_failure(
    run_dir: Path, failed_gate: str, rows: list[tuple[Path, dict]]
) -> None:
    match = next(
        ((d, r) for d, r in rows if r.get("gate_id") == failed_gate), None
    )
    if match is None:  # a bundle that names a gate it never recorded
        print(f"\nFailing gate: {failed_gate} (no result.json recorded)")
        return

    gate_dir, row = match
    print(f"\nFailing gate: {failed_gate}")
    print(f"  command    {row.get('command', '?')}")
    print(f"  exit code  {row.get('exit_code', '?')}")
    if row.get("timed_out"):
        print("  timed out  yes")

    for stream in ("stdout", "stderr"):
        path = gate_dir / f"{stream}.log"
        # label it the way the bundle does, so the reader can find the file
        _print_tail(path, path.relative_to(run_dir).as_posix())


def _explain_interruption(run_dir: Path, recorded: list[dict]) -> None:
    """Name the gate that was running when the run stopped.

    It has no `result.json` — it never finished — so the record of it is the
    `gate.started` event nothing answered, plus whatever it managed to print
    before it was killed.
    """
    answered = {
        event.get("gate_id")
        for event in recorded
        if event.get("type") == "gate.finished"
    }
    unanswered = [
        event
        for event in recorded
        if event.get("type") == "gate.started"
        and event.get("gate_id") not in answered
    ]
    if not unanswered:
        print("\nInterrupted before any gate started.")
        return

    event = unanswered[-1]
    gate_id = event.get("gate_id", "?")
    print(f"\nInterrupted during gate: {gate_id}")
    print(f"  command    {event.get('command', '?')}")

    gate_dir = _gate_dir_for(run_dir, str(gate_id))
    if gate_dir is None:
        return
    for stream in ("stdout", "stderr"):
        path = gate_dir / f"{stream}.log"
        _print_tail(path, path.relative_to(run_dir).as_posix())


def _gate_dir_for(run_dir: Path, gate_id: str) -> Path | None:
    """The `gates/NNN_<id>/` directory for one gate id.

    Matched on the whole name after the numeric prefix, never a suffix
    search: a gate called `test` must not find `unit_test`'s evidence.
    """
    gates_root = run_dir / evidence.GATES_DIRNAME
    if not gates_root.is_dir():
        return None
    for path in sorted(gates_root.iterdir()):
        name = path.name
        if path.is_dir() and name[:3].isdigit() and name[3:] == f"_{gate_id}":
            return path
    return None


def _explain_changes(recorded: list[dict]) -> None:
    git_status = next(
        (event for event in recorded if event.get("type") == "git.status"), None
    )
    if git_status is None:
        return

    changed = git_status.get("changed_files", [])
    untracked = git_status.get("untracked", [])
    if not changed and not untracked:
        print("\nNo uncommitted changes.")
        return

    if changed:
        print(f"\nChanged files ({len(changed)}):")
        for path in changed[:EXPLAIN_FILE_LIMIT]:
            print(f"  {path}")
        if len(changed) > EXPLAIN_FILE_LIMIT:
            print(f"  … {len(changed) - EXPLAIN_FILE_LIMIT} more")
    if untracked:
        lead = "" if changed else "\n"
        shown = ", ".join(untracked[:5])
        more = f", … {len(untracked) - 5} more" if len(untracked) > 5 else ""
        print(f"{lead}Untracked ({len(untracked)}): {shown}{more}")


def _gate_line(
    gate_id: str,
    passed: bool,
    timed_out: bool,
    duration_ms: int,
    optional: bool,
) -> str:
    """The spec's demo shape, used live by `verify` and replayed by `explain`
    so one gate never reads two different ways."""
    mark = "✓" if passed else "✗"
    outcome = "passed" if passed else ("timed out" if timed_out else "failed")
    label = f"{gate_id} {outcome}"
    padding = " " * max(1, 19 - len(label))
    note = "  (optional)" if not passed and optional else ""
    return f"{mark} {label}{padding}{duration_ms / 1000:.1f}s{note}"


def _report_gate(result: gates.GateResult) -> None:
    """One line per gate, printed as it finishes."""
    print(
        _gate_line(
            result.gate.id,
            result.passed,
            result.timed_out,
            result.duration_ms,
            result.gate.optional,
        ),
        flush=True,
    )


def _bundle_path(bundle: evidence.Bundle, root: Path) -> str:
    """The bundle's path as a reader would type it — repo-relative when it
    lives inside the repo, absolute when it somehow does not."""
    try:
        return bundle.directory.relative_to(root).as_posix()
    except ValueError:
        return str(bundle.directory)


def _report_json(
    bundle: evidence.Bundle,
    root: Path,
    failed_gate: str | None,
    status: str = "passed",
) -> None:
    """One object on stdout and nothing else (spec §CLI surface).

    This is what a coding agent consumes, so the keys are stable and present
    even when empty: a consumer should never have to distinguish "passed"
    from "the tool forgot to tell me".
    """
    print(
        json.dumps(
            {
                "status": status,
                "failed_gate": failed_gate,
                "rerun": (
                    f"wring verify --gate {failed_gate}"
                    if failed_gate is not None
                    else None
                ),
                "evidence_dir": _bundle_path(bundle, root),
            }
        )
    )


def _report_run(
    bundle: evidence.Bundle,
    root: Path,
    results: list[gates.GateResult],
    failed_gate: str | None,
    status: str = "passed",
) -> None:
    if status == "interrupted":
        print("\n✗ interrupted — the run stopped before every gate finished")
    if failed_gate is not None:
        failure = next(r for r in results if r.gate.id == failed_gate)
        for path in (failure.stdout_path, failure.stderr_path):
            _print_tail(path, bundle.relative(path))

    shown = _bundle_path(bundle, root)
    print(f"\nEvidence written to:\n{shown}/")

    if failed_gate is not None:
        print(
            f"\nNext:\n  open {shown}/summary.md\n"
            f"  rerun wring verify --gate {failed_gate}"
        )


def _print_tail(path: Path, label: str) -> None:
    """The tail of a failing gate's log — skipped when it wrote nothing."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    if not lines:
        return

    shown = lines[-LOG_TAIL_LINES:]
    elided = len(lines) - len(shown)
    where = f"{label} (last {len(shown)} of {len(lines)} lines)" if elided else label
    print(f"\n--- {where} ---")
    for line in shown:
        print(line)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        # A Ctrl-C between the phases that handle it themselves still owes the
        # caller the contract's exit code, not a traceback.
        print("\nwring: interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
