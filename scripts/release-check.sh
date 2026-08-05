#!/bin/sh
# The 0.2.0 release bar, checked rather than asserted.
#
# Builds from a CLEAN CLONE of origin/main into a throwaway venv and exercises
# the installed package — not the working tree, not an editable install. That
# distinction is the whole point: `pip install wringer` is what a stranger
# gets, and it is the only thing this script trusts.
#
# Every check prints its own true exit code. A wrapper's exit code can lie
# about which half failed; law 1 says never claim a check ran unless it ran.
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$(dirname "$0")/scratch.sh"
WORK=$(scratch_dir "${1:-}" release-check) || exit 2
UV="$HOME/.local/bin/uv"

PASS=0
FAIL=0

check() {
    name=$1
    shift
    if "$@" >/dev/null 2>&1; then
        echo "  ok    $name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $name  (exit $?)"
        FAIL=$((FAIL + 1))
    fi
}

rm -rf "$WORK"
mkdir -p "$WORK"
git clone -q "$ROOT" "$WORK/src" || exit 2
cd "$WORK/src" || exit 2
echo "HEAD: $(git log --oneline -1)"
echo

echo "== build and install, clean room =="
"$UV" venv -q --python 3.12 "$WORK/venv" || exit 2
"$UV" pip install -q . --python "$WORK/venv/bin/python" || {
    echo "  FAIL  the package does not install"; exit 1; }
WRING="$WORK/venv/bin/wring"
echo "  ok    installs"
echo "  version: $($WRING --version)"
echo

echo "== every command answers --help =="
for c in init verify run fleet resume judge spec plan get issue deliver \
         doctor explain; do
    check "wring $c --help" "$WRING" "$c" --help
done
echo

echo "== the documented happy path, in a scratch repo =="
PROBE="$WORK/probe"
mkdir -p "$PROBE" && cd "$PROBE" || exit 2
git init -q -b main .
git config user.email release@example.invalid
git config user.name "release check"
printf 'def add(a, b):\n    return a + b\n' > calc.py
printf 'version: 1\ngates:\n  - id: check\n    run: "grep -q return calc.py"\n' \
    > .wringer.yaml
git add -A && git commit -qm probe

check "wring doctor runs"            "$WRING" doctor --json
check "wring verify passes"          "$WRING" verify
check "wring verify --json"          "$WRING" verify --json
check "wring explain reads it back"  "$WRING" explain
# a glob inside `test -f` expands to several words and errors; count instead
for want in manifest.json evidence.jsonl summary.md digests.json; do
    found=$(ls .wringer/runs/*/"$want" 2>/dev/null | wc -l | tr -d " ")
    if [ "$found" -ge 1 ]; then
        echo "  ok    the bundle has $want"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  the bundle has no $want"
        FAIL=$((FAIL + 1))
    fi
done
echo

echo "== the release bar =="
cd "$WORK/src" || exit 2
test -f CHANGELOG.md && \
    { echo "  ok    CHANGELOG.md exists"; PASS=$((PASS + 1)); } || \
    { echo "  FAIL  no CHANGELOG.md"; FAIL=$((FAIL + 1)); }
grep -q "0.2.0" CHANGELOG.md && \
    { echo "  ok    CHANGELOG names 0.2.0"; PASS=$((PASS + 1)); } || \
    { echo "  FAIL  CHANGELOG does not name 0.2.0"; FAIL=$((FAIL + 1)); }
# the committed demo bundle must validate against the published schemas —
# it is the receipt the README points at
# The runtime install above proved `pip install wringer` gives a working CLI
# with PyYAML and nothing else. The suite needs the dev extras, so it gets its
# own install — added AFTER the runtime check, never before it.
"$UV" pip install -q '.[dev]' --python "$WORK/venv/bin/python" || {
    echo "  FAIL  dev extras do not install"; FAIL=$((FAIL + 1)); }
check "the suite is green"  "$WORK/venv/bin/python" -m pytest -q "$WORK/src/tests"

echo
echo "-------------------------------------------"
echo "$PASS passed, $FAIL failed   (clean clone at $WORK/src)"
[ "$FAIL" -eq 0 ]
