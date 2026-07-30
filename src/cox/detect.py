"""Project command detection for `cox init`.

Day-1 build: a static, commented template — the spec's own guidance is
"if detection is uncertain, generate comments rather than being clever".
Real detection of build/test/lint commands lands before the v0.1.0
release bar ("cox init works in an empty-ish Python repo") is checked.
"""

TEMPLATE = """\
# .cox.yaml — the gates Coxswain runs to prove a change is mergeable.
# Spec: https://github.com/marcoakes/coxswain/blob/main/SPEC_COX_VERIFY_V0.md
#
# Rules: gates run in order, cheapest first. A failing required gate
# fails the run (exit 1). Mark a gate `optional: true` to record its
# failure without failing the run. Edit the commands to match this
# project, then run: cox verify
version: 1

gates:
  - id: format
    run: make format-check
    optional: true

  - id: lint
    run: make lint

  - id: test
    run: make test

evidence:
  include:
    - git.diff
    - git.status
    - env
    - logs
"""


def template() -> str:
    return TEMPLATE
