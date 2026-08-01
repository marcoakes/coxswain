#!/bin/sh
# `wring verify` on Wringer itself — the repo's own law, and what CI runs.
#
# Exists as a named script for the same reason as check.sh: this needs the
# venv on PATH (gates inherit it, so `ruff` is otherwise not found), and a
# compound one-liner that sets PATH matches no permission rule.
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 2
PATH="$ROOT/.venv/bin:$PATH"
export PATH

wring verify "$@"
CODE=$?
mkdir -p "$ROOT/.wringer/last"
echo "$CODE" > "$ROOT/.wringer/last/verify.exit"
echo "wring verify exit $CODE"
exit $CODE
