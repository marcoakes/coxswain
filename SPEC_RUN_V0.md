# SPEC — `wring run` v0.2, slice 1: the repair loop

*Adopted 2026-07-30. This is the **binding implementation contract** for the
first executable slice of v0.2. Where it and [ROADMAP.md](ROADMAP.md)
disagree about this slice, this document wins;
[SPEC_VERIFY_V0.md](SPEC_VERIFY_V0.md) remains binding and unchanged for
everything `wring verify` does.*

## Positioning

> **While `wring verify` fails, hand the evidence to your own coding agent
> and let it try again — with receipts for every lap.**

`wring verify` proved a change. `wring run` closes the loop around it. The
worker is **your** agent, spawned as a subprocess; Wringer supplies the
gates, the brief and the evidence. It still makes **no LLM call and no
network call of its own** — the worker's costs and choices are the worker's.

The judge, issue ingestion and MR delivery are later slices. This one is the
loop.

## CLI surface

```bash
wring run                     # loop until converged or stopped
wring run --max-iterations 5  # override the config
wring run --json              # one object on stdout, no human report
```

**Exit codes are contract:**

| code | meaning |
|---|---|
| 0 | converged — every required gate passed |
| 1 | stopped without converging (iterations exhausted, or no progress) |
| 2 | config or environment error (including a missing `run:` section) |
| 3 | unsafe dirty state / refused precondition |
| 4 | interrupted |

These mirror `wring verify`'s table deliberately: `0` is still "the evidence
says yes", `1` is still "it does not".

## Config — the `run:` section

```yaml
run:
  worker: claude -p "$(cat {brief})"
  max_iterations: 3      # optional, default 3, integer >= 1
  worker_timeout: 900    # optional, default 900 seconds, integer >= 1
```

**Rules (binding):**

1. `worker` is **required and never invented**. `wring run` in a repo whose
   config has no `run:` section is exit 2 with a message naming what to add —
   the same law as gates: a wrong command is worse than an absent one.
2. Validation is strict, like the rest of the config: unknown keys under
   `run:` are errors.
3. **Placeholders**, substituted before the shell sees the command:
   `{brief}` — path to this iteration's brief · `{evidence_dir}` — the
   failing verify bundle · `{iteration}` — 1-based iteration number. An
   unknown `{name}` is a config error that names the allowed set. A `{` not
   forming a known placeholder, and anything of the form `${VAR}`, passes
   through untouched to the shell.
4. **The worker command is code**, exactly as a gate is: it runs through a
   shell, in the repo root, with the user's privileges and inherited `PATH`.
   Everything [SECURITY.md](SECURITY.md) says about `.wringer.yaml` applies
   to it with no exceptions.
5. A config carrying `run:` requires Wringer ≥ 0.2 — v0.1's strict loader
   rejects unknown top-level keys. Verify-only configs remain valid forever.

## The loop

Preconditions are `wring verify`'s: inside a git repo (else exit 2), no merge
or rebase in progress (else exit 3), config loads (else exit 2).

Then for iteration *N* = 1 … `max_iterations`:

1. **Verify.** A full `wring verify`, writing an ordinary bundle to
   `.wringer/runs/` — indistinguishable from one a human ran.
2. **Converged?** Every required gate passed → `loop.finished`, exit 0.
3. **Progress?** Fingerprint the tree. If it equals the fingerprint taken
   before the previous worker ran, the worker changed nothing: stop with
   reason `no_progress`, exit 1. No second verify is run — an identical tree
   gives an identical result, and re-running it would be theatre.
4. **Budget?** Iterations exhausted → stop, reason `max_iterations`, exit 1.
5. **Brief.** Write `iterations/NNN/brief.md`: the failing run's `--json`
   object, the diagnosis (failing gate, command, exit code, log tails,
   changed files), and the instruction to fix it, re-check with the printed
   rerun command, and leave `.wringer/` alone.
6. **Worker.** Substitute placeholders and run the command with its own
   process group and `worker_timeout`, capturing both streams to
   `iterations/NNN/worker.{stdout,stderr}.log` — scrubbed before write and
   capped, exactly as gate output is.

**A worker's exit code is recorded and never ends the loop.** The evidence
decides, not the worker's opinion of itself: a worker that crashed after
fixing the bug converges on the next lap, and one that exited cleanly
without changing anything stops on `no_progress`. A worker that overruns
`worker_timeout` is killed, recorded as timed out, and the loop continues.

**Ctrl-C** kills the worker's process group, finishes the loop bundle
honestly — a `worker.started` with no `worker.finished`, mirroring verify's
treatment of an interrupted gate — and exits 4.

