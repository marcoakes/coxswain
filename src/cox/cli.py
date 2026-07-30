"""cox — command-line entry points.

Exit codes are contract (SPEC_COX_VERIFY_V0.md):
0 = all required gates passed · 1 = a required gate failed ·
2 = config or environment error · 3 = unsafe dirty state / refused
precondition · 4 = interrupted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cox import __version__, config, detect, evidence, gates, git

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_CONFIG = 2
EXIT_REFUSED = 3  # wired in the Day-4 bolt
EXIT_INTERRUPTED = 4  # wired in the Day-4 bolt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cox",
        description=(
            "One command that proves whether this change is mergeable, "
            "and leaves behind evidence a human or agent can inspect."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"cox {__version__}"
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
        help="run this gate instead of the first one declared",
    )
    parser_verify.set_defaults(func=cmd_verify)

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    target = Path.cwd() / config.CONFIG_FILENAME
    if target.exists():
        print(
            f"cox init: refusing to overwrite existing {target.name}",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    target.write_text(detect.template(), encoding="utf-8")
    print(
        f"Wrote {target.name} — edit the gates to match this project, "
        "then run: cox verify"
    )
    return EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    root = git.find_root(Path.cwd())

    try:
        cfg = config.load(root / config.CONFIG_FILENAME)
        index, gate = _select_gate(cfg, args.gate)
    except config.ConfigError as exc:
        print(f"cox verify: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    # Snapshot git before the bundle exists, so .cox/ is not what makes
    # the tree look dirty.
    state = git.inspect(root)
    try:
        bundle = evidence.Bundle.create(root / evidence.RUNS_DIRNAME)
    except evidence.EvidenceError as exc:
        print(f"cox verify: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    bundle.event(
        "run.started",
        run_id=bundle.run_id,
        cox_version=__version__,
        repo=root.name,
        sha=state.head_sha,
    )
    bundle.event("gate.started", gate_id=gate.id, command=gate.run)
    gate_dir = bundle.gate_dir(index, gate.id)
    result = gates.run(
        gate,
        cwd=root,
        stdout_path=gate_dir / "stdout.log",
        stderr_path=gate_dir / "stderr.log",
    )
    bundle.event(
        "gate.finished",
        gate_id=gate.id,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
    )

    # An optional gate records its failure without failing the run.
    failed = not result.passed and not gate.optional
    status = "failed" if failed else "passed"
    bundle.event(
        "run.finished", status=status, **({"failed_gate": gate.id} if failed else {})
    )
    bundle.write_manifest(
        state=state, status=status, failed_gate=gate.id if failed else None
    )

    _report(result, bundle=bundle, root=root, failed=failed)
    return EXIT_GATE_FAILED if failed else EXIT_OK


def _select_gate(
    cfg: config.Config, requested: str | None
) -> tuple[int, config.Gate]:
    """The one gate this build runs, with its 1-based declared position.

    Sequencing every gate is the Day-2 bolt.
    """
    if requested is not None:
        for index, gate in enumerate(cfg.gates, start=1):
            if gate.id == requested:
                return index, gate
        known = ", ".join(gate.id for gate in cfg.gates)
        raise config.ConfigError(
            f"no gate '{requested}' in {config.CONFIG_FILENAME} (declared: {known})"
        )

    gate = cfg.gates[0]
    if len(cfg.gates) > 1:
        print(
            f"cox verify: {config.CONFIG_FILENAME} declares {len(cfg.gates)} gates; "
            f"this build runs one — using '{gate.id}'. "
            "Use --gate ID to pick another.",
            file=sys.stderr,
        )
    return 1, gate


def _report(
    result: gates.GateResult, bundle: evidence.Bundle, root: Path, failed: bool
) -> None:
    outcome = "passed" if result.passed else "failed"
    label = f"{result.gate.id} {outcome}"
    padding = " " * max(1, 19 - len(label))
    note = "  (optional)" if not result.passed and result.gate.optional else ""
    print(
        f"{'✓' if result.passed else '✗'} {label}{padding}"
        f"{result.duration_ms / 1000:.1f}s{note}"
    )

    try:
        shown = bundle.directory.relative_to(root)
    except ValueError:  # bundle outside the repo root
        shown = bundle.directory
    print(f"\nEvidence written to:\n{shown}/")

    if failed:
        print(f"\nNext:\n  rerun cox verify --gate {result.gate.id}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
