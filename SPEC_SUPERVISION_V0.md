# SPEC — supervision: fleets that fail small, heal themselves, and leave receipts

*Adopted for planning 2026-07-31 at the maintainer's direction. This is the
binding **design contract for every execution primitive Wringer has or grows**
— the loop it has now, the resume and fleet slices below, and the graph
engine later. Individual slices still get their own build specs; this
document is what they must all obey.
[SPEC_VERIFY_V0.md](SPEC_VERIFY_V0.md), [SPEC_RUN_V0.md](SPEC_RUN_V0.md) and
[SPEC_JUDGE_V0.md](SPEC_JUDGE_V0.md) are unchanged.*

## Why this exists — the incident of 2026-07-30

This spec was paid for, so its motivation gets receipts rather than
platitudes. During Wringer's own development, an orchestrated design fleet
was launched at 23:59 and killed by hand at 08:15 the next morning:

- **24 agents started; 4 produced results; 20 produced nothing.**
- The 4 useful results were all delivered **inside the first 49 minutes**.
  The remaining ~7.5 hours bought zero marginal value.
- The failing 20 were all the *same* failure: each consumer was handed a
  ~50 KB payload inline and asked to also read a whole repo; each drowned,
  failed validation, and was **retried with identical input, forever** — no
  retry ceiling, no failure-signature check, no deadline, no agent cap.
- The failure was **silent**: a wedged fleet is indistinguishable from a busy
  one unless progress is measured. Nothing measured it.
- The only reason anything was salvaged is that every result had been written
  to an **append-only ledger** as it landed. Recovery was reading a file.

Every rule below is one of those sentences, generalized. The last one is
Wringer's own thesis handed back to it: *the evidence bundle is the product* —
and it is also the crash-safety mechanism.

## The invariants (binding on every current and future primitive)

1. **Every retry has a ceiling, and every ceiling has an escalation.**
   Nothing in Wringer ever retries unboundedly. When attempts run out, the
   work is *parked with its evidence*, never dropped and never looped.
2. **Never retry identical input on an identical failure.** A failure with
   the same signature as the last attempt is deterministic, not transient;
   retrying it is theatre. Signatures are hashed and compared before any
   retry is granted.
3. **Every wait has a deadline.** Workers have `worker_timeout` (shipped);
   loops get `wall_clock`; fleets get a fleet deadline and a per-child
   progress window. There is no unbounded wait anywhere in the program.
4. **Progress is measured in evidence, not liveness.** A child is alive iff
   its ledger grew within its progress window. "The process exists" proves
   nothing — the incident's fleet had live processes for eight hours.
5. **Pass references, not blobs.** Work handed to a child is a *path* (a
   brief file, a bundle directory), never an inline payload. Anything inline
   is size-capped with a declared truncation marker. This rule is the direct
   fix for the incident's root cause, and the loop already obeys it
   (`{brief}` is a path).
6. **Partial success is a first-class outcome.** A fleet reports
   `{succeeded, failed, parked}` honestly. It never fails 200 tasks because
   3 died, and never declares success while quietly missing 3.
7. **Everything is resumable from the ledger.** A supervisor holds no state
   that is not on disk. Kill -9 any Wringer process at any moment and
   `wring resume` continues from the last recorded fact — because the ledger
   is append-only and every event is timestamped.
8. **Budgets nest and are hard.** A child's budget is clamped to its parent's
   remainder. Exhaustion is an outcome (`budget_exhausted`), not an error,
   and it is always recorded with what was completed.

"Self-correcting" is the repair loop itself (evidence fed back to the
worker). "Self-healing" is invariants 1–4 + 7: bounded retries, breakers,
deadlines, and resume. "Fallbacks" are the declared ladders in the config
shapes below — never improvised at runtime.

## Slice S1 — the loop learns to stop burning money

*Extends `wring run`. Small; the primitives everything else uses.*

**Failure signatures.** After each failed verify, compute
`sha256(gate_id, exit_code, normalized tail of the failing gate's logs)` —
normalization strips timestamps, run-id paths, and collapses whitespace, so
the *shape* of the failure is hashed rather than its noise. The signature is
recorded on the `verify.finished` event.

**The breaker:** a signature **seen before in this loop** trips it — stop,
reason `oscillating`. That one rule catches both thrash (A→A: the worker's
change didn't touch the failure) and oscillation (A→B→A: the worker is going
in circles). Normalization is heuristic and false-negative-safe: a missed
match merely spends budget the ceiling still catches.

**Wall clock.** `run.wall_clock` (optional, seconds): checked between steps;
exhaustion stops the loop, reason `budget_exhausted`, after finishing the
step in flight — Wringer does not kill a verify mid-gate to save seconds.

`reason` grows two values: `oscillating`, `budget_exhausted`. This amends
`wringer.loop.v1` **in place**, which is legitimate solely because 0.2 is
unreleased and unmerged; after any release this would cost a version bump.

```yaml
run:
  worker: claude -p "$(cat {brief})"
  max_iterations: 3
  worker_timeout: 900
  wall_clock: 3600        # NEW, optional — no default; the loop is already
                          # structurally bounded by iterations × timeouts
```

## Slice S2 — `wring resume`

