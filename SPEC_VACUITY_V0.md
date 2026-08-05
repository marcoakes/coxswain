# SPEC — vacuity detection (P5, part 2)

*Drafted 2026-08-03 by the planning window. **Rulings 1 and 2 decided by
Marc 2026-08-05 (§3a, §3b, §5). DRAFT on ruling 3; not binding until he
says so.** His one remaining open ruling is marked ⚖.*

## Positioning

> **"Prove the gates can fail."** The agent wrote tautological tests, its
> gates pass, and the green tick means nothing — reward-hacking by another
> name, and the failure mode everyone in this field fears and nobody
> guards. The counter is deterministic: if the gates still pass *without*
> the change, they never tested it.

## 1. The mechanism

`wring verify --prove` runs the normal verification, and then, **only if
every required gate passed**:

1. Create a scratch worktree detached at HEAD — `fleet.make_worktree`'s
   existing machinery, same cleanup guarantee. The worktree at HEAD *is*
   the pre-change tree: tracked edits absent, untracked files naturally
   missing. No reverse-patching, no cleverness.
2. Run the same declared gates there, same timeouts, same capture.
3. Compare per gate:

| changed tree | pre-change tree | meaning |
|---|---|---|
| pass | **fail** | the gate tests this change — what proof looks like |
| pass | **pass** | the gate is *insensitive* to this change |

A lint gate passing on both trees is ordinary. **Every** gate passing on
both is the signal: verdict `gates_vacuous`, and the change ships with a
green tick that proved nothing.

## 2. Where the verdict lives

A sibling `vacuity.json` (`wringer.vacuity.v1`) in the run bundle — the
`digests.json` pattern, because `wringer.evidence.v1` is frozen and this
must not touch it. Per-gate rows (`gate_id`, changed-tree result,
pre-change result, `sensitive: bool`), whole-set verdict
(`proven | gates_vacuous | not_applicable`), and the pre-change gate logs
kept under `vacuity/` in the bundle — evidence, not summary.

