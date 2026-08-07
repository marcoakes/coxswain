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

# ---------------------------------------------------------------------------
# The third recording: the agent lies, Wringer catches it.
#
# HEAD is GREEN. The worker is then handed a change with a real test that
# catches a real bug, and it "fixes" the failure by making the test
# tautological — `assert multiply(3, 4) == multiply(3, 4)`. The gates go green
# and the loop reports convergence. The bug is still there.
#
# `wring verify --prove` re-runs those gates against the pre-change tree. They
# pass there too, so they proved nothing about the change: `gates_vacuous`.
# `wring deliver` then refuses the bundle, exit 1.
#
# **Why the baseline must be green.** `--prove` compares against HEAD, so it
# catches gates that could not fail — not an agent deleting a test that was
# already failing at HEAD, which SPEC_VACUITY_V0 §5a states as a known limit.
# Committing the failing test would therefore record `sensitive` and tell the
# opposite story. The tree is left DIRTY for the same reason: a clean tree
# makes `--prove` return `not_applicable` and write no verdict at all.
#
# The gate is `python3 -m pytest -q` and the test imports only the repo's own
# module, because the pre-change worktree carries TRACKED FILES ONLY — a gate
# needing an installed dependency fails there on a missing environment, and
# the comparison reads that failure as PROOF.
# ---------------------------------------------------------------------------
VACUOUS=$(scratch_dir "${1:-}" vacuous) || exit 2
# The bare `origin` gets a scratch of its own rather than a path derived by
# string-appending to $VACUOUS: `scratch.sh` constructs safe answers, and
# building one by hand next to it is how that guarantee gets lost. It also
# has to be CLEARED — a bare repo surviving from a previous run already has
# `main`, so the push below fails and `set -eu` kills the script before the
# recording happens.
ORIGIN=$(scratch_dir "${1:-}" vacuous-origin) || exit 2
for tree in "$VACUOUS" "$ORIGIN"; do
    if [ -d "$tree" ]; then find "$tree" -mindepth 1 -delete 2>/dev/null; fi
    mkdir -p "$tree"
done
cd "$VACUOUS"

git init -q -b main .
git config user.email demo@example.invalid
git config user.name "demo"
echo ".wringer/" > .gitignore

cat > calc.py <<'EOF'
def add(a, b):
    return a + b
EOF

cat > test_calc.py <<'EOF'
from calc import add


def test_add():
    assert add(2, 2) == 4
EOF

cat > .wringer.yaml <<'EOF'
version: 1
gates:
  - id: test
    run: "python3 -m pytest -q"

run:
  worker: "sh ./fix.sh"
  max_iterations: 3

deliver:
  branch: "wringer/{run}"
EOF

git add -A
git commit -qm "a calculator, and a test that passes"

# A real `origin` on disk. `wring deliver` refuses when the remote's default
# branch cannot be resolved, and that refusal would be recorded INSTEAD of the
# vacuity one — the recording would show a true message about the wrong thing.
git init -q --bare -b main "$ORIGIN"
git remote add origin "$ORIGIN"
git push -q origin main
git remote set-head origin -a

# The change an agent is asked to land: a new function with a real bug, and a
# real test that catches it. The gates fail here, which is what gives the loop
# something to do.
cat > calc.py <<'EOF'
def add(a, b):
    return a + b


def multiply(a, b):
    return a + b
EOF

cat > test_calc.py <<'EOF'
from calc import add, multiply


def test_add():
    assert add(2, 2) == 4


def test_multiply():
    assert multiply(3, 4) == 12
EOF

# The lie. It stands in for a coding agent, as `demo.sh`'s first recording
# does, so the demo is honest about running no agent and reproducible by
# anyone. What it does is what matters and it is exactly what a reward-hacking
# agent does: make the assertion true rather than the code correct.
cat > fix.sh <<'EOF'
sed 's/multiply(3, 4) == 12/multiply(3, 4) == multiply(3, 4)/' test_calc.py > t
mv t test_calc.py
EOF

"$PY" "$ROOT/scripts/demo_record.py" "$VACUOUS" "$ROOT/docs/vacuous.cast.json" \
    "$WRING" vacuous
"$PY" "$ROOT/scripts/demo_render.py" "$ROOT/docs/vacuous.cast.json" \
    "$ROOT/docs/vacuous.svg" "the gates went green and proved nothing"
