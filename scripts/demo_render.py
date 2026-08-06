"""Render a recorded cast to a self-contained animated SVG.

Pure CSS keyframes over a monospace <text> per line — no JavaScript, no
external font, no dependency. GitHub renders it inline in a README, which is
the whole point: the asset has to work where the pitch is read.

Every timing here comes from `demo.cast.json`, which came from a real run.
Nothing is retimed to look better.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

CHAR_W = 8.4
LINE_H = 20.0
PAD_X = 18.0
PAD_Y = 34.0
FONT = (
    "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,"
    "'Liberation Mono',monospace"
)

# Terminal-ish, and legible on both GitHub themes.
BG = "#11141a"
FG = "#d7dae0"
DIM = "#7d8590"
GREEN = "#3fb950"
RED = "#f85149"
CYAN = "#56b6c2"


def colour(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("$ "):
        return CYAN
    if stripped.startswith("✓"):
        return GREEN
    if stripped.startswith("✗"):
        return RED
    if stripped.startswith(("→", "iteration")):
        return DIM
    if stripped.startswith(("Evidence written", "Loop evidence", "Converged")):
        return FG
    return DIM if stripped.startswith(("Next:", "  ", "rerun", "open")) else FG


def render(cast: list[dict], title: str) -> str:
    total = cast[-1]["at"] + 2.5
    width = PAD_X * 2 + CHAR_W * 80
    height = PAD_Y + LINE_H * (len(cast) + 1) + PAD_X

    rows: list[str] = []
    styles: list[str] = []
    for index, frame in enumerate(cast):
        y = PAD_Y + LINE_H * (index + 1)
        # Every line shares ONE cycle of `total` seconds and appears at its
        # own real fraction of it. Per-element `animation-delay` would give
        # each line its own cycle, so they would fade out at nineteen
        # different moments — a flicker rather than a clean replay.
        at = min(99.0, max(0.0, frame["at"] / total * 100.0))
        rows.append(
            # xml:space="preserve" or SVG collapses runs of spaces — and the
            # column alignment IS the readability of this output.
            f'<text class="l l{index}" x="{PAD_X:.0f}" y="{y:.0f}" '
            f'xml:space="preserve" '
            f'fill="{colour(frame["text"])}">'
            f'{html.escape(frame["text"]) or "&#160;"}</text>'
        )
        styles.append(
            f"@keyframes k{index}{{"
            f"0%,{at:.2f}%{{opacity:0}}"
            f"{min(at + 0.4, 99.4):.2f}%,95%{{opacity:1}}"
            f"100%{{opacity:0}}}}"
            f".l{index}{{animation-name:k{index}}}"
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" \
height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}" \
font-family="{FONT}" font-size="13" role="img" aria-label="{html.escape(title)}">
  <style>
    .l {{ opacity: 0; animation-duration: {total:.2f}s;
         animation-timing-function: linear; animation-iteration-count: infinite; }}
    @media (prefers-reduced-motion: reduce) {{
      .l {{ animation: none; opacity: 1; }}
    }}
  </style>
  <rect width="100%" height="100%" rx="10" fill="{BG}"/>
  <circle cx="24" cy="20" r="5.5" fill="#ff5f57"/>
  <circle cx="43" cy="20" r="5.5" fill="#febc2e"/>
  <circle cx="62" cy="20" r="5.5" fill="#28c840"/>
  <text x="{width / 2:.0f}" y="24" fill="{DIM}" font-size="11" \
text-anchor="middle">{html.escape(title)}</text>
  <g>
    {chr(10).join("    " + row for row in rows)}
  </g>
  <style>{"".join(styles)}</style>
</svg>
"""


# The title drawn in the window chrome. A parameter rather than a literal
# because there is more than one recording now, and a second cast rendered
# under the first one's title would be a caption that describes a different
# session than the one below it.
DEFAULT_TITLE = "wring run — a planted bug, verified fixed"


def main() -> int:
    cast = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    title = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_TITLE
    out.write_text(render(cast, title), encoding="utf-8")
    print(f"rendered {len(cast)} lines -> {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
