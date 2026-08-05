#!/bin/sh
# Run SETUP.md's own commands and check they do what the runbook says.
#
# The runbook's first real outing (a fresh Mac, 2026-08-04) found nine
# defects — a Python gate testing the wrong interpreter, an install path that
# failed twice on stock macOS, a wrong `ls` path, a doctor transcript that had
# been written rather than captured. Every one of them was a claim nobody had
# executed. This executes them.
#
# It does NOT cover steps 4/5/7 (container) — no runtime here, which is the
# situation that produced finding H and the reason step 7H exists.
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$(dirname "$0")/scratch.sh"
WORK=$(scratch_dir "${1:-}" setup-selftest) || exit 2

# The `wring` under test. SETUP.md step 3 installs it with `uv tool install`,
# which puts it in ~/.local/bin — so that is where to look first. The repo's
# .venv stays as a fallback for a developer working from a checkout.
#
# The old line prepended ONLY the venv, which the rewritten step 3 no longer
# creates. The prepend was a silent no-op and the script tested whatever
# `wring` happened to be on PATH, which might be an old release, or nothing
# at all (R2-06). Testing the wrong binary and testing no binary look
# identical in a passing log, so this now says which one it found and stops
# if there is none.
PATH="$HOME/.local/bin:$ROOT/.venv/bin:$PATH"
export PATH

if ! command -v wring >/dev/null 2>&1; then
    echo "FATAL: no 'wring' on PATH — there is nothing to test." >&2
    echo "  looked in: $HOME/.local/bin, $ROOT/.venv/bin, then \$PATH" >&2
    echo "  install it first, as SETUP.md step 3 does:" >&2
    echo "    uv tool install --force --python 3.12 $ROOT" >&2
    exit 2
fi

PASS=0
FAIL=0
ok()   { echo "  ok    $1"; PASS=$((PASS + 1)); }
bad()  { echo "  FAIL  $1"; FAIL=$((FAIL + 1)); }

echo "wring under test: $(command -v wring) ($(wring --version 2>&1))"
echo "scratch tree    : $WORK"
echo

if [ -d "$WORK" ]; then find "$WORK" -mindepth 1 -delete 2>/dev/null; fi
mkdir -p "$WORK" || exit 2

echo "== step 2 — the prerequisite gate =="
# Verbatim from SETUP.md.
FOUND=0
for p in python3.13 python3.12 python3.11 python3; do
    command -v "$p" >/dev/null 2>&1 || continue
    V=$("$p" --version 2>&1)
    echo "    $p -> $V"
    case "$V" in
        "Python 3.1"[1-9]*|"Python 3.2"*) FOUND=1 ;;
    esac
done
[ "$FOUND" -eq 1 ] && ok "an interpreter 3.11+ was found" \
    || bad "step 2's loop found no 3.11+ interpreter"

echo
echo "== step 3 — the verify command =="
wring --version | grep -q "^wring 0\.2" \
    && ok "wring --version starts 'wring 0.2'" \
    || bad "wring --version is not 0.2.x"
wring doctor --help >/dev/null 2>&1 \
    && ok "doctor present" || bad "doctor missing"

echo
echo "== step 6 — the workspace gate =="
mkdir -p "$WORK/wringer-workspace"
touch "$WORK/wringer-workspace/.wringer-write-test" \
    && rm "$WORK/wringer-workspace/.wringer-write-test" \
    && ok "workspace writable" || bad "workspace not writable"

