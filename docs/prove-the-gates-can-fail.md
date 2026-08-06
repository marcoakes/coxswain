# Prove the gates can fail

*The agent wrote tautological tests, its gates pass, and the green tick means
nothing. `wring verify --prove` is the deterministic counter: **if the gates
still pass without the change, they never tested it.***

This is [SPEC_VACUITY_V0.md](../SPEC_VACUITY_V0.md) end to end. Every block
below is **real captured output** from scratch repositories with `file://`
remotes.

---

## The mechanism

A scratch worktree detached at HEAD. That tree *is* the pre-change tree —
tracked edits absent, untracked files naturally missing — so there is no
reverse-patching and no cleverness. Run the same declared gates there and
compare:

| changed tree | pre-change tree | meaning |
|---|---|---|
| pass | **fail** | the gate tests this change — what proof looks like |
| pass | **pass** | the gate is *insensitive* to this change |

A lint gate passing on both is ordinary. **Every** required gate passing on
both is the signal.

## Case A — the loop's own shape: `proven`

HEAD carries a bug and a test that catches it. That is the state you point
`wring run` at.

```console
$ wring verify
✗ test failed        0.1s

FAIL: test_adds (test_calc.AddTest)
AssertionError: -1 != 5
```

The worker fixes `add()`. Now:

```console
$ wring verify --prove
✓ test passed        0.0s
```

```json
{
  "verdict": "proven",
  "reason": "test failed on the pre-change tree, so the gates test this change",
  "worktree_ms": 21,
  "prove_ms": 58,
  "setup": null,
  "gates": [
    {
      "gate_id": "test",
      "changed": "passed",
      "pre_change": "failed",
      "sensitive": true,
      "cites": "FAILED (failures=1)",
      "pre_change_log": "vacuity/001_test.stdout.log"
    }
  ]
}
```

`wring deliver` proceeds, exit 0.

## Case B — a green repo and a tautology: `gates_vacuous`

A working CSV exporter, committed and green. The change adds `to_tsv()`, and
the test the agent wrote for it is `self.assertTrue(True)`.

```console
$ wring verify
✓ test passed        0.0s

$ wring verify --prove
✓ test passed        0.0s
```

```json
{
  "verdict": "gates_vacuous",
  "reason": "every required gate passed without the change too (test), so they proved nothing about it — write a test that fails without your change",
  "gates": [
    {
      "gate_id": "test",
      "changed": "passed",
      "pre_change": "passed",
      "sensitive": false,
      "cites": null
    }
  ]
}
```

And delivery stops:

```console
$ wring deliver
wring deliver: refusing to deliver 20260806-103447-e720 — it recorded `gates_vacuous`. `test` passed on the pre-change tree too, so they proved nothing about this change. The fix is to write a test that fails without your change, then verify again; both trees' output is in 20260806-103447-e720/vacuity/ if you want to see why. There is no flag for this — make the evidence better, not the check weaker
```

Exit 1. **There is no `--allow-vacuous`,** and that is not an oversight: a
flag may tighten what the repo declared and never loosen it, so a flag waving
this through would be the first counter-example one section later in the same
spec. The escape is the same as for a failing gate — make the evidence better,
not the check weaker.

The summary a human opens carries the same table:

```markdown
## Vacuity — **gates_vacuous**

| gate | changed tree | pre-change tree | tests this change | because |
|---|---|---|---|---|
| test | passed | passed | NO | — |

> ⚠ **Every required gate passed without the change too, so they proved
> nothing about it.** Write a test that fails without your change, then
> verify again.

Both trees' output: [`vacuity/`](vacuity/) · worktree 22ms, prove 57ms
```

## The trap: a false `proven`

`git worktree add --detach` carries **tracked files and nothing else** — no
`.venv`, no `node_modules`, no build cache, because those are gitignored. A
gate of `pytest -q` therefore runs where the project is not installed, and
fails. The table above then reads *pass on changed, fail on pre-change* and
concludes **the gate tests this change**.

That would fire on every run in any repo whose dependencies are not committed,
however tautological the tests — the feature built to catch reward-hacking
certifying it. Two things close it, and neither is optional:

**`run.prove_setup`** runs in the scratch worktree before the pre-change
gates. Every repo already has this command, because it is in their CI. If it
fails the verdict is `inconclusive` — never `proven`, and never silently
dropped.

```yaml
run:
  prove: true
  prove_setup: "uv sync --frozen"
```

**Every `sensitive` row cites the failure it rests on.** A row saying "this
gate failed without your change" is only meaningful if you can see *why* it
failed:

```
| test | passed | failed | yes | ModuleNotFoundError: No module named 'yourproject' |
```

That is instantly legible as a broken environment rather than convincing as a
caught regression. Wringer deliberately does **not** try to classify the
failure — a verdict that shows its working is the product; one that hides it
is the thing this spec exists to prevent.

## How it is switched on

**The config declares the policy. A flag may only tighten it.**

| | effect |
|---|---|
| `run.prove: true` in `.wringer.yaml` | every `wring run` in this repo proves |
| `--prove` on `wring verify` or `wring run` | proves this once, whatever the config says |
| `--no-prove` | **does not exist, deliberately** — `wring run --no-prove` exits 2 |

The reason is not convenience. `wring run` drives an agent that writes code,
and `--prove` exists precisely to catch that agent writing tautological tests.
If switching it on were a flag, whoever invokes `wring run` would decide
whether the check happens — and that invoker is increasingly the agent itself,
or a script the agent wrote. **The audited party does not get to choose
whether the audit runs.** `.wringer.yaml` is committed and reviewed like code.

No flag and no environment variable can turn off `run.prove: true`. That is
the same shape as `approved: false` in SPEC_INTENT_V0, matched on purpose, so
*flags may tighten, never loosen* is one rule people learn once.

## Cost

`--prove` roughly doubles gate time. **There is no configurable ceiling**,
because every answer to "what happens when you hit it" is worse than the cost:
skipping the pass reads as `proven` while nothing was checked — the vacuity
failure reintroduced by the vacuity feature — refusing is a worse-timed block,
and warning does nothing. So it is measured instead: `worktree_ms` and
`prove_ms` sit beside the per-gate rows, and a repo decides with numbers rather
than guessing a threshold.

## What it does not catch — the honest limit

The pre-change tree is **HEAD**. So a gate fails there when HEAD was already
red and the change fixes it, and passes there when HEAD was green.

That means `--prove` answers one question well — *did this change add anything
that could have failed?* — and does not answer another: **it cannot tell you
that an agent neutered a test that was already failing.** In that case the
gate genuinely does fail at HEAD, so the verdict is `proven`, and it is
`proven` for the wrong reason.

Catching that needs the new tests applied to the old source, which is
reverse-patching, which §1 of the spec rules out by name. Recorded here as a
known limit rather than left for someone to discover: `--prove` is a strong
check against *green-baseline reward hacking* and is not a general
tamper-detector for the test suite. The `judged_by` clause and a human reading
`diff.patch` are what cover the rest.
