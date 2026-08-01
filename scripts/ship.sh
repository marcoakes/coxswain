#!/bin/sh
# Commit and push, but only behind the gate — the repo's own discipline
# applied to the repo's own history.
#
#   scripts/ship.sh <path-to-commit-message-file>
#
# Refuses if ruff or pytest is red. "Never claim a check ran unless it ran"
# is law 1; this is the version of it that cannot be forgotten in a hurry.
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 2

MESSAGE=${1:-}
if [ -z "$MESSAGE" ] || [ ! -f "$MESSAGE" ]; then
    echo "usage: scripts/ship.sh <commit-message-file>" >&2
    exit 2
fi

"$ROOT/scripts/check.sh" || {
    echo "refusing to ship: the gate is red" >&2
    exit 1
}

git add -A
git commit -q -F "$MESSAGE" || exit 1
git push || exit 1

git log --oneline -1
