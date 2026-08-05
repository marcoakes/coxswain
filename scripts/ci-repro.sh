#!/bin/sh
# Reproduce CI locally: a FRESH CLONE of this repository's COMMITTED state
# into a scratch dir, a fresh venv, and the suite run there.
#
# `git clone` of the local repo, so it gets local HEAD — not origin/main,
# which the header used to claim. Isolating from the dirty working tree is
# the point and that still holds; being identical to what CI will run does
# NOT, unless you have pushed. The cloned sha is printed at the end.
#
# Catches the class of bug that "works on my machine" always means — a test
# that passes only because of untracked state in the working tree, or a file
# that was never committed. CI logs on this repo are not readable without
# auth (403), so this is how a red build gets diagnosed.
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$(dirname "$0")/scratch.sh"
WORK=$(scratch_dir "${1:-}" ci-repro) || exit 2
UV="$HOME/.local/bin/uv"

rm -rf "$WORK"
mkdir -p "$WORK"
git clone -q "$ROOT" "$WORK/wringer" || exit 2
cd "$WORK/wringer" || exit 2

echo "HEAD: $(git log --oneline -1)"

"$UV" venv -q --python 3.12 .venv || exit 2
"$UV" pip install -q -e '.[dev]' --python .venv/bin/python || exit 2

# Run with NO ambient git identity, which is what a CI runner has.
#
# macOS invents `user@host` when git.user is unset, so a test that needs an
# identity passes here and fails on GitHub's Linux runners, where the hostname
# is not fully qualified and git refuses to guess. That divergence cost three
# red builds that could not be diagnosed, because this repo's CI logs are not
# readable without auth. Reproducing it locally is the whole point of this
# script.
HOME="$WORK/nohome" \
GIT_CONFIG_GLOBAL=/dev/null \
GIT_CONFIG_SYSTEM=/dev/null \
GIT_CONFIG_COUNT=1 \
GIT_CONFIG_KEY_0=user.useConfigOnly \
GIT_CONFIG_VALUE_0=true \
    .venv/bin/pytest -q
CODE=$?
echo "---"
echo "pytest exit $CODE (clone of local HEAD $(git -C "$WORK/wringer" rev-parse --short HEAD), no ambient git identity)"
exit $CODE