### The fingerprint

sha256 over: HEAD sha · `git diff` output · `git status --porcelain -z`
output · and for each untracked path in sorted order, its path and the hash
of its contents (files over 10 MB contribute path and size only).

This is deliberately the degenerate form of the anti-thrash machinery in the
roadmap's Days 31–60. Failure-signature hashing, oscillation detection and
plateau scoring are **not** this slice.

## Loop evidence — `.wringer/loops/<loop_id>/`

A new artifact with its own schema version, **`wringer.loop.v1`**. Verify
bundles are *referenced by path*, never copied or nested: one run, one
bundle, one place.

```
.wringer/loops/20260731-091500-4b2a/
  manifest.json
  loop.jsonl
  summary.md
  iterations/
    001/
      brief.md
      worker.stdout.log
      worker.stderr.log
```

`loop.jsonl` is append-only, one JSON object per line, every event carrying
`type` and a millisecond `ts`:

```json
{"type":"loop.started","ts":"...","loop_id":"...","wringer_version":"0.2.0","repo":"wringer","sha":"abc123","max_iterations":3}
{"type":"iteration.started","ts":"...","iteration":1}
{"type":"verify.finished","ts":"...","iteration":1,"status":"failed","failed_gate":"test","evidence_dir":".wringer/runs/..."}
{"type":"worker.started","ts":"...","iteration":1,"command":"claude -p ..."}
{"type":"worker.finished","ts":"...","iteration":1,"exit_code":0,"duration_ms":134201}
{"type":"iteration.started","ts":"...","iteration":2}
{"type":"verify.finished","ts":"...","iteration":2,"status":"passed","evidence_dir":".wringer/runs/..."}
{"type":"loop.finished","ts":"...","status":"converged","reason":"converged","iterations":2}
```

Optional keys appear only in the case they describe — `failed_gate` on a
failing verify, `timed_out` on a worker that overran — the same convention
the evidence bundle uses.

`manifest.json`:

```json
{
  "schema_version": "wringer.loop.v1",
  "loop_id": "20260731-091500-4b2a",
  "started_at": "2026-07-31T09:15:00+01:00",
  "repo": {"root": ".", "head_sha": "abc123", "branch": "main", "dirty": true},
  "config": {"max_iterations": 3, "worker": "claude -p ..."},
  "result": {"status": "converged", "reason": "converged", "iterations": 2,
             "final_run": ".wringer/runs/..."}
}
```

## The console

```
$ wring run
iteration 1/3
✓ lint passed        0.1s
✗ test failed        9.2s
→ worker             2m 14s (exit 0)
iteration 2/3
✓ lint passed        0.1s
✓ test passed       11.0s

Converged in 2 iterations.
Loop evidence: .wringer/loops/20260731-091500-4b2a/
```

Gate lines are `wring verify`'s, unchanged. `wring run --json` emits one
object, keys always present:

```json
{"status":"converged","reason":"converged","iterations":2,"loop_dir":".wringer/loops/...","final":{"status":"passed","failed_gate":null,"rerun":null,"evidence_dir":".wringer/runs/..."}}
```

`status` is `converged | stopped | interrupted`; `reason` is
`converged | max_iterations | no_progress | interrupted`; `final` is the last
verify's `--json` object, or `null` if none completed.

## Non-goals for this slice (binding)

LLM judge and rubrics · issue ingestion · branch, commit, push, PR or MR
creation of any kind · durable resume · cost ledger · OpenTelemetry ·
anti-thrash beyond the fingerprint above · parallelism · ACP · Temporal ·
`wring explain` for loops (the loop's `summary.md` serves) · Windows.

`wring run` **never writes to git.** It runs gates and a worker; committing
what came out is the human's decision, and delivery is a later slice.

## Definition of DONE for this slice

- [ ] `wring run` converges on a repo with a scripted worker that fixes a
      planted bug, exit 0
- [ ] stops with `max_iterations` when the worker never fixes it, exit 1
- [ ] stops with `no_progress` when the worker changes nothing, having run
      exactly one verify
- [ ] converges even when the worker exits non-zero, because the evidence
      decides
- [ ] a worker that overruns its timeout is killed and recorded, loop continues
- [ ] Ctrl-C exits 4 and leaves an honest loop bundle
- [ ] `--json` keys stable across every outcome
- [ ] secrets never reach `worker.stdout.log`
- [ ] loop bundle validates against `schema/loop-*.schema.json`, enforced by
      the suite the same dependency-free way the evidence schemas are
- [ ] docs carry a real captured transcript of a loop converging
