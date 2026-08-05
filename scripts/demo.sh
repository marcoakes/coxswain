#!/bin/sh
# Regenerate the README demo: a real `wring verify` failing on a planted bug,
# then a real `wring run` repairing it and verifying again.
#
# Everything below is genuinely executed. The cast records what came back and
# when; the SVG renders exactly that. If the console changes, run this again
# rather than editing either file — the same rule the captured transcripts
# have always had (law 8).
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$(dirname "$0")/scratch.sh"
SCRATCH=$(scratch_dir "${1:-}" demo) || exit 2
PY="$ROOT/.venv/bin/python"
WRING="$ROOT/.venv/bin/wring"

if [ -d "$SCRATCH" ]; then find "$SCRATCH" -mindepth 1 -delete 2>/dev/null; fi
mkdir -p "$SCRATCH"
cd "$SCRATCH"

git init -q -b main .
git config user.email demo@example.invalid
git config user.name "demo"
echo ".wringer/" > .gitignore

# A planted bug: the test expects 4, the code returns 5.
cat > calc.py <<'EOF'
def add(a, b):
    return a + b + 1
EOF

cat > test_calc.py <<'EOF'
from calc import add


def test_add():
    assert add(2, 2) == 4
EOF

# The worker stands in for a coding agent. In a real repo this is
#   worker: claude -p "$(cat {brief})"
# or an acp: mapping; here it is a shell one-liner so the demo is honest
# about running no agent and reproducible by anyone.
cat > fix.sh <<'EOF'
sed -i '' 's/return a + b + 1/return a + b/' calc.py
EOF

cat > .wringer.yaml <<'EOF'
version: 1
gates:
  - id: test
    run: "python3 -m pytest -q"

run:
  worker: "sh ./fix.sh"
  max_iterations: 3
EOF

git add -A
git commit -qm "the calculator, with a planted bug"

"$PY" "$ROOT/scripts/demo_record.py" "$SCRATCH" "$ROOT/docs/demo.cast.json" "$WRING"
"$PY" "$ROOT/scripts/demo_render.py" "$ROOT/docs/demo.cast.json" "$ROOT/docs/demo.svg"