echo
echo "== step 7H — the host branch, run TWICE =="
# Twice on purpose. The runbook promises every step is idempotent, and the
# first version of this block broke that promise two ways at once: a bare
# `git add -A` staged the previous run's `.wringer/` — two runs, two
# commits, nine tracked evidence files — and a second `git init` printed a
# re-init warning into a runbook that says to stop on unexplained output
# (R2-03, R2-04). Running it once could never have found either.
#
# Kept verbatim from SETUP.md step 7H apart from the path. If the runbook's
# block changes, change this one to match, or this stops testing the runbook
# and starts testing a paraphrase of it.
probe_7h() {
    mkdir -p "$WORK/wringer-workspace/probe" && cd "$WORK/wringer-workspace/probe" || exit 2
    { [ -d .git ] || git init -q -b main .; }
    git config user.email you@example.com
    git config user.name "You"
    printf 'def add(a, b):\n    return a + b\n' > calc.py
    printf 'version: 1\ngates:\n  - id: check\n    run: "grep -q return calc.py"\n' > .wringer.yaml
    printf '.wringer/\n' > .gitignore
    git add calc.py .wringer.yaml .gitignore
    git diff --cached --quiet || git commit -qm probe >/dev/null 2>&1
    wring verify
}

if probe_7h; then ok "wring verify exits 0"; else bad "wring verify failed"; fi

SECOND=$(probe_7h 2>&1)
if [ $? -eq 0 ]; then ok "7H is idempotent — a second run also exits 0"
else bad "7H failed on its second run"; fi

case "$SECOND" in
    *"re-init"*) bad "7H's second run prints a git re-init warning (R2-04)" ;;
    *)           ok "7H's second run prints no re-init warning" ;;
esac

COMMITS=$(git rev-list --count HEAD)
[ "$COMMITS" -eq 1 ] \
    && ok "two 7H runs leave exactly one commit" \
    || bad "two 7H runs left $COMMITS commits — the second staged the first's evidence"

TRACKED=$(git ls-files .wringer | wc -l | tr -d " ")
[ "$TRACKED" -eq 0 ] \
    && ok "no evidence bundle is tracked by git (R2-03)" \
    || bad "$TRACKED evidence file(s) committed into the probe repo (R2-03)"

git check-ignore -q .wringer \
    && ok "the probe ignores .wringer/" \
    || bad "the probe has no .gitignore rule for .wringer/"

echo
echo "== step 7's documented bundle contents =="
for want in manifest.json evidence.jsonl summary.md digests.json diff.patch status.txt; do
    n=$(ls .wringer/runs/*/"$want" 2>/dev/null | wc -l | tr -d " ")
    [ "$n" -ge 1 ] && ok "bundle has $want" || bad "bundle has no $want"
done
[ -d "$(ls -d .wringer/runs/*/gates 2>/dev/null | head -1)" ] \
    && ok "bundle has gates/" || bad "bundle has no gates/"

echo
echo "== step 8 — doctor from the clone, and from outside one =="
cd "$ROOT" || exit 2
wring doctor >/dev/null 2>&1 && ok "doctor exits 0 from the clone" \
    || bad "doctor is not clean in its own repo"

# Outside a repo, the three repository-scoped checks must SKIP — not fail,
# not silently pass. SETUP.md step 8 documents that state but its own
# command (`cd ~/wringer && wring doctor`) cannot produce it, because from
# the clone those three never skip (R2-01). Nothing executed the documented
# state until this. The runbook now carries the contrasting transcript, and
# these two checks are what stop that transcript rotting.
cd "$WORK" || exit 2
wring doctor >/dev/null 2>&1 \
    && ok "doctor exits 0 outside a repo (repo checks skipped)" \
    || bad "doctor still blocks outside a repo — finding D regressed"

SKIPS=$(wring doctor 2>/dev/null | grep -c '^- ')
[ "$SKIPS" -eq 3 ] \
    && ok "doctor prints three '-' lines outside a repo" \
    || bad "doctor printed $SKIPS '-' lines outside a repo, expected 3 (R2-01)"

# `grep -o | wc -l`, not `grep -c`: --json prints ONE line, so grep -c
# counts matching lines and answers 1 no matter how many skips there are.
JSON_SKIPS=$(wring doctor --json 2>/dev/null | grep -o '"status": "skip"' | wc -l | tr -d " ")
[ "$JSON_SKIPS" -eq 3 ] \
    && ok "doctor --json reports three \"status\": \"skip\" entries" \
    || bad "doctor --json reported $JSON_SKIPS skips, expected 3 (R2-01)"

echo
echo "-------------------------------------------"
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
