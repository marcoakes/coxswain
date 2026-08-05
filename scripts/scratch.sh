# Where a script may create — and destroy — a scratch tree.
#
# Sourced, not executed. Every caller points a recursive delete at what this
# returns, so it has two jobs: pick a default that is right on whatever
# machine this is, and refuse a target that would be a disaster.
#
# Both jobs come from one finding. Five scripts in here defaulted to a
# sandbox path under /private/tmp named after one developer's machine and
# one developer's uid, and three of them `rm -rf` it. A field run on a
# different Mac found it before it cost anyone anything
# (docs/field-report-2026-08-05.md, R2-05). The default is now $TMPDIR,
# which every machine has and every machine agrees is disposable.
#
# The literal path is deliberately not written here: tests/test_docs.py
# greps every script for it, and an explanation that trips its own guard is
# not worth the explanation.
#
# One place rather than five copies: a safety check that can drift between
# copies is not a safety check.
#
# Usage:  WORK=$(scratch_dir "${1:-}" setup-selftest) || exit 2

scratch_dir() {
    _requested=${1:-}
    _name=${2:?scratch_dir needs a name}
    if [ -n "$_requested" ]; then
        _dir=$_requested
    else
        # macOS sets TMPDIR with a trailing slash; Linux usually does not.
        _tmp="${TMPDIR:-/tmp}"
        _dir="${_tmp%/}/wringer-$_name"
    fi

    case "$_dir" in
        /|"$HOME"|"$HOME"/)
            echo "scratch_dir: refusing to use '$_dir' as a scratch tree" >&2
            return 2
            ;;
        /*)
            # Strip a trailing slash so "$dir"/x is never "$dir//x".
            printf '%s\n' "${_dir%/}"
            return 0
            ;;
        *)
            echo "scratch_dir: '$_dir' must be an absolute path" >&2
            return 2
            ;;
    esac
}
