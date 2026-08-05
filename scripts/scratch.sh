# Where a script may create — and destroy — a scratch tree.
#
# Sourced, not executed. Five scripts point `rm -rf` or `find -delete` at
# what this returns, so it is the single most dangerous line in the repo and
# it is worth being paranoid about.
#
# It exists because those five scripts each defaulted to a sandbox path under
# /private/tmp named after one developer's machine and one developer's uid —
# a recursive delete aimed at somebody else's filesystem (see
# docs/field-report-2026-08-05.md, R2-05). The default is now $TMPDIR, which
# every machine has and every machine agrees is disposable.
#
# The literal old path is deliberately not written here: tests/test_docs.py
# greps every script for it, and an explanation that trips its own guard is
# not worth the explanation.
#
# HOW IT IS SAFE. The first version of this file tried to be safe by
# REFUSING dangerous answers — "/" and "$HOME" — and that is a blacklist over
# unnormalised strings, which loses to any equivalent spelling. It did:
# `scratch_dir "//"` returned `/`, and `$HOME//` and `$HOME/.` returned the
# home directory, all with exit 0, because a second slash dodged the literal
# match and was then stripped. Every one of those was a live `rm -rf`.
#
# So this does not decide whether an answer is dangerous. It *constructs* an
# answer that cannot be: the caller supplies a base directory, and the leaf
# component is always `wringer-<name>`, chosen here. Whatever the base — "/",
# "$HOME", "..", something pathological — the delete target is a directory
# literally named `wringer-<name>`, so the blast radius is a directory this
# repo's own scripts created. There is nothing to outsmart.
#
# Usage:  WORK=$(scratch_dir "${1:-}" setup-selftest) || exit 2
#
# NOTE the argument is the PARENT directory, not the scratch tree itself:
# `scripts/foo.sh /tmp/mine` works in /tmp/mine/wringer-foo.

scratch_dir() {
    _scratch_name=${2:?scratch_dir needs a name}
    # The name becomes a path component, so it may not contain one.
    case "$_scratch_name" in
        "" | *[!A-Za-z0-9_-]*)
            echo "scratch_dir: name '$_scratch_name' must match [A-Za-z0-9_-]+" >&2
            return 2
            ;;
    esac

    _scratch_base=${1:-}
    if [ -z "$_scratch_base" ]; then
        _scratch_base=${TMPDIR:-/tmp}
    fi

    case "$_scratch_base" in
        /*) ;;
        *)
            # Relative would put the tree under whatever the caller's cwd
            # happens to be, which for these scripts is often the repo.
            echo "scratch_dir: base '$_scratch_base' must be an absolute path" >&2
            return 2
            ;;
    esac

    # EVERY trailing slash, not one. "$HOME//" names the same directory as
    # "$HOME", and stripping a single slash is what let the old version be
    # fooled.
    while :; do
        case "$_scratch_base" in
            ?*/) _scratch_base=${_scratch_base%/} ;;
            *) break ;;
        esac
    done
    # "/" survives the loop above; empty it so the result is "/wringer-x"
    # rather than "//wringer-x".
    [ "$_scratch_base" = "/" ] && _scratch_base=""

    printf '%s/wringer-%s\n' "$_scratch_base" "$_scratch_name"
}
