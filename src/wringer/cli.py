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

from wringer import __version__, config, detect, evidence, gates, git, redact, summary

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
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human report",
    )
    parser_verify.set_defaults(func=cmd_verify)

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

    # Preconditions first: a bundle that describes an unsafe or unknowable
    # state is worse than no bundle, so neither one gets written.
    if not git.is_repo(root):
        print(
            f"wring verify: {Path.cwd()} is not a git repository — verification "
            "records which commit and which changes were proven, so it needs "
            "one. Run 'git init', or verify from inside your repo.",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    unfinished = git.in_progress(root)
    if unfinished is not None:
        print(
            f"wring verify: refusing to verify in the middle of {unfinished} — "
            "HEAD and the working tree describe a state nobody chose. Finish "
            "or abort it, then verify.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    try:
        cfg = config.load(root / config.CONFIG_FILENAME)
        planned = _plan(cfg, args.gate)
    except config.ConfigError as exc:
        print(f"wring verify: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    # Snapshot git before the bundle exists, so Wringer's own run directory
    # is never what makes the tree look dirty — or shows up in its own
    # evidence as an untracked file.
    state = git.inspect(root)
    patch = git.diff(root, state.head_sha)
    status_text = git.status(root)
    # Built from the environment this run inherits, so the gates' own
    # secrets are the ones erased.
    redactor = redact.Redactor.from_config(cfg.evidence)
    try:
        bundle = evidence.Bundle.create(
            root / evidence.RUNS_DIRNAME, redactor=redactor
        )
    except evidence.EvidenceError as exc:
        print(f"wring verify: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    bundle.event(
        "run.started",
        run_id=bundle.run_id,
        wringer_version=__version__,
        repo=root.name,
        sha=state.head_sha,
    )
    bundle.event(
        "git.status",
        dirty=state.dirty,
        changed_files=list(state.changed_files),
        # Only when there are any, so the event stays the spec's shape for
        # the common case.
        **({"untracked": list(state.untracked)} if state.untracked else {}),
    )
    if patch is not None:
        bundle.write_capture(evidence.DIFF_FILENAME, patch)
    if status_text is not None:
        bundle.write_capture(evidence.STATUS_FILENAME, status_text)

    results: list[gates.GateResult] = []
    skipped: list[config.Gate] = []
    failed_gate: str | None = None

    interrupted = False

    for offset, (index, gate) in enumerate(planned):
        try:
            result = _run_gate(bundle, gate, index, root)
        except KeyboardInterrupt:
            # Ctrl-C: finish the bundle rather than abandon it half-written.
            # A run that stopped is evidence too, as long as it says so.
            interrupted = True
            skipped = [pending for _, pending in planned[offset + 1 :]]
            break
        results.append(result)
        if not args.json:
            _report_gate(result)
        if not result.passed and not gate.optional:
            # Stop on the first required failure; everything after it is
            # unrun, not passed, and the summary says so.
            failed_gate = gate.id
            skipped = [pending for _, pending in planned[offset + 1 :]]
            break

    if interrupted:
        status = "interrupted"
    elif failed_gate is not None:
        status = "failed"
    else:
        status = "passed"
    bundle.event(
        "run.finished",
        status=status,
        **({"failed_gate": failed_gate} if failed_gate is not None else {}),
    )
    bundle.write_manifest(state=state, status=status, failed_gate=failed_gate)
    summary.write(
        bundle,
        state,
        results=results,
        skipped=skipped,
        failed_gate=failed_gate,
        status=status,
    )

    if args.json:
        _report_json(bundle, root, failed_gate, status)
    else:
        _report_run(bundle, root, results, failed_gate, status)

    if interrupted:
        return EXIT_INTERRUPTED
    return EXIT_GATE_FAILED if failed_gate is not None else EXIT_OK


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


def _plan(
    cfg: config.Config, requested: str | None
) -> list[tuple[int, config.Gate]]:
    """The gates this run will attempt, each with its declared position.

    Every gate by default, in declared order (the config decides what runs
    cheapest first). `--gate ID` narrows the run to one gate but keeps its
    number, so its evidence lands where a full run would have put it.
    """
    numbered = list(enumerate(cfg.gates, start=1))
    if requested is None:
        return numbered

    for index, gate in numbered:
        if gate.id == requested:
            return [(index, gate)]
    known = ", ".join(gate.id for gate in cfg.gates)
    raise config.ConfigError(
        f"no gate '{requested}' in {config.CONFIG_FILENAME} (declared: {known})"
    )


def _run_gate(
    bundle: evidence.Bundle, gate: config.Gate, index: int, root: Path
) -> gates.GateResult:
    """Run one gate and record everything it produced."""
    bundle.event("gate.started", gate_id=gate.id, command=gate.run)
    gate_dir = bundle.gate_dir(index, gate.id)
    result = gates.run(
        gate,
        cwd=root,
        stdout_path=gate_dir / "stdout.log",
        stderr_path=gate_dir / "stderr.log",
        redactor=bundle.redactor,
    )
    bundle.write_gate_result(gate_dir, result)

    finished: dict[str, object] = {
        "gate_id": gate.id,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
    }
    if not result.passed:
        # The spec carries `log` on the failing gate only — that is the one
        # a reader is being sent to.
        finished["log"] = bundle.relative(result.stdout_path)
    if result.truncated:
        # Only when true: an absent key means the log is whole.
        finished["truncated"] = True
    bundle.event("gate.finished", **finished)
    return result


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
