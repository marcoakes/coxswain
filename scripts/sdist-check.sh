#!/bin/sh
# Build the sdist and prove its test suite can actually RUN.
#
# The 0.2.0 sdist shipped 23 test modules and no conftest.py, because
# setuptools' default sdist packs `test*.py` and nothing else from tests/.
# Measured on that tarball: `pytest -q tests/` gave 12 failed, 259 passed,
# 276 errors — almost every one "fixture 'repo' not found". A suite that
# cannot run is worse than an absent one: it invites a packager to conclude
# the package is broken.
#
# MANIFEST.in grafts tests/. This checks the graft worked, from the tarball
# rather than from the working tree, because the working tree always has
# conftest.py and that is exactly what hid the bug.
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$(dirname "$0")/scratch.sh"
WORK=$(scratch_dir "${1:-}" sdist-check) || exit 2
UV="$HOME/.local/bin/uv"

rm -rf "$WORK"
mkdir -p "$WORK" || exit 2

echo "== build the sdist =="
"$UV" build --sdist --out-dir "$WORK/dist" "$ROOT" >/dev/null 2>&1 || {
    echo "FAIL: could not build the sdist"; exit 1; }
TARBALL=$(ls "$WORK"/dist/*.tar.gz 2>/dev/null | head -1)
[ -n "$TARBALL" ] || { echo "FAIL: no sdist produced"; exit 1; }
echo "  $(basename "$TARBALL")"

echo
echo "== the files a suite needs to run at all =="
FAIL=0
for required in tests/conftest.py tests/fake_acp_agent.py; do
    if tar -tzf "$TARBALL" | grep -q "/$required$"; then
        echo "  ok    $required is packed"
    else
        echo "  FAIL  $required is MISSING — the suite cannot run"
        FAIL=1
    fi
done

echo
echo "== run the packed suite, from the tarball =="
mkdir -p "$WORK/unpacked" || exit 2
tar -xzf "$TARBALL" -C "$WORK/unpacked" || exit 2
SRC=$(ls -d "$WORK"/unpacked/*/ | head -1)
"$UV" venv -q --python 3.12 "$WORK/venv" || exit 2
"$UV" pip install -q "$SRC[dev]" --python "$WORK/venv/bin/python" || {
    echo "FAIL: dev extras do not install from the sdist"; exit 1; }
cd "$SRC" || exit 2
# To a file, then read it. `pytest … | tail -3` puts pytest's exit code out of
# reach — `$?` is tail's, which is always 0 — so the first version of this
# script printed PASS over 13 failures. dash has no `pipefail`, and this is
# the same defect this series just fixed in verify-published.sh, made again
# here within the hour. Worth the extra two lines.
"$WORK/venv/bin/python" -m pytest -q > "$WORK/pytest.log" 2>&1
CODE=$?
tail -3 "$WORK/pytest.log"

echo
echo "-------------------------------------------"
if [ "$FAIL" -eq 0 ] && [ "$CODE" -eq 0 ]; then
    echo "PASS: the sdist ships a suite that runs"
    exit 0
fi
echo "FAIL: sdist suite is not runnable (files $FAIL, pytest $CODE)"
exit 1
