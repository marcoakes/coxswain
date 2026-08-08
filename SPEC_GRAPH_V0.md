# SPEC — the graph of loops (P7)

*Drafted 2026-08-07 by the planning window, from an external base plan that
was adversarially reviewed against the whole spec corpus — its four largest
defects are now rulings 1, 2, 3 and 5 rather than inherited mistakes.
**APPROVED 2026-08-07: Marc delegated the two open rulings (§5.3, §5.5)
to the planning window and both are decided below. Binding; no approval
pauses remain in this slice.** [SPEC_SUPERVISION_V0.md](SPEC_SUPERVISION_V0.md)
binds every primitive here; [SPEC_RUN_V0.md](SPEC_RUN_V0.md),
[SPEC_GET_V0.md](SPEC_GET_V0.md), [SPEC_VACUITY_V0.md](SPEC_VACUITY_V0.md)
and [SPEC_JUDGE_V0.md](SPEC_JUDGE_V0.md) are unchanged except where §5.3
amends one sentence by name.*

## Positioning

> **Wringer composes AI software work as graphs of evidence-producing loops.
> Each loop can use any coding agent. Each transition is explicit. Each stop
> is explainable. Each delivery requires evidence. Each graph resumes from
> disk.**

The northstar has promised "graphs of loops" since day one. This is the
first slice of it, and it is deliberately small: **a local, resumable,
evidence-driven workflow file that composes the primitives Wringer already
has.** It is not an agent framework, not a scheduler, and not a second
implementation of anything that exists — a graph node *names a Wringer
capability*, and the capability does what it has always done, with the same
refusals, the same evidence, the same laws.

The one-sentence test for every design question below: **would this widen
what Wringer can execute, contact, or write?** If yes, it is wrong — the
graph engine adds sequencing and stopping, never power.

## 1. What it does

```
wring graph validate graph.yaml     exit 0/2 — schema, dataflow, DAG checks
wring graph run graph.yaml          execute until done, failed, or parked
wring graph run graph.yaml --send   ...allowing the deliver node to send
wring graph resume GRAPH_DIR        continue a parked or killed graph
wring graph status GRAPH_DIR        one screen: where it is, why
wring graph explain GRAPH_DIR       why it stopped, and the next action
wring graph render graph.yaml       Mermaid to stdout, or --output FILE
```

Five node kinds and two built-in sinks:

| kind | wraps | stops the graph when |
|---|---|---|
| `intent` | staging an input file into evidence | the file is missing |
| `human` | the `approved: false` interlock (SPEC_INTENT §3) | always, until a person edits the decision file |
| `loop` | `loop.run` — the whole repair loop | never; its outcome routes |
| `router` | three comparison forms over state | a route targets `fail` |
| `deliver` | `deliver.plan`/`send` and **all its refusals** | the delivery is refused |

Routes may target a node id or the sinks **`done`** and **`fail`**. The
first release's canonical flow, shipped as `examples/graphs/issue-to-mr.yaml`:

```
intent → human approval → loop → router ─ converged → deliver → done
                                        └ otherwise → fail
```

## 2. Exit codes — and one amendment, named

`0` the graph reached `done` · `1` it reached `fail`, a node failed, or a
budget ran out (supervision: exhaustion is an outcome, not an error) · `2`
config or environment, including an invalid graph file · `3` a refused
precondition · `4` interrupted · **`5` parked — a human must act before the
graph can continue.**

