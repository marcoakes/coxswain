# Wringer on a pull request

Copy [`wringer.yml`](wringer.yml) to `.github/workflows/wringer.yml`.

It is the same shape this repository runs on itself
([`.github/workflows/tests.yml`](../../.github/workflows/tests.yml)) — a
recipe using a second idiom would be a recipe nobody here tests.

## What it enforces

| step | what it does | what fails the job |
|---|---|---|
| `wring verify --prove` | runs the gates **your** `.wringer.yaml` declares, then re-runs them against the pre-change tree | a required gate failing |
| upload artifact | attaches the evidence bundle to the run | — |
| `wring deliver` | refuses a bundle whose gates could not have failed | a `gates_vacuous` verdict, exit 1 |
| summary comment | posts `summary.md` to the PR | — |

**The third row is the one that is hard to buy elsewhere.** An AI-authored
change can arrive with green tests that pass whether or not the change is
there — a tautological assertion, a test that never exercises the new path.
`--prove` runs the same gates against the pre-change tree and records
`gates_vacuous` when they pass on both, and `wring deliver` will not deliver
that bundle. There is no flag to disable it, deliberately: the party being
audited does not get to choose whether the audit runs.

That refusal, captured from a real session:

<div align="center">

<img src="../../docs/vacuous.svg" alt="the gates went green and proved nothing" width="760">

</div>

## What it does not do

- **It never sends anything.** `wring deliver` here is a dry run — it writes
  the patch, the commit message and the MR body, and touches no git history.
  Writing history needs `--send`, which this workflow never passes. A test
  asserts it never appears.
- **It needs no credential.** Nothing in this workflow calls an LLM. The
  `pull-requests: write` permission is only for the summary comment.
- **It does not install your dependencies for you.** Your gates run *your*
  commands, so if `.wringer.yaml` declares `pytest -q`, pytest has to be
  installed in the job or the gate fails with `command not found` — which is
  Wringer working correctly. The recipe installs `.[dev]`; change that line to
  whatever your project actually needs.

## Two things worth changing

**`fetch-depth: 0`.** `--prove` builds the pre-change tree from history, so a
shallow clone makes the prove pass inconclusive rather than wrong — and
inconclusive is not what you want gating a merge.

**Requiring the check.** The workflow failing is only advisory until the
`verify` job is a required status check in the repository's branch protection
settings. That part is GitHub's, not Wringer's.

## Verifying the recipe still works

Every `wring` invocation in it is parsed against the real CLI by
`tests/test_docs.py`, so a renamed command or a removed flag fails this
repository's own suite. What that cannot prove is that GitHub's runner
behaves — a workflow under `examples/` is never executed here. If you run it,
the honest thing is to say so in `docs/MANUAL_CHECKS.md`.
