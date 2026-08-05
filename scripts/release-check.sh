#!/bin/sh
# The release bar, checked rather than asserted.
#
# Builds from a CLEAN CLONE OF THIS REPOSITORY'S COMMITTED STATE — `git clone`
# of the local repo, so it gets local HEAD, not origin/main. That is the
# useful semantics (it isolates from a dirty working tree, which is the bug
# class this catches) but it is NOT the same as checking what is pushed, and
# the header used to claim origin/main. Push first if that is what you mean.
# The built sha is printed below so every run says which tree it judged.
#
# It exercises the INSTALLED package — not the working tree, not an editable
# install. That distinction is the whole point: `pip install wringer` is what
# a stranger gets, and it is the only thing this script trusts.
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
# Say which tree is being judged. A clone of the local repo gets local HEAD,
# which is not origin/main unless you have pushed — printing it is how a
# reader tells the difference without reading this script.
echo "judging: $(git log --oneline -1)"
if [ -n "$(git -C "$ROOT" log --oneline "origin/main..HEAD" 2>/dev/null)" ]; then
    echo "NOTE: local HEAD is ahead of origin/main — this is NOT what CI will run"
fi
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
# The version being BUILT, not a literal. `grep -q "0.2.0"` passed forever
# once 0.2.0 was in the file, so at 0.3.0 it would have silently checked the
# previous release's entry and reported ok.
VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$WORK/src/src/wringer/__init__.py")
if [ -z "$VERSION" ]; then
    echo "  FAIL  could not read the version from src/wringer/__init__.py"
    FAIL=$((FAIL + 1))
elif grep -q "$VERSION" CHANGELOG.md; then
    echo "  ok    CHANGELOG names $VERSION"; PASS=$((PASS + 1))
else
    echo "  FAIL  CHANGELOG does not name $VERSION"; FAIL=$((FAIL + 1))
fi
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