**§5.3 (DECIDED 2026-08-07, under Marc's delegation):** `5` currently
belongs to `wring judge` alone, by
SPEC_JUDGE §2's own sentence. A parked graph is the same claim — *nothing
was decided; a person must act* — and `0` here would make
`wring graph run && anything` a footgun. SPEC_JUDGE §2's
"belongs to `wring judge` alone" sentence is **restated in the same commit
that registers the graph CLI** — the J2 precedent (wording ships with the
capability) and the network-enumeration lesson (no third copy left behind).
`test_judge.py`'s "verify and run can never return 5" guard is *extended* to
keep asserting exactly that — it pins those two commands, not the family.

## 3. The graph file

House config rules, verbatim: `version: 1` · unknown keys are hard errors ·
strict validation everywhere · **no command strings, anywhere** (§5.1).

```yaml
version: 1
id: issue-to-mr                 # a slug; it names directories

inputs:
  task: examples/tasks/example-issue.md

state:                          # initial routing state — strings only in v0
  approved: "false"

budgets:
  wall_clock: 7200              # whole-graph, seconds — REQUIRED (invariant 3)

nodes:
  read-intent:
    kind: intent
    input: inputs.task          # a dotted reference, never "${...}" templating
    then: approve-plan

  approve-plan:
    kind: human
    prompt: "Review the brief, then set approved: true by hand."
    then: build

  build:
    kind: loop
    budgets: {max_iterations: 4, wall_clock: 2700}
    writes: {status: state.build-status}
    then: route

  route:
    kind: router
    routes:
      - when: "state.build-status == 'converged'"
        to: deliver
    default: fail

  deliver:
    kind: deliver
    then: done
```

**Connectivity is `then:` and `routes:` — there is no separate `edges:`
block.** One representation, so the validator, the renderer and the executor
cannot disagree about what connects to what. The start node is the one no
edge targets; zero or several is a validation error.

**Validation** (`wring graph validate`, exit 2 on any):
missing/wrong `version` · missing or non-slug `id` · empty `nodes` · unknown
node kind · unknown key anywhere · a `then`/`to` naming no node and no sink ·
zero or multiple start nodes · unreachable nodes · **any cycle** (v0 is a
DAG; the loop node IS the cycle, bounded) · a router with no `default` · a
missing whole-graph `wall_clock` · **dataflow: every state path a router
reads must be in the initial `state:` or some upstream node's `writes:`** —
the authoring error the base plan could not catch.

## 3a. `intent` — stage the input

Copies the named file into the node's directory **through the bundle's
redactor** — the same scrub-on-the-way-in that `wring issue` does — and
writes its path into declared state. No summarising, no LLM, nothing clever:
its job is that the graph's evidence includes what the work was asked to be.
A missing file fails the node.

*It does not replace `wring spec`.* A future `spec` node kind may wrap the
real front door; this one only stages bytes.

## 3b. `human` — the interlock, again, on purpose

First execution writes `prompt.md` and `decision.yaml` into the node's
directory and parks the graph (exit 5):

```yaml
approved: false      # written as a constant — SPEC_INTENT §3's rules apply
comments: ""
state_updates: {}    # applied to state on approval; strings only
```

SPEC_INTENT's three rules hold verbatim: **`approved: false` is written as a
constant; no flag, environment variable or model reply may flip it; resume
re-reads the file from disk every time.** Unapproved on resume = still
parked, exit 5, no event spam — one `node.parked` per park, not per look.

`state_updates` may write **routing state only** — it cannot forge evidence,
because nothing reads state as evidence (§5.2).

## 3c. `loop` — wrap, never reimplement

Calls **`loop.run` in-process**, exactly as `cmd_run` does — same callbacks,
so a graph run *looks like* the `wring run` users already know. Not a
subprocess: `verify.py`'s founding rule is that shelling out to yourself
means parsing your own output, and the loop's supervision machinery (pgid
files, reaping, the breaker, `wants_prove`) comes along intact only in
process. The repo's own `.wringer.yaml` supplies the worker and gates — a
graph cannot substitute either (§5.1).

**Budgets nest and are hard — invariant 8, verbatim.** The node's
`max_iterations`/`wall_clock` are clamped to the graph's remaining budget
*before* the loop starts, and passed as `loop.run`'s own parameters, so
enforcement is the loop's existing enforcement rather than a second timer.
Every loop outcome — converged, stopped, oscillating, budget_exhausted — is
a *routing fact*, never a graph failure: the node completes and writes
`status` to its declared state path. `run.prove: true` binds here as
everywhere; a graph cannot loosen it.

## 3d. `router` — three forms, parsed, never evaluated

```
state.X == 'value'   ·   state.X != 'value'   ·   state.X in ['a', 'b']
```

Parsed by grammar, strings only, first match wins, missing state path
matches nothing, `default` is required. **There is no expression engine and
no eval** — anything outside the three forms is a validation error naming
them. Routers read state and may not write it.

## 3e. `deliver` — the refusals are the safety, `--send` is the human's

Calls the existing delivery machinery with the run bundle the loop node
recorded. **Dry-run by default, exactly as `wring deliver` is:** the patch,
message, branch and MR body land on disk and nothing touches git.

