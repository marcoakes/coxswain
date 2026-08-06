"""Render the intent→receipt flow to a self-contained SVG — `docs/flow.svg`.

An architecture diagram is the second easiest document in a repository to lie
with, after a roadmap. It is drawn once, it is never run, and nothing fails
when a box stops matching the program: the picture keeps showing a stage that
was renamed, or a command that never shipped, and it looks authoritative while
doing it.

So **every stage here names the command that performs it**, and
`tests/test_docs.py` asserts each of those commands is registered in the real
parser. Rename a command and the diagram fails the suite rather than quietly
becoming fiction. Same bargain as `scripts/roadmap_render.py`.

Regeneration is deliberate:

    python3 scripts/flow_render.py docs/flow.svg

Two stages deliberately name **no** command, and that is the point of drawing
them: a human approving a spec and a human reviewing a merge request are the
places this program stops and waits. A diagram that showed only the automated
steps would be selling the wrong thing.
"""

from __future__ import annotations

import html
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Stage:
    """One box: what happens, what runs it, and what it leaves behind."""

    title: str
    # The commands that perform this stage. Empty means a human does it —
    # which is a claim the diagram makes on purpose, not an omission.
    commands: tuple[str, ...] = ()
    artifact: str = ""

    @property
    def label(self) -> str:
        return " · ".join(f"wring {name}" for name in self.commands) or "a human"


STAGES: tuple[Stage, ...] = (
    Stage("issue or PRD", ("issue",), "issues/42.md"),
    Stage("spec", ("spec",), "wringer.spec.yaml"),
    Stage("approved", (), "approved: true"),
    Stage("work", ("plan", "fleet"), "tasks.jsonl"),
    Stage("the agent writes", ("run",), "loop bundle"),
    Stage("gates prove it", ("verify",), "evidence bundle"),
    Stage("judged", ("judge",), "verdict"),
    Stage("reviewed", (), "a person decides"),
    Stage("merge request", ("deliver",), "branch + MR"),
    Stage("receipt", ("attest", "audit"), "attestation"),
)


def commands_named() -> set[str]:
    return {name for stage in STAGES for name in stage.commands}


# The palette `demo_render.py` and `roadmap_render.py` already use: three
# assets in one README should look like one project.
BG = "#11141a"
FG = "#d7dae0"
DIM = "#7d8590"
GREEN = "#3fb950"
BLUE = "#58a6ff"
RAIL = "#2b313b"

BOX_W = 176.0
BOX_H = 62.0
GAP_X = 34.0
GAP_Y = 40.0
PAD = 30.0
PER_ROW = 5
FONT = (
    "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,"
    "'Liberation Mono',monospace"
)


def render(stages: tuple[Stage, ...]) -> str:
    rows = [stages[i : i + PER_ROW] for i in range(0, len(stages), PER_ROW)]
    width = PAD * 2 + BOX_W * PER_ROW + GAP_X * (PER_ROW - 1)
    height = PAD * 2 + BOX_H * len(rows) + GAP_Y * (len(rows) - 1) + 26

    parts: list[str] = [f'<rect width="100%" height="100%" rx="10" fill="{BG}"/>']

    for row_index, row in enumerate(rows):
        top = PAD + 26 + row_index * (BOX_H + GAP_Y)
        for col, stage in enumerate(row):
            x = PAD + col * (BOX_W + GAP_X)
            human = not stage.commands
            accent = BLUE if human else GREEN
            parts.append(
                f'<rect x="{x:.0f}" y="{top:.0f}" width="{BOX_W:.0f}" '
                f'height="{BOX_H:.0f}" rx="6" fill="{BG}" stroke="{accent}" '
                f'stroke-width="{2 if human else 1}"/>'
            )
            parts.append(
                f'<text x="{x + 12:.0f}" y="{top + 21:.0f}" fill="{FG}" '
                f'font-size="13">{html.escape(stage.title)}</text>'
            )
            parts.append(
                f'<text x="{x + 12:.0f}" y="{top + 38:.0f}" fill="{accent}" '
                f'font-size="11">{html.escape(stage.label)}</text>'
            )
            parts.append(
                f'<text x="{x + 12:.0f}" y="{top + 53:.0f}" fill="{DIM}" '
                f'font-size="10">{html.escape(stage.artifact)}</text>'
            )
            # The arrow into the next box on this row.
            if col < len(row) - 1:
                start = x + BOX_W
                parts.append(
                    f'<line x1="{start + 6:.0f}" y1="{top + BOX_H / 2:.0f}" '
                    f'x2="{start + GAP_X - 6:.0f}" y2="{top + BOX_H / 2:.0f}" '
                    f'stroke="{RAIL}" stroke-width="2"/>'
                )
        # The wrap: last box of this row down and back to the first of the next.
        if row_index < len(rows) - 1:
            parts.append(
                f'<path d="M {PAD + BOX_W / 2:.0f} {top + BOX_H:.0f} '
                f'v {GAP_Y:.0f}" stroke="{RAIL}" stroke-width="2" fill="none"/>'
            )

    parts.append(
        f'<text x="{PAD:.0f}" y="{PAD + 4:.0f}" fill="{DIM}" font-size="12">'
        f'intent in · evidence out — every box names the command that runs it'
        f'</text>'
    )
    parts.append(
        f'<text x="{width - PAD:.0f}" y="{height - PAD + 8:.0f}" fill="{BLUE}" '
        f'font-size="11" text-anchor="end">'
        f'blue = a human decides, and nothing proceeds without them</text>'
    )

    label = "Wringer: from an issue to a receipt, and what runs each step"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'font-family="{FONT}" role="img" aria-label="{html.escape(label)}">\n  '
        + "\n  ".join(parts)
        + "\n</svg>\n"
    )


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/flow.svg")
    out.write_text(render(STAGES), encoding="utf-8")
    named = sorted(commands_named())
    print(f"rendered {len(STAGES)} stages naming {len(named)} commands -> {out}")
    for stage in STAGES:
        print(f"  {stage.title:<18}{stage.label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