`not_applicable`: the tree has no changes (nothing to be vacuous about),
or a required gate failed the normal run (`--prove` never runs; there is
nothing to prove about a failure — law 3's shape).

**Ordering:** `digests.json` still writes **last**, after `vacuity.json`,
so the digest covers the vacuity evidence too. The existing write-order
test extends.

## 3. Consequences downstream — where the teeth are

- **`wring attest` refuses `gates_vacuous`** (SPEC_PROVENANCE §3 gains the
  refusal): no attestation for gates that proved nothing. This is the
  rubric line "a new behaviour needs a test that fails without it" turned
  from a judge's opinion into a machine check.
- **The loop, when the repo opts in** (`run.prove: true` — see ruling 1):
  a converged-but-vacuous iteration does not converge; the worker gets a
  brief that says *"write a test that fails without your change"* and the
  loop continues. The plateau fingerprint already prevents thrash.
- **`wring deliver` refuses a `gates_vacuous` bundle** — see §3b.

## 3a. How it is switched on — BINDING (ruling 1)

**The config declares the policy. A flag may only tighten it.**

| | effect |
|---|---|
| `run.prove: true` in `.wringer.yaml` | every `wring run` in this repo proves |
| `--prove` on `wring verify` or `wring run` | proves this once, whatever the config says |
| `--no-prove` | **does not exist, deliberately** |

The convenience reading of this ruling — "repos opt in once" — is not the
reason. The reason is **authority over the supervised party**.

`wring run` drives an agent that writes code, and `--prove` exists
precisely to catch that agent writing tautological tests. If switching it
on were a flag, then whoever invokes `wring run` decides whether the check
happens — and that invoker is increasingly the agent itself, or a script
the agent wrote. **The audited party does not get to choose whether the
audit runs.** `.wringer.yaml` is committed and reviewed like code; what
counts as *proven* for a repository belongs there.

The flag remains, in the tightening direction only, so someone can try
`--prove` on one run without editing config or making a commit. Nothing
can turn off what the repo declared.

This is the same shape as `approved: false` in SPEC_INTENT_V0 — *"an
interlock no flag, environment variable or model reply may flip, and there
is deliberately no `--yes`"* — and matching it is the point. Two features
ruling the same way makes **flags may tighten, never loosen** a rule people
learn once, rather than a per-feature surprise.

**Discoverability, decided with it.** A config-only setting nobody knows
about is a setting nobody uses, so `wring init`'s template names
`run.prove` in a commented block, the way it already teaches with commented
example gates. `wring verify` does **not** warn when vacuity was not
checked. The placeholder warning is tolerable because it disappears when
the user fixes it; this one would never disappear unless they accept
doubled gate time, so it would be permanent noise — and a warning nobody
can act on is one everybody learns to skip.

## 3b. `wring deliver` refuses a vacuous run — BINDING (ruling 2)

A bundle whose `vacuity.json` reads `gates_vacuous` is not deliverable.
`Refused`, exit 1 — the same family as *"its gates did not pass"*, sitting
directly beside it in `deliver.py`, because it is the same statement: this
bundle is not evidence that the change is mergeable.

**There is no `--allow-vacuous`, and that is not an oversight.** Ruling 1
established that flags may tighten and never loosen; a flag that waves this
refusal through would be the first counter-example, in the same spec, one
section later. `wring deliver` has never had an `--ignore-failures` for a
failed gate either. The escape from this refusal is the same as the escape
from that one: **make the evidence better, not the check weaker.** Write a
test that fails without the change, verify again, deliver.

### The trap, and why this framing defuses it

The honest objection to this ruling is that turning on `--prove` to *learn*
something also, implicitly, blocks your delivery path — a strictness the
repo never explicitly chose.

The framing that resolves it: **the refusal attaches to the bundle, not to
the user or the flag.** A run without `--prove` writes no `vacuity.json`,
so `wring deliver` behaves exactly as it does today — unchanged, for every
repo that has not opted in. The strictness applies only to runs that
actually measured, and only when the measurement came back saying nothing
was proven. Nobody is blocked for asking the question; they are blocked by
the answer, which is the correct thing to be blocked by.

### The refusal must be actionable

A refusal that only says *no* converts this feature into something people
turn off. It names, in the message: the verdict, **which gates were
insensitive**, the one-line fix (*"write a test that fails without your
change"*), and the path to `vacuity/` so the reader can see both trees'
output. Same standard as the failing-gate refusal, which already names the
gate rather than saying "a gate failed".

### Known limit, recorded rather than closed

In a repo that declared `run.prove: true`, a plain `wring verify` bundle
carries no vacuity verdict at all, so it delivers. The declaration binds
the loop; it does not retroactively bind every other way of producing a
bundle. Closing that would mean `deliver` refusing any bundle **lacking** a
verdict whenever the repo declared one — strictly more than ruling 2
approved, and a change that would make `wring verify` alone unable to
produce a deliverable bundle in such a repo. It is written down here as an
open question rather than smuggled in.

## 4. Cost, stated plainly

`--prove` roughly doubles gate time and is **opt-in** everywhere: a flag
on `verify`, a config key for the loop. The docs say why you would pay it
in one sentence: *a green tick that cannot fail is worth nothing.*

## 5. Rulings

1. **Loop opt-in shape — DECIDED 2026-08-05: config declares, flags may
   only tighten.** Full design and reasoning in §3a. `run.prove: true` in
   `.wringer.yaml`; `--prove` turns it on for one run; there is no
   `--no-prove`. Chosen for authority over the supervised party rather than
   for convenience, and matched deliberately to the `approved: false`
   interlock so that *flags may tighten, never loosen* is one rule instead
   of two precedents.

2. **Should `wring deliver` refuse a vacuous run? — DECIDED 2026-08-05:
   yes.** Design in §3b. `Refused`, exit 1, beside "its gates did not
   pass", because it is the same statement. No `--allow-vacuous`: ruling 1
   banned loosening flags and this would be the first counter-example, one
   section later in the same spec.

   The acknowledged catch — that opting into `--prove` implicitly tightens
   delivery — is answered by scope rather than by an escape hatch. The
   refusal attaches to the *bundle*: a run without `--prove` writes no
   verdict and delivers exactly as it does today. Nobody is blocked for
   asking the question, only by the answer.
3. ⚖ **Worktree cost guard:** repos with huge working trees pay a checkout
   per `--prove`. Accept (it's opt-in), or add a declared ceiling?

## 6. Non-goals (binding once approved)

Mutation testing (per-mutant analysis is a different product) · flakiness
detection (a gate failing *sometimes* pre-change is out of scope; first
result rules) · Windows · proving *optional* gates (they don't decide
outcomes) · any LLM involvement — this is deterministic or it is nothing.

## 7. Definition of DONE

- [ ] a planted tautological test (`assert True`) yields `gates_vacuous`;
      the demo repo's real test yields `proven` — both captured
- [ ] a mixed set (sensitive test gate + insensitive lint gate) reports
      per-gate sensitivity and whole-set `proven`
- [ ] a failed normal run never triggers the prove pass
- [ ] **§3a** — `run.prove: true` makes every `wring run` prove; `--prove`
      proves once against a config that says nothing; `--no-prove` is not a
      flag and `wring run --no-prove` exits 2 rather than silently ignoring
      it; and **no flag or environment variable can turn off `run.prove:
      true`** — the test that matters, mirroring the one that guards
      `approved: false`
- [ ] **§3a** — `wring init`'s template names `run.prove` in a commented
      block, and `wring verify` prints no warning when vacuity was not
      checked
- [ ] **§3b** — a `gates_vacuous` bundle is refused by `wring deliver` with
      exit 1, and the message names the insensitive gates and the fix; a
      bundle with **no** `vacuity.json` delivers exactly as it does today,
      so no repo that has not opted in changes behaviour; and `--allow-
      vacuous` is not a flag
- [ ] the scratch worktree is gone afterwards, pass or fail or Ctrl-C
- [ ] `digests.json` covers `vacuity.json` and the `vacuity/` logs
- [ ] attest refuses `gates_vacuous` with a test
- [ ] `wringer.vacuity.v1` under `schema/`, freeze-guard extended
- [ ] docs carry the captured vacuous-then-fixed loop transcript
