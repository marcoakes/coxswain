"""Render the milestone rail to a self-contained SVG — `docs/roadmap.svg`.

A roadmap is the easiest document in a repository to lie with. It is written
once, it is never run, and nothing fails when it drifts: a node keeps saying
"done" long after the thing it names was renamed, deferred or quietly dropped.
In a project whose entire product is evidence, a hand-drawn plan would be the
one artifact nobody could check.

So **every milestone here carries a probe**, and a node is drawn green only
when its probe passes against this checkout: the commands it claims must be
registered in `wring --help`, the files it claims must exist, the tags it
claims must be in `git tag`. `tests/test_docs.py` runs the same probes, so a
milestone that stops being true fails the suite rather than ageing quietly on
a picture.

The same CSS-keyframe-free, dependency-free, GitHub-renderable shape as
`demo_render.py`, and deliberately the same palette: these three assets sit in
one README and should look like one project.

Regeneration is a deliberate act, like the demo's:

    python3 scripts/roadmap_render.py docs/roadmap.svg 2026-08-06

The date is an ARGUMENT rather than `date.today()`. A file that rewrites
itself on every run has a diff nobody can read, and "the progress bar moved"
is not a change worth reviewing.
"""

from __future__ import annotations

import html
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# The 90-day compression's window (ROADMAP.md). Day 1 is the day the arc was
# adopted; the deadline is the one the roadmap has carried since.
START = date(2026, 7, 29)
DEADLINE = date(2026, 9, 30)


@dataclass(frozen=True)
class Milestone:
    """One node on the rail, and how to check it is really there."""

    label: str
    caption: str
    # Subcommands that must be registered for this milestone to be done.
    commands: tuple[str, ...] = ()
    # Paths that must exist, relative to the repo root.
    files: tuple[str, ...] = field(default_factory=tuple)
    # Git tags that must exist.
    tags: tuple[str, ...] = field(default_factory=tuple)

    def done(self, root: Path) -> bool:
        return (
            all(name in registered_commands() for name in self.commands)
            and all((root / name).exists() for name in self.files)
            and all(tag in existing_tags(root) for tag in self.tags)
        )


MILESTONES: tuple[Milestone, ...] = (
    Milestone("v0.1", "verify", commands=("init", "verify", "explain")),
    Milestone("v0.2", "loop+fleet", commands=("run", "resume", "fleet", "judge")),
    Milestone(
        "ship", "PyPI+tag",
        tags=("v0.1.0", "v0.2.0"),
        files=(".github/workflows/release.yml",),
    ),
    Milestone(
        "P0", "the box",
        commands=("doctor",),
        files=("Dockerfile", "SETUP.md"),
    ),
    Milestone(
        "P1", "ACP",
        files=("src/wringer/acp.py", "SPEC_ACP_V0.md"),
    ),
    Milestone("P2", "spec/plan", commands=("spec", "plan")),
    Milestone("P3", "issue→MR", commands=("get", "issue", "deliver")),
    Milestone(
        "P4", "PM UX",
        commands=("start",),
        files=("SPEC_START_V0.md", "docs/start.cast.json"),
    ),
    Milestone(
        "P5", "attest",
        commands=("attest", "audit"),
        files=("src/wringer/vacuity.py",),
    ),
    Milestone("P6", "bench", commands=("bench",)),
)


def registered_commands() -> frozenset[str]:
    """Every subcommand `wring` actually registers.

    Read from the parser rather than grepped out of the source: a roadmap that
    matched a string in a comment would be exactly the kind of evidence this
    project refuses.
    """
    from wringer import cli

    for action in cli.build_parser()._actions:
        if getattr(action, "choices", None):
            return frozenset(action.choices)
    return frozenset()


def existing_tags(root: Path) -> frozenset[str]:
    try:
        proc = subprocess.run(
            ["git", "tag"], cwd=root, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):  # pragma: no cover
        return frozenset()
    return frozenset(proc.stdout.split()) if proc.returncode == 0 else frozenset()


# Same palette as demo_render.py — three assets, one README, one project.
BG = "#11141a"
FG = "#d7dae0"
DIM = "#7d8590"
GREEN = "#3fb950"
BLUE = "#58a6ff"
RAIL = "#2b313b"

WIDTH = 1000.0
HEIGHT = 300.0
PAD_X = 40.0
RAIL_Y = 176.0
FONT = (
    "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,"
    "'Liberation Mono',monospace"
)


