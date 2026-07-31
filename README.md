<div align="center">

# 🗜️ Wringer

**The vendor-neutral AI-DLC harness — a control plane for AI-driven development,
for product managers, designers and engineers.**

*Put every change through the wringer.*
*The harness runs the gates, keeps the receipts, and never writes the code itself.*

[![tests](https://github.com/marcoakes/wringer/actions/workflows/tests.yml/badge.svg)](https://github.com/marcoakes/wringer/actions/workflows/tests.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![v0.1.0: Sep 30, 2026](https://img.shields.io/badge/v0.1.0-Sep%2030%2C%202026-orange.svg)](ROADMAP.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

[Quickstart](QUICKSTART.md) · [v0 spec](SPEC_VERIFY_V0.md) · [90-day roadmap](ROADMAP.md) · [Security](SECURITY.md) · [vs LangGraph](docs/wringer-vs-langgraph.md) · [Build plan](wringer-ai-dlc-harness-plan.md) · [RFCs](https://github.com/marcoakes/wringer/issues?q=is%3Aissue+RFC)

</div>

---

> **Everyone else in this space is selling capability and asking for trust.
> Wringer is built on the opposite premise: trust nothing — including itself.**
> Not the worker's exit code, not the agent's summary, not even the tests the
> agent wrote — and soon, provably, not even its own ledgers. That stance came
> out of [a real eight-hour burn](SPEC_SUPERVISION_V0.md), it is welded into
> [eight invariants](SPEC_SUPERVISION_V0.md) a fleet already obeys, and it
> gets more valuable with every step frontier models take — because autonomy
> without receipts is exactly what everyone is about to be terrified of.

Wringer (CLI: `wring`) compiles **intent** — tickets, PRDs, Slack messages — into **verified outcomes**: reviewed merge requests with evidence. It treats *loops* and *graphs of loops* as first-class, portable primitives, and runs the **same workflow definition** on your laptop today and on durable runtimes (Temporal first) tomorrow.

Every cloud's harness locks you to its runtime, its identity system, its gateway. **Nobody owns the neutral layer.** That's the bet — Kubernetes-vs-managed-containers, replayed one layer up.

## What ships first

**Proof beats orchestration.** v0.1.0 is a standalone evidence compiler — one command:

> *One command that proves whether this change is mergeable, and leaves behind evidence a human or agent can inspect.*

A real run, pasted unedited from a scratch Python repo (`ruff` and `pytest` as the two declared gates, with a bug planted in the code):

```
$ wring verify
✓ lint passed        0.0s
✗ test failed        0.1s

--- gates/002_test/stdout.log ---
    def test_add():
>       assert add(2, 2) == 4
E       assert 5 == 4
E        +  where 5 = add(2, 2)

FAILED test_calc.py::test_add - assert 5 == 4
1 failed in 0.01s

Evidence written to:
.wringer/runs/20260730-210750-b3ec/

Next:
  open .wringer/runs/20260730-210750-b3ec/summary.md
  rerun wring verify --gate test
```

Exit code `1`, and a bundle on disk that a human or an agent can read: `summary.md` for the person reviewing, timestamped `evidence.jsonl` for the machine, `diff.patch` and `status.txt` for what was being verified, per-gate logs for what happened. `wring explain` replays the diagnosis without an LLM; `wring verify --json` emits one object for an agent to act on. The full transcript — and what is still unbuilt — is in the [quickstart](QUICKSTART.md).

It runs your project's declared gates (build · test · lint) in order and writes a portable evidence bundle — `manifest.json`, `evidence.jsonl`, `summary.md`, `diff.patch`, `status.txt`, and per-gate stdout/stderr/`result.json` — around **any** session: Claude Code, Codex CLI, Gemini CLI, or a human. No LLM and no network — by default, and in every command that proves anything. `wring judge --send` is the single exception: it exists only when your repo declares an endpoint, it writes the exact bytes to disk before it opens a socket, and it never runs unless you type `--send`. After an AI coding session, `wring verify` leaves a cleaner, more reviewable truth trail than the agent's own summary. The binding implementation contract is **[SPEC_VERIFY_V0.md](SPEC_VERIFY_V0.md)** — including the release bar: *Wringer verifies Wringer, in CI, with the demo bundle committed, before v0.1.0 tags.*

> ⚠️ **`.wringer.yaml` is code.** `wring verify` runs the commands a repository declares, through a shell, with your privileges — the same trust you extend to its `Makefile`. Read a stranger's `.wringer.yaml` before running `wring verify` in their repo. Gates are not sandboxed in v0.1; see [SECURITY.md](SECURITY.md), which also explains why an evidence bundle should be read before you share it.

Then the loop closes: `wring run` is just a loop that keeps calling `wring verify` until the evidence says stop — worker (your existing coding agent; Wringer never ships its own) → gates → isolated rubric judge → iterate or exit → MR with the receipts attached. **`v0.1.0` no later than September 30, 2026** — see the [90-day roadmap](ROADMAP.md) and the [quickstart](QUICKSTART.md).

## Wringer verifies Wringer

The claim is checkable, not rhetorical. This repo declares its own gates in
[`.wringer.yaml`](.wringer.yaml), CI runs `wring verify` on every push and
uploads the bundle, and a real one is committed at
[`.wringer.example/`](.wringer.example/) — manifest, timestamped event log,
summary, diff, and both gates' logs, exactly as produced:

```
$ wring verify
✓ lint passed        0.1s
✓ test passed        17.6s

Evidence written to:
.wringer/runs/20260730-231645-a57c/
```

That is the run committed at
[`.wringer.example/runs/20260730-231645-a57c/`](.wringer.example/runs/) — the
same id, so the transcript and the bundle are the same event rather than two
similar ones. That bundle is the answer to "how do I know?" — read it rather
than trust the badge.

## The loop is real now — `wring run`

`wring verify` proves a change; `wring run` closes the loop around it. While
the gates fail it writes the failure into a brief, hands it to **your** coding
agent as a subprocess, and verifies again. Wringer still never calls an LLM
itself. Captured from a scratch repo with a planted bug and a scripted worker:

```
$ wring run

iteration 1/3
✗ test failed        0.2s
→ worker             0.0s  (exit 0)

iteration 2/3
✓ test passed        0.1s

Converged in 2 iterations.
Loop evidence: .wringer/loops/20260730-234410-7c70/
```

A worker's exit code never ends the loop — the evidence decides — and a worker
that changes nothing stops it without re-running the gates to prove the
obvious. `wring run` never touches git. Contract:
**[SPEC_RUN_V0.md](SPEC_RUN_V0.md)**; walkthrough in the
[quickstart](QUICKSTART.md#the-loop--wring-run).

## The format is targetable, not just readable

The bundle is the interface, so it is [published as JSON
Schema](schema/) — `manifest.json`, each `evidence.jsonl` event, and each
gate's `result.json`, in draft 2020-12. Write a tool against the schema
rather than against this implementation. A test fails the build if the code
ever writes a field the schema does not declare.

## It is not a Python tool

Wringer is *written* in Python; nothing about it is *for* Python. It runs the
commands your repo already declares. [`docs/beyond-python.md`](docs/beyond-python.md)
is the receipt — real captured output from a Make project whose test suite is
a shell script, and a Node project's detected gates, neither containing a line
of Python.

## Put an agent's edits through it

`wring verify --json` exists so an agent can act on the result rather than
read prose about it. [`examples/claude-code-hook/`](examples/claude-code-hook/)
wires that into a coding session: after every edit, the gates run; if one
fails, the agent is handed the structured verdict and `wring explain`'s
diagnosis and fixes it before carrying on. Passing gates say nothing.

That is the v0.1 shape of the v0.2 loop — worker, gate, evidence — with the
loop still driven by the agent rather than by `wring run`.

## Why

The substrate is converging. Every serious AI-DLC implementation lands on the same five-layer architecture — and the frontier labs are each selling their piece of it. The code layer is commoditizing. What stays defensible is **governance, deterministic verification, audit trails, and execution speed** on top of the substrate.

Wringer is:

- **Verified, not vibed.** Deterministic gates (build / test / lint / custom linters) always run before any LLM judge. A loop cannot claim "done" without passing its declared verifier.
- **A graph of loops.** A node isn't a function call — it's a *loop-bearing agent* with a contract: budget, verifier, exit conditions. The graph wires those loops into an organization with typed edges and explicit inter-loop feedback paths.
- **Physically worker/judge separated.** The judge sees the rubric, the diff, and the gate outputs — never the worker's chain of reasoning. Engine guarantee, with tests.
- **Auditable as a byproduct.** Every run emits intent → plan → steps → evidence → delivery as queryable JSONL plus OpenTelemetry GenAI traces, with a per-loop cost ledger.
- **Vendor-neutral by construction.** The Graph IR references *capabilities*, never vendor resources. Adapters map capabilities to runtimes; a conformance suite proves each mapping.

Already using LangGraph, CrewAI, or Microsoft Agent Framework? Read the [honest comparison](docs/wringer-vs-langgraph.md) — they're compile targets and peers here, not competitors.

## A loop is a contract

```yaml
loop:
  kind: repair            # repair | evaluator_optimizer | convergence | explore | evolve
  budgets:
    max_iterations: 6
    max_cost_usd: 4.00
    max_wall_clock: 45m
    max_tokens: 800k
  verify:                  # gates run in order, cheapest first
    - gate: build
    - gate: test
    - gate: lint.custom.architecture-boundaries
    - judge: rubric.acceptance-criteria   # only if gates pass
  exit:
    on_pass: continue
    on_budget_exhausted: escalate.human
    on_oscillation: escalate.human       # same-failure-signature repeated N times
    on_plateau: best_effort_deliver
  evidence: full           # every iteration captured to the run bundle
```

Anti-thrash machinery is core, not optional: failure-signature hashing, score-plateau detection, judge-disagreement tracking, per-loop cost ledgers. The schema is an open spec — [RFC discussion here](https://github.com/marcoakes/wringer/issues?q=is%3Aissue+RFC).

## A graph is an organization

```mermaid
flowchart LR
    I([Intent<br/>issue · PRD · Slack]) --> S[agent_step<br/>scope]
    S --> P[agent_step<br/>plan]
    P --> H{human<br/>approve?}
    H -- low-risk auto --> L
    H -- approved --> L
    subgraph L [loop: repair]
        direction LR
        W[worker<br/>writes code] --> G[gates<br/>build · test · lint]
        G -- fail --> W
        G -- pass --> J[judge<br/>isolated context]
        J -- revise --> W
    end
    J -- pass --> D([deliver<br/>MR + evidence bundle])
    L -. budget exhausted /<br/>oscillation .-> E{escalate<br/>to human}
```

The worker never sees the judge; the judge never sees the worker's chain of reasoning. Feedback edges are *declared, not implied*, so coupled-loop conflicts (speed loop vs quality loop) are inspectable instead of emergent.

## Architecture (the north star)

The full five-layer architecture — protocol wires (ACP/MCP/A2A), swappable runtime/gateway/identity/memory planes, sandbox layer, self-evolution loop — is specified in the **[build plan](wringer-ai-dlc-harness-plan.md)**. We are shipping it inside-out: the differentiated core first, the plumbing when the loop has earned it. Execution order is governed by **[ROADMAP.md](ROADMAP.md)**.

```
┌─────────────────────────────────────────────────────────────────┐
│ L1 INTENT        GitHub/GitLab issues · Linear · Jira · Slack   │
├─────────────────────────────────────────────────────────────────┤
│ L2 HARNESS       wringer-ir · wringer-engine · wringer-loops · wringer-verify   │
│                  wringer-context · wringer-policy                       │
├─────────────────────────────────────────────────────────────────┤
│ L3 WIRES         ACP → coding agents · MCP → tools ·            │
│                  A2A → other agents                             │
├─────────────────────────────────────────────────────────────────┤
│ L4 PLANES        runtime · gateway · identity · model · memory  │
│                  (adapters — all swappable, conformance-tested) │
├─────────────────────────────────────────────────────────────────┤
│ L5 SANDBOX       Docker/Podman · VM · gVisor · microVM          │
├─────────────────────────────────────────────────────────────────┤
│ CROSS-CUTTING    OTel GenAI traces · cost ledger · audit JSONL  │
└─────────────────────────────────────────────────────────────────┘
```

## Roadmap

| When | What | Proof |
|---|---|---|
| **Days 1–30** | **v0.1.0 — the evidence compiler** ([spec](SPEC_VERIFY_V0.md)): `wring init` · `wring verify` · `wring explain`, evidence bundles, Python/pipx. Then the loop closes: `wring run` = verify-in-a-loop with your existing agent as worker | **Wringer verifies Wringer in CI + committed demo bundle** |
| **Days 31–60** | Durable execution (SQLite event log, `wring resume`), anti-thrash (oscillation + plateau detection), cost ledger, OTel GenAI traces | crash-and-resume on camera |
| **Days 61–90** | Graph of loops (scope → plan → repair → deliver), one `human` interrupt node, **Wringer ships a Wringer PR** | the dogfooded PR, public |

**Q3 2026 OKR:** a GitHub issue becomes a passing MR for Python repos under $2.00 LLM spend. **Q4 2026:** TypeScript targets + the Temporal adapter. Everything else in the plan — gateway plane, policy, context autogen, skills, self-evolution — is deferred behind the working loop, [with reasons](ROADMAP.md#rulings-that-changed-from-the-v10-plan).

## Design principles (the short version)

1. The harness never writes code.
2. Separate the worker from the judge.
3. Deterministic gates are the contract.
4. Vendor-agnostic at every layer — no lock-in, ever.
5. Loops are contracts; graphs are organizations.
6. Audit trail as byproduct.
7. Cost per task is a first-class metric.
8. Build to delete.

The full eleven, with rationale, are in [the plan](wringer-ai-dlc-harness-plan.md#3-design-principles).

## Contributing

The highest-value contributions right now are **design review and prior art** on the open RFCs — the [loop-contract schema, the gate plugin interface, and the evidence-bundle format](https://github.com/marcoakes/wringer/issues?q=is%3Aissue+RFC). Code has started landing (`wring init` and `wring verify` work — see [AGENTS.md](AGENTS.md) for state and setup); green tests are the only law. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache-2.0](LICENSE). Vendor-neutral, conformance-tested, built to be donated.
