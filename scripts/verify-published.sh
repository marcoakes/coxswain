#!/bin/sh
# Install Wringer FROM PYPI into a clean venv and prove it works.
#
# Not from the working tree, not from dist/, not editable — from the index,
# with the cache off, exactly as a stranger gets it. This is the last link in
# the Definition of PROVEN: everything else checks the code, and this checks
# the thing people actually download.
set -u

. "$(dirname "$0")/scratch.sh"
W=$(scratch_dir "${1:-}" pypi-check) || exit 2
UV="$HOME/.local/bin/uv"
# The version to check, defaulting to the one this working tree declares
# rather than to a literal. A hardcoded default rots into a script that
# green-lights the PREVIOUS release forever: at 0.3.0 a bare run would have
# installed and blessed 0.2.0 while reporting success.
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WANT=${2:-$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$ROOT/src/wringer/__init__.py")}
[ -n "$WANT" ] || { echo "FATAL: could not read the version from src/wringer/__init__.py" >&2; exit 2; }
echo "checking wringer==$WANT (source of truth: src/wringer/__init__.py)"

if [ -d "$W" ]; then find "$W" -mindepth 1 -delete 2>/dev/null; fi
mkdir -p "$W" || exit 2

"$UV" venv -q --python 3.12 "$W/venv" || exit 2
echo "installing wringer==$WANT from PyPI (cache off)..."
"$UV" pip install -q --no-cache "wringer==$WANT" --python "$W/venv/bin/python" || {
    echo "FAIL: could not install from PyPI"; exit 1; }

WRING="$W/venv/bin/wring"
echo "version : $($WRING --version)"
echo "deps    :"
"$UV" pip list --python "$W/venv/bin/python" 2>/dev/null | tail -n +3 | sed 's/^/          /'

echo
MISSING=0
for c in init verify run fleet resume judge spec plan get issue deliver \
         doctor explain; do
    "$WRING" "$c" --help >/dev/null 2>&1 || { echo "  MISSING $c"; MISSING=1; }
done
[ "$MISSING" -eq 0 ] && echo "all thirteen commands present"

echo
echo "a real verification, from the published package:"
mkdir -p "$W/probe" && cd "$W/probe" || exit 2
git init -q -b main .
git config user.email p@example.invalid && git config user.name probe
printf 'def add(a, b):\n    return a + b\n' > calc.py
printf 'version: 1\ngates:\n  - id: check\n    run: "grep -q return calc.py"\n' \
    > .wringer.yaml
git add -A && git commit -qm probe
"$WRING" verify
CODE=$?
echo "verify exit $CODE"
DIGESTS=0
ls .wringer/runs/*/digests.json >/dev/null 2>&1 \
    && echo "digests.json written" || { echo "NO digests.json"; DIGESTS=1; }

# Every failure reaches the exit code. `MISSING` used to be printed and then
# dropped on the floor — the script exited with `verify`'s code alone, so it
# could report "MISSING judge" and still exit 0, which is a green light for a
# release that is missing a command.
echo
if [ "$CODE" -eq 0 ] && [ "$MISSING" -eq 0 ] && [ "$DIGESTS" -eq 0 ]; then
    echo "PASS: wringer==$WANT installs from the index and works"
    exit 0
fi
echo "FAIL: wringer==$WANT (verify exit $CODE, missing commands $MISSING, digests $DIGESTS)"
exit 1
