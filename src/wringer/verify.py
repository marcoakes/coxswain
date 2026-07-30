"""Run a verification and write its bundle — the core `wring verify` drives.

Split out of `cli.py` so something other than the console can ask for a
verification and get the answer as data: `wring run` needs a full verify per
iteration (SPEC_RUN_V0.md), and shelling out to itself to get one would mean
parsing its own output.

The split is deliberately narrow. This module owns the part that is the same
however it was invoked — snapshot git, open a bundle, run the planned gates
in order, stop on the first required failure, write the manifest and the
summary. `cli.py` keeps everything that is about being a command line:
argument parsing, precondition messages, exit codes, and printing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from wringer import __version__, config, evidence, gates, git, redact, summary

# Called as each gate finishes, so a console can report a long run as it
# happens rather than after it. None for callers that want no output.
GateReporter = Callable[[gates.GateResult], None]


@dataclass(frozen=True)
class Outcome:
    """Everything a caller could want to know about one verification."""

    bundle: evidence.Bundle
    results: list[gates.GateResult]
    skipped: list[config.Gate]
    interrupted: summary.Interrupted | None
    failed_gate: str | None
    status: str

    @property
    def passed(self) -> bool:
        return self.status == "passed"


def plan(cfg: config.Config, requested: str | None) -> list[tuple[int, config.Gate]]:
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


def run(
    root: Path,
    cfg: config.Config,
    planned: list[tuple[int, config.Gate]],
    output: str | None = None,
    on_gate: GateReporter | None = None,
) -> Outcome:
    """Verify once and write the bundle. Raises `evidence.EvidenceError` if
    the bundle cannot be opened; the caller decides what that costs."""
    # Snapshot git before the bundle exists, so Wringer's own run directory
    # is never what makes the tree look dirty — or shows up in its own
    # evidence as an untracked file.
    state = git.inspect(root)
    patch = git.diff(root, state.head_sha)
    status_text = git.status(root)
    # Built from the environment this run inherits, so the gates' own
    # secrets are the ones erased.
    redactor = redact.Redactor.from_config(cfg.evidence)
    if output is not None:
        bundle = evidence.Bundle.at(Path(output), redactor=redactor)
    else:
        bundle = evidence.Bundle.create(root / evidence.RUNS_DIRNAME, redactor=redactor)

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
    interrupted: summary.Interrupted | None = None

    for offset, (index, gate) in enumerate(planned):
        try:
            result = _run_gate(bundle, gate, index, root)
        except KeyboardInterrupt:
            # Ctrl-C: finish the bundle rather than abandon it half-written.
            # A run that stopped is evidence too, as long as it says so.
            # The gate that was running is neither passed nor skipped, so it
            # is carried separately — its directory already exists and holds
            # whatever it printed before it was killed.
            interrupted = summary.Interrupted(
                gate=gate, directory=bundle.gate_dir(index, gate.id)
            )
            skipped = [pending for _, pending in planned[offset + 1 :]]
            break
        results.append(result)
        if on_gate is not None:
            on_gate(result)
        if not result.passed and not gate.optional:
            # Stop on the first required failure; everything after it is
            # unrun, not passed, and the summary says so.
            failed_gate = gate.id
            skipped = [pending for _, pending in planned[offset + 1 :]]
            break

    if interrupted is not None:
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
        interrupted=interrupted,
    )

    return Outcome(
        bundle=bundle,
        results=results,
        skipped=skipped,
        interrupted=interrupted,
        failed_gate=failed_gate,
        status=status,
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