*A loop whose ledger lacks `loop.finished` did not finish — SIGKILL, power
loss, OOM. Its completed iterations are facts. Resume continues them.*

```bash
wring resume              # resume the latest unfinished loop
wring resume LOOP_DIR     # resume a named one
```

- Reconstructs state purely from `loop.jsonl` (the manifest is written only
  at completion and stays that way — the ledger is the source of truth, the
  manifest is a convenience index).
- Appends a `loop.resumed` event (new event type, same in-place-amendment
  license as S1), then continues iteration numbering as if never interrupted.
- A ledger whose last event is `loop.finished` is not resumable: exit 2,
  "nothing to resume". An interrupted loop (Ctrl-C wrote `loop.finished
  status=interrupted`) is also not resumable — the human chose to stop it;
  they can start a new loop.
- Budgets resume with the *remainder*: iterations already spent stay spent.
- Test in the house style: really `kill -9` a running loop mid-worker, then
  really resume it to convergence.

## Slice S3 — `wring fleet`: hundreds of tasks, bounded blast radius

*The scale slice. Queue hundreds of repair loops; run a bounded number at
once; heal what can be healed; park what cannot; report honestly; survive
its own death. This section is the contract — S3 still gets a detailed build
spec before implementation.*

```bash
wring fleet tasks.jsonl            # run a fleet
wring fleet tasks.jsonl --json
wring resume FLEET_DIR             # unfinished + parked tasks re-enter the queue
```

**Tasks are a JSONL file** — one object per line, `{"id": "slug", "brief":
"path/to/brief.md", "dir": "path/to/worktree"}` — references, per invariant
5. Ids are slugs (they name directories). "Hundreds" is the **queue depth**;
concurrency is the bounded worker pool.

```yaml
fleet:
  concurrency: 4            # simultaneous children; the queue may hold hundreds
  deadline: 21600           # whole-fleet wall clock, required — no unbounded fleets
  progress_window: 1200     # a child whose ledger is silent this long is reaped
  retries: 1                # per task, on non-identical failure signatures only
  on_exhausted: park        # park | fail — what a task becomes when retries run out
  join: all                 # all | quorum:0.8 | first_pass
  child:                    # budget template, clamped to the fleet's remainder
    max_iterations: 3
    worker_timeout: 900
    wall_clock: 3600
  worker_fallbacks: []      # optional ladder: retry N uses command N, declared here
```

**The self-healing ladder, per task:** attempt → on failure, classify by
signature: *new* signature → transient, eligible for retry (with the next
`worker_fallbacks` entry if one is declared); *seen* signature →
deterministic, **parked immediately with its evidence** (invariant 2 — the
incident's 20 wasted agents were all deterministic failures retried as if
transient). Reaped-for-silence counts as a failure with signature
`no_progress`.

**Isolation ruling (needs the maintainer's word):** parallel children cannot
share a working tree. Each task therefore declares its own `dir` — and an
optional worktree mode lets the fleet `git worktree add/remove` per task.
That is a git *metadata* write; the standing law "the loop never commits,
never pushes" holds unchanged. Veto the worktree half and `dir` becomes
simply mandatory.

**The fleet ledger** — `.wringer/fleets/<fleet_id>/fleet.jsonl` +
`manifest.json` under **`wringer.fleet.v1`**, children referenced by path,
schemas published and drift-tested like everything else. Events:
`fleet.started`, `task.started`, `task.finished` (status + child loop dir),
`task.retried` (with signature and fallback index), `task.parked` (with
why), `task.reaped`, `fleet.finished` (`{succeeded, failed, parked}` counts
+ join verdict). Exit codes: `0` join satisfied · `1` join failed · the
family's `2/3/4` unchanged — and partial results are on disk either way.

**Cost honesty.** Wringer's enforced budgets are time, iterations and
attempts. Dollar budgets exist only where Wringer itself makes the call (the
judge); a worker's spend is its own affair unless it reports one. `cost.jsonl`
records what is known and declares what is not — no invented numbers.

## Non-goals (binding for S1–S3)

The graph IR and typed edges (the fleet is the primitive the graph will
compile to) · judge-in-the-loop · distributed/multi-machine fleets ·
Temporal · OpenTelemetry · sandboxing children beyond worktree isolation ·
any commit or push · dollar-denominated budget *enforcement*.

## Definition of DONE for the supervision arc

- [ ] a worker that oscillates A→B→A is stopped by the breaker, with both
      signatures in the ledger
- [ ] a loop with `wall_clock: 2` and a slow worker stops with
      `budget_exhausted` after the step in flight
- [ ] `kill -9` mid-worker, then `wring resume`, converges — and the ledger
      shows one `loop.resumed` between the two lives
- [ ] a 50-task fleet with `concurrency: 4` completes with correct
      `{succeeded, failed, parked}` counts; re-running the *same* fleet after
      `kill -9` via `wring resume` finishes only the unfinished tasks
- [ ] a task failing twice with the same signature is parked after one
      attempt, never retried
- [ ] a child silent past `progress_window` is reaped and recorded
- [ ] the incident's shape — deterministic failures retried unboundedly —
      is structurally impossible, and a test demonstrates why