def render(states: list[tuple[Milestone, bool]], today: date) -> str:
    """The rail, drawn from probed state. Nothing here decides done-ness."""
    span = (DEADLINE - START).days
    elapsed = max(0, min(span, (today - START).days))
    fraction = elapsed / span if span else 0.0

    bar_x, bar_w = PAD_X, WIDTH - PAD_X * 2
    fill_w = bar_w * fraction
    done_count = sum(1 for _, ok in states if ok)
    # The rail is green up to the last node whose probe passed, grey after.
    # Drawn from the LAST done node rather than the count, so a milestone
    # completed out of order shows as the gap it is instead of being tidied
    # into a clean prefix.
    last_done = max((i for i, (_, ok) in enumerate(states) if ok), default=-1)

    step = bar_w / (len(states) - 1) if len(states) > 1 else 0.0
    positions = [bar_x + step * i for i in range(len(states))]

    parts: list[str] = [
        f'<rect width="100%" height="100%" rx="10" fill="{BG}"/>',
        # --- the progress bar
        f'<text x="{bar_x:.0f}" y="46" fill="{DIM}" font-size="12">Jul 29</text>',
        f'<text x="{bar_x + bar_w:.0f}" y="46" fill="{DIM}" font-size="12" '
        f'text-anchor="end">Sep 30 — deadline</text>',
        f'<rect x="{bar_x:.0f}" y="58" width="{bar_w:.0f}" height="6" rx="3" '
        f'fill="{RAIL}"/>',
        f'<rect x="{bar_x:.0f}" y="58" width="{fill_w:.0f}" height="6" rx="3" '
        f'fill="{BLUE}"/>',
        f'<text x="{bar_x + fill_w:.0f}" y="84" fill="{BLUE}" font-size="12">'
        f'today · day {elapsed + 1} of {span}</text>',
        f'<text x="{bar_x + bar_w:.0f}" y="84" fill="{DIM}" font-size="12" '
        f'text-anchor="end">{span - elapsed} days remaining</text>',
        # --- the rail
        f'<line x1="{positions[0]:.0f}" y1="{RAIL_Y:.0f}" '
        f'x2="{positions[-1]:.0f}" y2="{RAIL_Y:.0f}" stroke="{RAIL}" '
        f'stroke-width="3"/>',
    ]
    if last_done > 0:
        parts.append(
            f'<line x1="{positions[0]:.0f}" y1="{RAIL_Y:.0f}" '
            f'x2="{positions[last_done]:.0f}" y2="{RAIL_Y:.0f}" '
            f'stroke="{GREEN}" stroke-width="3"/>'
        )

    for (milestone, ok), x in zip(states, positions, strict=True):
        parts.append(
            f'<text x="{x:.0f}" y="{RAIL_Y - 26:.0f}" fill="{FG}" '
            f'font-size="13" font-weight="600" text-anchor="middle">'
            f'{html.escape(milestone.label)}</text>'
        )
        if ok:
            parts.append(
                f'<circle cx="{x:.0f}" cy="{RAIL_Y:.0f}" r="11" fill="{GREEN}"/>'
            )
            parts.append(
                f'<text x="{x:.0f}" y="{RAIL_Y + 4:.0f}" fill="{BG}" '
                f'font-size="12" font-weight="700" text-anchor="middle">✓</text>'
            )
        else:
            parts.append(
                f'<circle cx="{x:.0f}" cy="{RAIL_Y:.0f}" r="10" fill="{BG}" '
                f'stroke="{DIM}" stroke-width="2"/>'
            )
        parts.append(
            f'<text x="{x:.0f}" y="{RAIL_Y + 30:.0f}" fill="{DIM}" '
            f'font-size="11" text-anchor="middle">'
            f'{html.escape(milestone.caption)}</text>'
        )

    remaining = ", ".join(m.label for m, ok in states if not ok) or "nothing"
    parts += [
        f'<circle cx="{PAD_X + 6:.0f}" cy="248" r="6" fill="{GREEN}"/>',
        f'<text x="{PAD_X + 20:.0f}" y="252" fill="{DIM}" font-size="12">'
        f'shipped — every command it names is registered and every file it '
        f'names is committed</text>',
        f'<circle cx="{PAD_X + 6:.0f}" cy="272" r="5.5" fill="{BG}" '
        f'stroke="{DIM}" stroke-width="2"/>',
        f'<text x="{PAD_X + 20:.0f}" y="276" fill="{DIM}" font-size="12">'
        f'remaining — {html.escape(remaining)}</text>',
        f'<text x="{WIDTH - PAD_X:.0f}" y="252" fill="{FG}" font-size="12" '
        f'text-anchor="end">{done_count} of {len(states)} milestones</text>',
        f'<text x="{WIDTH - PAD_X:.0f}" y="276" fill="{DIM}" font-size="11" '
        f'text-anchor="end">every node probed against this checkout</text>',
    ]

    label = f"Wringer roadmap — {done_count} of {len(states)} milestones shipped"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH:.0f}" '
        f'height="{HEIGHT:.0f}" viewBox="0 0 {WIDTH:.0f} {HEIGHT:.0f}" '
        f'font-family="{FONT}" role="img" aria-label="{html.escape(label)}">\n  '
        + "\n  ".join(parts)
        + "\n</svg>\n"
    )


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/roadmap.svg")
    today = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()
    root = Path(__file__).resolve().parent.parent

    states = [(milestone, milestone.done(root)) for milestone in MILESTONES]
    out.write_text(render(states, today), encoding="utf-8")

    shipped = sum(1 for _, ok in states if ok)
    print(f"probed {len(states)} milestones, {shipped} shipped -> {out}")
    for milestone, ok in states:
        print(f"  {'✓' if ok else '-'} {milestone.label:<6}{milestone.caption}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
