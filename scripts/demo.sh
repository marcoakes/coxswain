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
# Prefer the repo venv (a developer regenerating the demo has one), then the
# uv-tool install SETUP.md step 3 creates, then PATH. The venv was hardcoded,
# which made this script one machine's — and "reproducible by anyone" was
# printed a few lines above the assumption.
for candidate in "$ROOT/.venv/bin" "$HOME/.local/bin"; do
    if [ -x "$candidate/wring" ] && [ -x "$candidate/python" ]; then
        PY="$candidate/python"; WRING="$candidate/wring"; break
    fi
done
PY=${PY:-$(command -v python3 || true)}
WRING=${WRING:-$(command -v wring || true)}
if [ -z "$PY" ] || [ -z "$WRING" ]; then
    echo "FATAL: need both python and wring — looked in $ROOT/.venv/bin," >&2
    echo "  \$HOME/.local/bin, then \$PATH. Install with:" >&2
    echo "  uv tool install --force --python 3.12 $ROOT" >&2
    exit 2
fi
echo "recording with $WRING ($("$WRING" --version))"

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
# `sed -i ''` is BSD-only and this script claims to be reproducible by
# anyone; GNU sed reads the '' as a filename and fails. Writing beside the
# file and moving it works on both, and needs no feature detection.
cat > fix.sh <<'EOF'
sed 's/return a + b + 1/return a + b/' calc.py > calc.py.tmp
mv calc.py.tmp calc.py
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

# ---------------------------------------------------------------------------
# The second recording: the guided launch.
#
# Its own scratch, and that is not tidiness. The tree above already carries a
# .wringer.yaml with `gates:` and `run:`, so `wring start` there would refuse
# to rewrite a `run:` section the file already has — the recording would be a
# correct refusal rather than a launch.
#
# It lands BESIDE docs/demo.svg rather than replacing it. The README's hero is
# `wring run` repairing a planted bug, which is the product's core claim; the
# launch is a different story (onboarding) and both are worth showing.
# ---------------------------------------------------------------------------
START=$(scratch_dir "${1:-}" start) || exit 2
STUBS=$(scratch_dir "${1:-}" start-bin) || exit 2

if [ -d "$START" ]; then find "$START" -mindepth 1 -delete 2>/dev/null; fi
if [ -d "$STUBS" ]; then find "$STUBS" -mindepth 1 -delete 2>/dev/null; fi
mkdir -p "$START" "$STUBS"

# The agent is a STUB, and the documentation says so beside the picture.
# It is the only route that films the agent step while keeping the rule that
# Wringer neither bundles nor installs an agent, and without putting a vendor
# binary into anyone's regeneration path. It is never executed: the launch's
# gates pass on the first try, so no repair loop runs and nothing speaks ACP.
cat > "$STUBS/claude-code-acp" <<'EOF'
#!/bin/sh
echo "this is a stub; the demo detects it and never runs it" >&2
exit 1
EOF
chmod +x "$STUBS/claude-code-acp"

cd "$START"
git init -q -b main .
git config user.email demo@example.invalid
git config user.name "demo"
echo ".wringer/" > .gitignore

# No .wringer.yaml: the launch DETECTS the gates, which is the step being
# filmed. A `test_*.py` at the root is what detection reads as a Python
# layout, so the gate it proposes is `pytest -q`.
cat > calc.py <<'EOF'
def add(a, b):
    return a + b
EOF

cat > test_calc.py <<'EOF'
from calc import add


def test_add():
    assert add(2, 2) == 4
EOF

git add -A
git commit -qm "a calculator, and a test that passes"

# Obviously fake, and it never reaches the recording: `wring start` prints the
# NAME of the variable and never its value. Setting it is what makes the key
# step non-interactive — which is the only form this recorder can film, since
# getpass reads /dev/tty and would block on the operator's real terminal.
ANTHROPIC_API_KEY=sk-ant-notarealkey
export ANTHROPIC_API_KEY
PATH="$STUBS:$PATH"
export PATH

"$PY" "$ROOT/scripts/demo_record.py" "$START" "$ROOT/docs/start.cast.json" \
    "$WRING" start
"$PY" "$ROOT/scripts/demo_render.py" "$ROOT/docs/start.cast.json" \
    "$ROOT/docs/start.svg" "wring start — preflight, gates, agent, receipt"