**§5.5 (DECIDED 2026-08-07, under Marc's delegation):** the graph never
conjures a `--send`. The amended law
6 says git history moves only on a flag a human typed — so the flag is typed
*on the graph invocation*: `wring graph run … --send` (or `resume … --send`)
authorises the deliver node this run reaches, once. A decision file cannot
carry it (a file is not a typed flag), and a graph file cannot declare it.
Without `--send`, the deliver node completes as a dry run and the summary
says exactly what to type next.

## 4. The run bundle — `.wringer/graphs/<graph_id>/`

`wringer.graph.v1`, and every house rule the other bundles obey:

- **`graph.jsonl` is an append-only, `prev_hash`-chained ledger** — events
  `graph.started/resumed/finished`, `node.started/finished/failed/parked`,
  `route.selected`, `state.updated`, `budget.exhausted`, each with the
  millisecond local-offset `ts`. Chained from day one so `wring audit`'s
  machinery can cover graph runs without a retrofit.
- **The bundle owns a `Redactor` built from `declared_secret_names`** and
  every write goes through it. Non-negotiable: two of this month's leaks
  were write paths that skipped it, and the whole-artifact secret sweep will
  be extended to run a graph.
- **`state.json` is a convenience snapshot; the ledger is the truth.**
  Resume reconstructs from `graph.jsonl` and never trusts the snapshot — the
  loop-resume ruling, unchanged. Completed nodes are never re-run.
- Loop and delivery bundles are **referenced by path, never nested** —
  `nodes/<id>/loop.ref.json` points at `.wringer/runs/…`; one run, one
  bundle, one place.
- `manifest.json` (schema-versioned), `graph.resolved.json` (the validated
  graph as executed, so `render` and `explain` describe what ran, not what
  the file says today), `summary.md`, `digests.json` **last, covering
  everything**. Run ids come from `evidence.new_run_id` — UTC-stamped, the
  house format.
- Schemas published under `schema/` with the drift test extended, in the
  same commit as the code — the version string is what a new field costs.

## 5. Rulings

1. **Graphs name capabilities, never commands.** No `command:` key exists in
   the format. The base plan let a graph specify `command: "wring run
   --json"` — which is arbitrary shell execution wearing a node costume, and
   it forbade arbitrary Python in edges while permitting arbitrary shell in
   nodes. The only file that may put a command into Wringer's mouth remains
   `.wringer.yaml`, whose trust story ("this file is code") is already
   documented, reviewed, and guarded. A graph adds **no** execution surface:
   validating and running a stranger's graph file must be exactly as safe as
   running the same Wringer commands by hand.
2. **State is routing data; evidence lives in bundles; only bundles gate.**
   The base plan gated delivery on `state.build_status == "converged"` — a
   string a human node's `state_updates` could forge. Here the deliver node
   hands `deliver.plan` the *bundle path*, and the protections are the
   shipped refusals: gates-passed, tree-unchanged-since-verify, vacuity.
   A graph that lied in state delivers nothing, because delivery re-checks
   the evidence — Wringer's thesis applied to Wringer's own new feature.
3. **Exit 5 = parked — DECIDED.** `0` would make `wring graph run &&
   deploy` ship on a graph nobody approved; `1` would page someone for a
   graph that is merely waiting for them. "Nothing was decided; a person
   must act" already has a number in this family, and reusing it keeps the
   exit table one table. Amends one SPEC_JUDGE §2 sentence, restated in the
   registering commit; `verify` and `run` still provably never return 5.
4. **Wrap in-process; never shell out to yourself; never reimplement.** The
   graph engine contains no gate runner, no worker seam, no delivery logic
   and no second repair loop — `loop.run` and `deliver.plan/send` are called
   as `cli.py` calls them today.
5. **`--send` passes through from the human's own invocation — DECIDED.**
   The amended law 6 survives verbatim: a human types the flag, and the
   graph is the human's invocation. Scope is deliberately narrow — it
   authorises only the deliver node reached in THAT invocation, once;
   resume requires retyping it; neither a graph file nor a decision file
   can carry it, because a file is not a typed flag. Without this the
   headline flow dead-ends at a dry run and the product claim loses its
   point; with it, delivery still passes through every shipped refusal.
6. **v0 is a DAG.** Retry-the-loop-differently cycles are a later version
   with explicit bounds; today the loop node is the only cycle and it is
   already bounded four ways.
7. **Parallelism belongs to the fleet.** No `fanout`/`join` kinds — when
   parallel branches arrive they arrive as a `fleet` node wrapping the real
   fleet, its invariants included, rather than as a second unsupervised pool.

## 6. Non-goals (binding)

Any new network path (the enumeration in SECURITY.md is unchanged by this
entire spec) · any new command execution surface · LLM calls · fanout/join ·
sub-graphs · cron/watch modes · a TUI or web UI · OpenTelemetry · graph
templates or a registry · cross-repo graphs · numeric/boolean router
comparisons (strings only in v0) · editing `.wringer.yaml` from a graph ·
Windows.

## 7. Definition of DONE

- [ ] the example graph validates, runs to `done` on a scratch repo with a
      real worker, parks at the human node, and resumes after a hand edit —
      all through real processes, nothing mocked
- [ ] `validate` rejects each §3 failure with a message naming the fix
- [ ] the dataflow check catches a router reading state nothing writes
- [ ] a graph file containing any `command:`-like key is a validation error
      with ruling 1's one-line why
- [ ] a killed (`kill -9`) graph resumes from the ledger, never re-running a
      completed node; a doctored `state.json` changes nothing (ledger wins)
- [ ] the loop node's budget is provably `min(node, graph remainder)` and
      `run.prove: true` is provably not loosenable from a graph
- [ ] a `state_updates` forgery of `build-status` still cannot deliver — the
      bundle check refuses; test plants the lie and watches the refusal
- [ ] deliver without `--send` writes the dry run and git is untouched;
      `--send` on the invocation delivers through the existing five refusals
- [ ] parked = exit 5, and the SPEC_JUDGE amendment + extended guard land in
      the same commit that registers the graph CLI
- [ ] every artifact passes the extended whole-artifact secret sweep with a
      graph in the driven-command list
- [ ] `render` output is derived from the resolved graph and a test asserts
      node-for-node agreement — never a second hand-maintained picture
- [ ] schemas under `schema/`, drift test extended, AGENTS.md hierarchy row,
      QUICKSTART heading and table rows — all in the shipping commits (the
      parser-derived guards will fail until they are; that is by design)
- [ ] docs carry a **captured** transcript: run → park → hand edit → resume →
      done. The park/resume shape is fully non-interactive, so the recorder
      films it honestly with no new capability
