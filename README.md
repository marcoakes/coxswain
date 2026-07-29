<div align="center">

# ⛵ Coxswain

**The open, control-plane-agnostic harness for AI-driven development.**

*The coxswain steers the boat, calls the stroke rate, and never rows.*
*The harness steers the work, sets the loop cadence, and never writes the code itself.*

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Status: Design Phase](https://img.shields.io/badge/status-design%20phase-orange.svg)](coxswain-ai-dlc-harness-plan.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

</div>

---

Coxswain (CLI: `cox`) compiles **intent** — tickets, PRDs, Slack messages — into **verified outcomes**: reviewed merge requests with evidence. It treats *loops* and *graphs of loops* as first-class, portable primitives, and runs the **same workflow definition** on your laptop, on Temporal, on AWS Bedrock AgentCore, on Google's Agent Engine, on Microsoft Foundry, or on Anthropic Managed Agents.

Every cloud's harness locks you to its runtime, its identity system, its gateway. **Nobody owns the neutral layer.** That's the bet — Kubernetes-vs-managed-containers, replayed one layer up.

## Why

The substrate is converging. Every serious AI-DLC implementation lands on the same five-layer architecture — and the frontier labs are each selling their piece of it. The code layer is commoditizing. What stays defensible is **governance, deterministic verification, audit trails, and execution speed** on top of the substrate.

Coxswain is:

- **Vendor-neutral by construction.** The Graph IR references *capabilities*, never vendor resources. Adapters map capabilities to vendor primitives; a conformance suite proves each mapping.
- **A graph of loops.** A node isn't a function call — it's a *loop-bearing agent* with a contract: budget, verifier, exit conditions. The graph wires those loops into an organization with typed edges, fan-out/fan-in, human interrupt nodes, and explicit inter-loop feedback paths.
- **Verified, not vibed.** Deterministic gates (build / test / lint / custom linters) always run before any LLM judge. Worker and judge are physically separated contexts.
- **Auditable as a byproduct.** Every run emits intent → plan → steps → evidence → delivery as queryable JSONL plus OpenTelemetry GenAI traces.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ L1 INTENT        GitHub/GitLab issues · Linear · Jira · Slack   │
│                  · PRD files · CLI                              │
├─────────────────────────────────────────────────────────────────┤
│ L2 HARNESS (Coxswain)                                           │
│   cox-ir      portable Graph IR (graphs of loops) + DSLs        │
│   cox-engine  local durable executor (event-sourced,            │
│               checkpoint/resume)                                │
│   cox-loops   loop contracts, budgets, judges, oscillation      │
│               detection                                         │
│   cox-verify  deterministic gates + rubric judges + evidence    │
│   cox-context AGENTS.md autogen · skills registry · KG hooks    │
│   cox-policy  Cedar/OPA policy-as-code hooks                    │
├─────────────────────────────────────────────────────────────────┤
│ L3 WIRES (open protocols)                                       │
│   ACP → coding agents      MCP → tools      A2A → other agents  │
├─────────────────────────────────────────────────────────────────┤
│ L4 PLANES (adapters — all swappable)                            │
│   Runtime: local · Temporal · AgentCore · Agent Engine ·        │
│     Foundry hosted agents · Anthropic Managed Agents · K8s      │
│   Gateway: agentgateway (default) · AgentCore Gateway ·         │
│     Google Agent Gateway · Foundry/APIM                         │
│   Identity: OIDC broker → AgentCore Identity · Entra Agent ID · │
│     GCP IAM agent identity                                      │
│   Model: via gateway (OpenAI-compat) · direct SDKs              │
│   Memory: local store · AgentCore Memory · Memory Bank ·        │
│     Foundry memory                                              │
├─────────────────────────────────────────────────────────────────┤
│ L5 SANDBOX       Docker/Podman · Apple Container VM · gVisor    │
│                  on K8s · microVM · or the managed runtime's    │
│                  own sandbox                                    │
├─────────────────────────────────────────────────────────────────┤
│ CROSS-CUTTING    OTel GenAI traces · cost ledger · audit JSONL  │
│                  · evals · self-evolution loop                  │
└─────────────────────────────────────────────────────────────────┘
```

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

Anti-thrash machinery is core, not optional: failure-signature hashing, score-plateau detection, judge-disagreement tracking, per-loop cost ledgers.

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

The worker never sees the judge; the judge never sees the worker's chain of reasoning — only the rubric, the diff, and the gate outputs. Feedback edges are *declared, not implied*, so coupled-loop conflicts (speed loop vs quality loop) are inspectable instead of emergent.

## Status

**Design phase.** The full v1.0 build plan is published and is the plan of record:

### 📐 **[Read the build plan →](coxswain-ai-dlc-harness-plan.md)**

Coxswain is being built *with* the methodology it encodes (AWS AI-DLC: plan → approve → execute in bolts → verify), by Claude Code, against deterministic gates, from day one. The repo is the agent-experience surface — see [AGENTS.md](AGENTS.md).

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 0 | Scaffold, `@cox/verify` MVP, boundary linter, evidence v0 | ⏳ next |
| 1 | Graph IR + event-sourced local engine, replay determinism | — |
| 2 | ACP agent plane, sandbox, **the harness ships its own PR** | — |
| 3 | Loop engine, judge isolation, OTel GenAI observability | — |
| 4 | Gateway plane (agentgateway) + Cedar policy | — |
| 5 | Runtime adapters: Temporal · AgentCore · Google · Foundry · Anthropic — conformance-first | — |
| 6 | Context autogen, skills registry, intent surfaces (webhooks/Slack) | — |
| 7 | Self-evolution loop (prediction-gated), benchmark rig, **v1.0** | — |

## Design principles (the short version)

1. The harness never writes code.
2. Separate the worker from the judge.
3. Deterministic gates are the contract.
4. Vendor-agnostic at every layer — no lock-in, ever.
5. Loops are contracts; graphs are organizations.
6. Audit trail as byproduct.
7. Cost per task is a first-class metric.
8. Build to delete.

The full eleven, with rationale, are in [the plan](coxswain-ai-dlc-harness-plan.md#3-design-principles).

## Contributing

Early enough that the most valuable contributions are **design review and prior art**: open an issue against the plan. Once Phase 0 lands, `make verify` green is the only law. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache-2.0](LICENSE). Vendor-neutral, conformance-tested, built to be donated.
