# SPEC — vacuity detection (P5, part 2)

*Drafted 2026-08-03 by the planning window. **DRAFT — awaiting Marc's
approval; not binding until he says so.** His open rulings are marked ⚖.*

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
- **The loop, when the repo opts in** (`run.prove: true` — ⚖ see rulings):
  a converged-but-vacuous iteration does not converge; the worker gets a
  brief that says *"write a test that fails without your change"* and the
  loop continues. The plateau fingerprint already prevents thrash.
- `wring deliver` — ⚖ ruling 2.

## 4. Cost, stated plainly

`--prove` roughly doubles gate time and is **opt-in** everywhere: a flag
on `verify`, a config key for the loop. The docs say why you would pay it
in one sentence: *a green tick that cannot fail is worth nothing.*

## 5. ⚖ Marc's rulings, needed at approval

1. **Loop opt-in shape:** `run.prove: true` in config (recommended —
   repos opt in once) vs `--prove` on `wring run` only.
2. **Should `wring deliver` refuse a vacuous run?** Recommended: yes, same
   exit-1 family as "gates did not pass" — but it makes `--prove` + deliver
   strictly stricter, which is a behaviour change a repo chose only
   implicitly.
3. **Worktree cost guard:** repos with huge working trees pay a checkout
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
- [ ] the scratch worktree is gone afterwards, pass or fail or Ctrl-C
- [ ] `digests.json` covers `vacuity.json` and the `vacuity/` logs
- [ ] attest refuses `gates_vacuous` with a test
- [ ] `wringer.vacuity.v1` under `schema/`, freeze-guard extended
- [ ] docs carry the captured vacuous-then-fixed loop transcript
