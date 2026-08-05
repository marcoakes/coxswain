#!/bin/sh
# The gate, run the way CI runs it: ruff then pytest, from the repo root,
# with the venv on PATH so gates find their own tools.
#
# A named script rather than an ad-hoc one-liner on purpose: permission rules
# match command prefixes, so `cd repo && a && b` matches nothing and asks a
# human every time. This asks once, forever.
#
# Writes each step's TRUE exit code to .wringer/last/, because a wrapper's
# own exit code can lie about which half failed.
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 2
PATH="$ROOT/.venv/bin:$PATH"
export PATH

mkdir -p "$ROOT/.wringer/last"

ruff check src tests examples scripts
LINT=$?
echo "$LINT" > "$ROOT/.wringer/last/lint.exit"

pytest -q
TEST=$?
echo "$TEST" > "$ROOT/.wringer/last/test.exit"

echo "---"
echo "ruff  exit $LINT"
echo "pytest exit $TEST"

[ "$LINT" -eq 0 ] && [ "$TEST" -eq 0 ]
