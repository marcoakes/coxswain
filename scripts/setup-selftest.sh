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
WORK=${1:-/private/tmp/claude-501/-Users-marc-Claude/setup-selftest}
PATH="$ROOT/.venv/bin:$PATH"
export PATH

PASS=0
FAIL=0
ok()   { echo "  ok    $1"; PASS=$((PASS + 1)); }
bad()  { echo "  FAIL  $1"; FAIL=$((FAIL + 1)); }

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
echo "== step 7H — the host branch =="
mkdir -p "$WORK/wringer-workspace/probe" && cd "$WORK/wringer-workspace/probe" || exit 2
git init -q -b main .
git config user.email you@example.com
git config user.name "You"
printf 'def add(a, b):\n    return a + b\n' > calc.py
printf 'version: 1\ngates:\n  - id: check\n    run: "grep -q return calc.py"\n' > .wringer.yaml
git add -A && git commit -qm probe >/dev/null
if wring verify; then ok "wring verify exits 0"; else bad "wring verify failed"; fi

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
cd "$WORK" || exit 2
wring doctor >/dev/null 2>&1 \
    && ok "doctor exits 0 outside a repo (repo checks skipped)" \
    || bad "doctor still blocks outside a repo — finding D regressed"

echo
echo "-------------------------------------------"
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
