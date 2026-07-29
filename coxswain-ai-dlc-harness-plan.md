# Coxswain — an open-source, enterprise-grade AI-DLC harness

**Build plan for Claude Code · v1.0 · July 29, 2026**

> Working title: **Coxswain** (CLI: `cox`). The coxswain steers the boat, calls the stroke rate, and never rows. The harness steers the work, sets the loop cadence, and never writes the code itself. Rename freely.

---

## 1. Thesis

The substrate is converging. Every serious AI-DLC implementation lands on the same five-layer architecture: **Intent → Harness → Protocol wire → Interchangeable agents → Sandboxed execution**, with context and governance cross-cutting. The frontier labs are all selling their piece of it: Anthropic Managed Agents, AWS Bedrock AgentCore, Google's Gemini Enterprise Agent Platform (née Vertex AI Agent Builder), Microsoft Foundry. The code layer is commoditizing; what stays defensible is governance, deterministic verification, audit trails, and execution speed on top of the substrate.

**Coxswain's bet:** nobody owns the *neutral* harness layer. Each cloud's harness locks you to its runtime, its identity system, its gateway. The open-source opportunity is a **control-plane-agnostic harness** that:

1. Compiles **intent** (tickets, PRDs, Slack messages) into **verified outcomes** (reviewed MRs with evidence).
2. Treats **loops** and **graphs** as first-class, portable primitives — not framework-specific code.
3. Runs the *same workflow definition* on your laptop, on Temporal, on AgentCore Runtime, on Google Agent Engine, on Foundry hosted agents, or on Anthropic Managed Agents — via adapters.
4. Routes all agent↔tool↔LLM↔agent traffic through a governed gateway plane (agentgateway by default; AgentCore Gateway / Google Agent Gateway / Foundry as alternatives).
5. Produces an audit trail as a byproduct of normal work, aligned to OpenTelemetry GenAI semantic conventions.

This is Kubernetes-vs-managed-containers, replayed one layer up. Apache-2.0, vendor-neutral, conformance-tested.

---

## 2. The July 2026 landscape (research grounding)

What exists today and what Coxswain must interoperate with:

### 2.1 Managed control planes (the "big four")

| Vendor | Runtime | Gateway | Identity | Memory | Notes |
|---|---|---|---|---|---|
| **AWS Bedrock AgentCore** (GA Oct 2025) | AgentCore Runtime: serverless, session-isolated, 8-hour execution windows, hosts agents *and* MCP servers, A2A support | AgentCore Gateway: MCP federation over Lambda/OpenAPI/Smithy targets + existing MCP servers; OAuth 2LO/3LO inbound, IAM or OAuth outbound | AgentCore Identity: token exchange across Okta/Entra/Cognito; workload access tokens | Short-term events + long-term strategies (semantic, preference, summary; self-managed pipelines) | AgentCore Policy checks every Gateway tool call against Cedar rules; natural-language policy authoring. Framework-agnostic (Strands, LangGraph, CrewAI…) |
| **Google Gemini Enterprise Agent Platform** (rebrand of Vertex AI Agent Builder, Cloud Next 2026) | Agent Engine / Agent Platform Runtime: managed, $0.0864/vCPU-hr; also Cloud Run & GKE | **Agent Gateway**: route Agent Runtime traffic for "secure and governed connectivity" | IAM agent identity; agent credentials secured by Context-Aware Access by default | Memory Bank + Sessions ($0.25/1k events) | ADK is open source (Apache-2.0; Python/TypeScript/Go/Java) with Sequential/Parallel/**Loop** workflow agents; A2A native; 200+ models incl. Claude |
| **Microsoft Foundry** (Build 2026) | Foundry Agent Service: prompt agents + **hosted agents** (bring a container; GA ~July 2026); session-isolated sandbox w/ compute, memory, filesystem; Responses API as single entry point | Foundry tool catalog + 1,400+ MCP-enabled tools; APIM in front for enterprises | Entra Agent ID; BYO VNet, no public egress option | Managed memory; Foundry IQ knowledge plane (SharePoint/Fabric/Bing) | Hosted agents explicitly run Agent Framework, LangGraph, OpenAI Agents SDK, **Anthropic Agent SDK**, GitHub Copilot SDK, or custom code. Agent Framework = open-source successor to Semantic Kernel + AutoGen. Foundry Control Plane for governance |
| **Anthropic Managed Agents** (public beta Apr 8, 2026) | Fully managed harness+sandbox+session; $0.08/session-hour (running time only) + standard tokens | Native MCP | Scoped permissions, execution tracing | Persistent sessions, checkpointing | Outcomes = built-in worker/judge self-evaluation; multi-agent coordination in research preview. Claude Agent SDK for self-hosted equivalents |

### 2.2 The open protocol & gateway layer

- **MCP** — agent↔tool. The universal plug. All four clouds now speak it.
- **A2A** — agent↔agent. Donated by Google to the Linux Foundation (June 2025); agent cards at `/.well-known/agent-card.json`; supported by AgentCore Runtime and Google's platform.
- **ACP (Agent Client Protocol)** — harness↔coding-agent. Zed's open standard (Apache-2.0, JSON-RPC over stdio); adopted by Zed, JetBrains, Neovim, Emacs; 25+ agents including Gemini CLI, Codex CLI, OpenCode, and Claude Code (via Zed's bridge adapter). The **ACP Registry** (Jan 2026) gives one-time agent registration → available to every ACP client. This is Coxswain's Layer-4 wire — a primitive that multiple independent harness efforts have now converged on.
- **agentgateway** — Linux Foundation open-source, Rust data plane, purpose-built for stateful MCP/A2A sessions plus an OpenAI-compatible LLM gateway (budget/spend controls, prompt enrichment, failover across OpenAI/Anthropic/Gemini/Bedrock), Kubernetes Gateway API support via kgateway, OAuth, tool federation, multi-tenancy. This is the default open data plane for Coxswain's gateway abstraction.

### 2.3 Methodology

- **AWS AI-DLC** (published July 2025; workflows open-sourced Nov 2025 at `awslabs/aidlc-workflows`): three phases — **Inception** (AI turns intent into requirements/stories/units of work via "Mob Elaboration"), **Construction**, **Operations** — executed in **bolts** (hours-to-days work cycles replacing sprints), with adaptive rigor (greenfield vs brownfield detection, risk-based ceremony). Explicitly agent/IDE/model-agnostic steering rules. Coxswain encodes this methodology as executable graph templates rather than markdown steering files.

### 2.4 Loop engineering and graph engineering (the June–July 2026 shift)

The discipline stack is now commonly described as **Prompt → Context → Harness → Loop → Graph**, each layer wrapping the one beneath:

- **Loop engineering** (coined June 2026; Boris Cherny: "I don't prompt Claude anymore. I have loops that are running. They're the ones prompting Claude."): design the *system* that prompts the agent — discover → plan → execute → **verify** → repeat until a stop condition. The verifier is the bottleneck. Andrew Ng's nesting: agentic coding loop (minutes) ⊂ developer feedback loop (hours) ⊂ external/user feedback loop (days).
- **Graph engineering** (crystallized ~July 18, 2026 via Peter Steinberger / OpenClaw): loops made *one agent's behavior* programmable; graphs make *agent organizations* programmable — specialized nodes in parallel, typed edges, state flowing between them, feedback routed through specific paths rather than the whole loop. Resident agents vs ephemeral workers. The skeptics are right that LangGraph / Microsoft Agent Framework Workflows / Google ADK shipped this before the term existed — which is precisely why Coxswain treats those as *compile targets*, not competitors.
- **Coupled-loop failure modes** (from the graph-engineering critique): independent loops optimizing local metrics can fight each other (speed loop vs quality loop), targets drift, sensors rot. The graph layer must make loop *interactions* explicit and observable.
- **AHE** (Fudan, Apr 2026): observability-driven self-evolution of the harness itself — component/experience/decision observability pillars; 10 iterations lifted Terminal-Bench 2 from 69.7 → 77%, transferring across model families at fewer tokens. The endgame loop: the harness improves the harness, gated by falsifiable prediction contracts.

**Design consequence:** Coxswain's core abstraction is a **graph of loops**. A node is not a function call — it's a *loop-bearing agent* with a contract (budget, verifier, exit conditions). The graph wires those loops into an organization with typed edges, parallel fan-out/fan-in, human interrupt nodes, and explicit inter-loop feedback paths.

### 2.5 Observability standard

**OpenTelemetry GenAI semantic conventions** (`gen_ai.*`): `invoke_agent` / `chat` / `execute_tool` span nesting, model + token attributes, operation-duration metrics; client spans stabilized in early 2026, agent/framework spans still maturing (repo split June 2026). Adopt the shape now, pin the version, and isolate attribute strings behind a thin mapping layer. OTel graduated CNCF May 2026 — this is the substrate every backend (Datadog, Grafana, Langfuse, AgentCore Observability, Foundry, Cloud Trace) consumes.

---

## 3. Design principles

Distilled from published enterprise harness practice (Cloudflare's internal AI engineering stack, Anthropic's managed-agents architecture, the AHE literature) and restated as build constraints:

1. **The harness never writes code.** It scopes, orchestrates, verifies, and delivers. Agents write code.
2. **Separate the worker from the judge.** Execution and evaluation run in isolated contexts; the judge can be a smaller/cheaper model; deterministic gates run before any LLM judge.
3. **Plan, then execute, then verify, in tight loops.** Explicit planning step; plan-approval gates where stakes warrant; verification cheap enough to run every iteration.
4. **Vendor-agnostic at every layer.** Three hard requirements: non-engineers can safely contribute to production code; multiple models orchestrated per task; no lock-in at any layer. Any proposal failing one of these is rejected.
5. **Deterministic gates are the contract.** Build/test/lint/typecheck plus repo-specific custom linters (architecture boundaries, file-size limits, conventions). A gate is a falsifiable contract the agent must satisfy.
6. **The repo is the agent-experience surface.** AGENTS.md, fast deterministic tests, structured error messages > prompt engineering.
7. **Build to delete.** Invest in abstractions (IR, adapter interfaces, conformance tests) that make every concrete artifact cheap to replace.
8. **Audit trail as byproduct.** Every run emits intent → plan → steps → evidence → delivery as queryable JSONL + OTel traces. Align with ISO 42001 / Five Eyes agentic-AI guidance posture.
9. **Governance at the artifact, not the human queue.** Automated gates, automated skill scoring, policy-as-code. Prohibition produces shadow IT.
10. **Loops are contracts; graphs are organizations.** Every loop declares budget, verifier, and exit conditions. Every graph declares which loops feed which, so coupled-loop conflicts are visible, not emergent.
11. **Cost per task is a first-class metric.** Route frontier models to hard steps, cheap models to judging; tripwire on token burn.

---

## 4. Architecture

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
│   Runtime plane: local · Temporal · AgentCore Runtime ·         │
│     Google Agent Engine · Foundry hosted agents ·               │
│     Anthropic Managed Agents · K8s/Cloud Run                    │
│   Gateway plane: agentgateway (default) · AgentCore Gateway ·   │
│     Google Agent Gateway · Foundry/APIM                         │
│   Identity plane: OIDC broker → AgentCore Identity ·            │
│     Entra Agent ID · GCP IAM agent identity                     │
│   Model plane: via gateway (OpenAI-compat) · direct SDKs        │
│   Memory plane: local store · AgentCore Memory · Memory Bank ·  │
│     Foundry memory                                              │
├─────────────────────────────────────────────────────────────────┤
│ L5 SANDBOX       Docker/Podman · Apple Container VM · gVisor    │
│                  on K8s · microVM (Firecracker/E2B-style) ·     │
│                  or delegate to managed runtime's sandbox       │
├─────────────────────────────────────────────────────────────────┤
│ CROSS-CUTTING    OTel GenAI traces · cost ledger · audit JSONL  │
│                  · evals · self-evolution loop                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.1 The Graph IR (the crown jewel)

A versioned, JSON-serializable intermediate representation. Authoring surfaces: **YAML-first** (non-engineers, diffable, PR-reviewable) and a **TypeScript DSL** (type-safe composition), both compiling to the same IR. Python DSL later.

**Node kinds (v1):**

- `agent_step` — a loop-bearing worker. References an agent binding (ACP agent, A2A peer, HTTP/Responses endpoint, or MCP-only LLM step), a skill set, a sandbox profile, and a **loop contract**.
- `judge` — evaluator in an isolated context; rubric + evidence in, verdict + reasons out. Model may differ from worker's.
- `gate` — deterministic verifier (command with structured pass/fail: build, test, lint, typecheck, custom linter, security scan).
- `human` — interrupt node: plan approval, mob-elaboration review, escalation. Durable park-and-resume (hours/days).
- `fanout` / `join` — parallel dispatch of ephemeral workers; join strategies: all, quorum, first-pass-gate, judge-ranked best-of-n.
- `router` — conditional edges on typed state (risk tier, repo readiness score, diff size).
- `tool` — direct MCP call without an agent (deterministic side effects: open MR, post Slack message, query knowledge graph).
- `subgraph` — composition + reuse; the unit of "resident agent" (long-lived subgraph instance) vs ephemeral worker (fanout-spawned).
- `loop` — explicit cyclic region wrapping any subgraph with a loop contract (see 4.2).

**Edges** are typed channels over a shared, schema'd state object (Zod-validated). Feedback edges are declared, not implied — a judge's verdict routes to *named* targets, which is what makes coupled-loop conflicts (speed-loop vs quality-loop) inspectable.

**Determinism & durability contract:** every node execution is an event in an append-only run log; state transitions are replayable; any node can checkpoint; `human` and long `agent_step` nodes park durably. This contract is what each runtime adapter must honor (natively on Temporal/AgentCore; emulated locally).

**Portability rule:** the IR references *capabilities* (e.g., `sandbox: isolated-vm`, `memory: session`), never vendor resources. Adapters map capabilities to vendor primitives, and the conformance suite proves the mapping.

### 4.2 Loop contracts (loop engineering made executable)

Every `loop` and `agent_step` declares:

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
    on_pass: continue      # proceed along pass edge
    on_budget_exhausted: escalate.human
    on_oscillation: escalate.human       # same-failure-signature repeated N times
    on_plateau: best_effort_deliver      # judge score not improving
  evidence: full           # every iteration captured to the run bundle
```

Built-in loop kinds:

- **repair** — run gates, feed structured failures back to the worker, retry (the canonical test-fix loop).
- **evaluator_optimizer** — worker produces, judge critiques against a rubric, worker revises (Anthropic's original pattern; Outcomes/`/goals` equivalent).
- **convergence** — iterate until a scalar score crosses a threshold.
- **explore** — best-of-n via fanout + judge-ranked join.
- **evolve** — the AHE loop (Phase 7): propose a harness/skill edit **with a falsifiable prediction** ("this change raises eval suite X pass-rate by ≥Y%"), run the eval, keep or revert. Predictions and outcomes are logged, so the self-evolution loop is itself auditable.

Anti-thrash machinery is core, not optional: failure-signature hashing (oscillation detection), score-plateau detection, judge-disagreement tracking (worker claims done, judge says no, repeatedly), and per-loop cost ledgers feeding the cost-per-task metric.

### 4.3 Worker/judge separation (enforced)

The engine physically prevents a worker's context from leaking into its judge: judges get the rubric, the diff/artifacts, and gate outputs — never the worker's chain of reasoning. Default judge model is configurable per workflow (cheap-model default, e.g., Haiku-class); judge verdicts are structured (`pass | fail | needs_human`, reasons, per-criterion scores).

### 4.4 Gateway plane

All LLM, MCP, and A2A traffic flows through a `GatewayProvider` interface:

- **Default: agentgateway** — Coxswain ships config generation (`cox gateway init`) producing agentgateway listeners/targets for: LLM routing with per-workflow budget caps and failover; MCP tool federation (knowledge-graph, ownership/directory, and repo tools appear as one governed MCP surface); A2A exposure of Coxswain runs as agents (agent card publishing).
- **AgentCore Gateway adapter** — register MCP targets; inbound OAuth per AgentCore Identity; policy checks land in Cedar (same language as cox-policy → policies port cleanly).
- **Google Agent Gateway adapter** — route Agent Engine traffic per Google's governed-connectivity model.
- **Foundry adapter** — tool catalog / APIM-fronted MCP.

Policy hooks (Cedar first, OPA optional) evaluate: which workflows may call which tools, spend ceilings, data-classification rules ("no repo X context to model Y"), egress allowlists.

### 4.5 Identity plane

`IdentityBroker` interface: inbound (who may start/approve runs — OIDC), workload (the run's own identity), outbound (tokens for GitHub/GitLab/Slack/Jira on behalf of user or service). Adapters: plain OIDC + secrets store (local), AgentCore Identity (token exchange), Entra Agent ID, GCP IAM agent identity. Every delegated action is stamped into the audit trail with the acting identity.

### 4.6 Verification & evidence

`cox-verify` runs gates in a sandbox profile, parses structured output (JUnit XML, ESLint JSON, tsc, custom linter JSON schema), and assembles the **evidence bundle** per run: `run.jsonl` (event log), `plan.md`, per-iteration gate reports, judge verdicts, diffs, optional screen recordings (browser/UI tasks), cost ledger, OTel trace IDs. `cox evidence open <run>` renders it; the MR description embeds the summary + link. This is the S-1-grade audit artifact.

### 4.7 Context & governance layer

- **AGENTS.md autogen** — `cox context scan` inspects a repo (language, framework, test/lint/build commands, layout, CI config) and generates/refreshes AGENTS.md (the de facto cross-agent standard) + a machine-readable `agents.lock.json` the harness consumes. Cloudflare has demonstrated this at thousands-of-repos scale; this is the ≤1-day-onboarding lever.
- **Repo readiness scorecard** — `cox context readiness` scores test speed/determinism, lint coverage, build time, docs; the `router` node can gate autonomous modes on readiness tier.
- **Skills registry** — skills are markdown files in-repo (`.cox/skills/`) with frontmatter; `cox skills eval` runs baseline-vs-skill A/B evals and scores on a rubric (justification, description, gotchas, fallback, structure). Distribution via git; quality enforced at the artifact, no human gatekeeping chokepoint. Registry index is just a git repo + static JSON.
- **Knowledge-graph hook** — a documented MCP interface (`kg.dependencies`, `kg.owners`, `kg.impact`) the scoping stage queries when present; ships with a reference implementation backed by a repo-scan + CODEOWNERS, so the pattern works day one and enterprises swap in their real graph.

### 4.8 AI-DLC methodology, encoded

Templates in `templates/aidlc/` map AWS AI-DLC onto graphs:

- **Inception graph**: intent → `agent_step` (elaboration: questions, requirements, units of work) → `human` (mob-elaboration approval) → emit **bolts** (units of work as child run specs).
- **Construction graph** (per bolt): scope (reads AGENTS.md + KG) → plan → `human` approval (risk-tiered: auto-approve for docs/dep-bumps/low-risk per router) → `loop:repair` execute → `judge` → deliver (MR + evidence).
- **Operations graph**: post-merge watch → incident intent loop-back.
- Adaptive rigor = router nodes on greenfield/brownfield detection + readiness score, mirroring `awslabs/aidlc-workflows` semantics so teams already using AWS's steering files can migrate.

### 4.9 Observability

`cox-otel` emits GenAI-semconv spans (`invoke_agent` → `chat` → `execute_tool` nesting; `gen_ai.request.model`, token usage, cost attrs) with attribute strings isolated behind one mapping module (conventions are pre-1.0; pin + wrap). Plus Coxswain-namespaced loop metrics: `cox.loop.iterations_to_green`, `cox.loop.oscillations`, `cox.judge.disagreement_rate`, `cox.run.cost_usd`, `cox.run.hours_saved_estimate`. OTLP export → anything (Grafana/Langfuse/Datadog/AgentCore Observability/Foundry/Cloud Trace).

---

## 5. Repository layout

Monorepo, TypeScript (Node 22), pnpm workspaces, Apache-2.0. (TS because ACP/agentgateway/ADK-TS/Agent Framework all have first-class TS/JSON surfaces and the YAML→IR compiler benefits from Zod; Python SDK is Phase 6+.)

```
coxswain/
  AGENTS.md                      # dogfood from day one
  packages/
    ir/                          # @cox/ir — Zod schemas, YAML+TS DSL → IR compiler, validators
    engine/                      # @cox/engine — event-sourced local executor, SQLite checkpoints
    loops/                       # @cox/loops — loop contracts, budgets, oscillation/plateau detectors
    verify/                      # @cox/verify — gate runners, output parsers, evidence bundler
    judge/                       # @cox/judge — rubric judge harness, context isolation
    acp/                         # @cox/acp — ACP client, agent registry integration, session mgmt
    gateway/                     # @cox/gateway — GatewayProvider iface + agentgateway config gen
    identity/                    # @cox/identity — IdentityBroker iface + OIDC/local
    otel/                        # @cox/otel — GenAI semconv mapping layer + cox.* metrics
    context/                     # @cox/context — AGENTS.md autogen, readiness score, skills evals
    policy/                      # @cox/policy — Cedar evaluation hooks
    runtimes/
      local/                     # in-process (wraps engine)
      temporal/                  # durable OSS execution
      agentcore/                 # AWS Bedrock AgentCore Runtime + Gateway + Identity + Memory
      google/                    # Agent Engine (Gemini Enterprise Agent Platform) + Agent Gateway
      foundry/                   # MS Foundry hosted agents (container + Responses API)
      anthropic/                 # Anthropic Managed Agents / Agent SDK
    cli/                         # @cox/cli — the `cox` binary
  conformance/                   # runtime + gateway adapter conformance suites
  templates/
    aidlc/                       # inception/construction/operations graph templates
    library/                     # repair-pr, best-of-n, docs-sync, dep-bump, overnight-feature
  examples/
  docs/
  .github/workflows/             # CI = coxswain's own gates
```

---

## 6. Phased execution plan (for Claude Code)

**Operating discipline (meta):** build Coxswain *with* AI-DLC. Each phase = a bolt series. For every bolt: Claude Code produces a plan first; human approves; execution runs against the deterministic gates below; every session ends with `make verify` green and a conventional-commit PR small enough to review. Maintain AGENTS.md continuously. Build to delete: no package may import another's internals — interfaces only (enforced by a custom lint gate from Phase 0).

**Universal gates (Phase 0 onward):** `make verify` = typecheck (tsc strict) + lint (eslint + custom boundary linter) + unit tests (vitest) + build. CI mirrors it. No PR merges red.

### Phase 0 — Scaffold & dogfood substrate (Days 1–3)

Deliverables: monorepo scaffold; AGENTS.md; CI; `@cox/verify` MVP (run a command, parse pass/fail, emit JSON report); the custom **architecture-boundary linter** (which packages may import which); evidence-bundle v0 (run.jsonl writer).
Claude Code kickoff prompt:
> "Using AI-DLC, scaffold the coxswain monorepo per §5 of the plan. pnpm + TS strict + vitest + eslint. Implement @cox/verify with gate runners for tsc/eslint/vitest and a JSON evidence report, plus a custom eslint rule enforcing the package-boundary matrix in docs/boundaries.json. Wire make verify and GitHub Actions. Write AGENTS.md describing how to build/test/lint this repo. Plan first; wait for approval."
Exit: CI green; `cox` binary prints version; boundary linter fails on a seeded violation (test proves the gate bites).

### Phase 1 — Graph IR + local engine (Weeks 1–2)

Deliverables: `@cox/ir` (Zod schemas for all §4.1 node kinds; YAML loader; TS DSL; compiler + validator with helpful errors); `@cox/engine` (event-sourced executor over SQLite: run/step events, checkpoint, resume, replay; `human` node parks durably and resumes via `cox approve <run>`); `cox run graph.yaml`, `cox graph validate`, `cox graph viz` (mermaid export).
Exit: golden-fixture suite — 12 canonical graphs (linear, branch, fanout/join strategies, nested subgraph, loop with budget exhaustion, human interrupt, crash-mid-run resume) all replay deterministically.

### Phase 2 — Agent plane via ACP + sandbox + first end-to-end (Weeks 2–3)

Deliverables: `@cox/acp` (spawn/manage ACP agents over stdio; permission brokering; session transcripts into evidence); Claude Code binding (via the ACP bridge) + Gemini CLI binding (native ACP) as proof of interchangeability; sandbox profiles v1 (Docker/Podman: workspace mount, no-network default, credential injection via env broker); `tool` nodes for `git` + GitHub/GitLab MR creation.
**Milestone: the harness ships its own PR.** A `construction` graph takes a real issue on the coxswain repo → scopes → plans → human approves → Claude Code executes in sandbox → gates pass → MR opens with evidence bundle.
Exit: same graph YAML runs with `agent: claude-code` and `agent: gemini-cli` unchanged.

### Phase 3 — Loop engine + judge + observability (Weeks 3–5)

Deliverables: `@cox/loops` (repair, evaluator_optimizer, convergence, explore; budgets; failure-signature oscillation detection; plateau detection; escalation edges); `@cox/judge` (isolated judge context; rubric YAML; structured verdicts; cheap-model default with per-workflow override); `@cox/otel` (GenAI semconv spans behind the mapping layer + `cox.*` metrics; OTLP export; docker-compose with Grafana/Tempo for local viewing); cost ledger per run/loop/node.
Exit: benchmark script runs the repair loop on 10 seeded-bug fixtures; dashboard shows iterations-to-green, cost-per-task, judge-disagreement; worker context provably absent from judge input (test).

### Phase 4 — Gateway plane + policy (Weeks 5–6)

Deliverables: `GatewayProvider` interface; **agentgateway integration**: `cox gateway init` generates config (LLM routes w/ budget caps + failover across Anthropic/OpenAI/Gemini/Bedrock; MCP federation of the KG-reference + repo tools; A2A listener exposing runs as agents with generated agent cards); `@cox/policy` Cedar hooks enforced at tool-call and model-call time; red-team tests (policy denies out-of-scope tool, spend cap trips mid-run and loop escalates cleanly).
Exit: all Phase-2/3 flows run *through* the gateway with policies on; A2A: an external ADK sample agent invokes a Coxswain run via agent card.

### Phase 5 — Managed runtime + identity adapters, conformance-tested (Weeks 6–9)

Build the **conformance suite first**: ~25 behaviors every runtime adapter must pass (start/resume/cancel, checkpoint durability, human-interrupt park ≥24h simulated, fanout concurrency, budget enforcement, evidence completeness, identity stamping).
Then adapters, in order:
1. **Temporal** (OSS durable baseline — proves the IR maps to industrial durable execution).
2. **AWS AgentCore**: deploy graph runs on AgentCore Runtime; register Coxswain's MCP surface into AgentCore Gateway; IdentityBroker → AgentCore Identity; optional Memory adapter; export traces to AgentCore Observability.
3. **Google**: Agent Engine deployment (via ADK wrapper for runtime compatibility); route through Google **Agent Gateway**; IAM agent identity.
4. **Microsoft Foundry**: package the engine as a hosted-agent container exposing the Responses protocol; Entra Agent ID; tool catalog wiring.
5. **Anthropic Managed Agents**: adapter mapping `agent_step` loops onto managed sessions (leveraging Outcomes for the judge where it fits) + Claude Agent SDK path for self-hosted.
Exit: `cox run graph.yaml --runtime {local|temporal|agentcore|google|foundry|anthropic}` — same YAML, five clouds, conformance badges in CI (cloud adapters behind env-gated integration jobs).

### Phase 6 — Context, skills, and intent surfaces (Weeks 9–11)

Deliverables: `cox context scan` (AGENTS.md + agents.lock.json autogen), readiness scorecard, router templates keyed on readiness tier; skills registry + `cox skills eval` (baseline-vs-skill A/B with the judge harness); KG reference MCP server (repo scan + CODEOWNERS); intent adapters: GitHub/GitLab webhook service (`label: cox` → run), Slack app (`/cox run …`, approval buttons resolve `human` nodes), Linear/Jira webhooks.
Exit: a stranger's repo goes from clone → scanned → first governed harness PR in under one day, measured.

### Phase 7 — Self-evolution + benchmark rig + v1.0 (Weeks 11–13)

Deliverables: `evolve` loop — harness/skill edits proposed only with a **falsifiable prediction contract** (target eval, predicted delta, rollback rule); prediction ledger; benchmark rig wiring Terminal-Bench-2-style tasks + a SWE-bench-lite subset so evolution has ground truth; safety rails (evolve loop may only touch skills/templates/config — never engine code — enforced by the boundary linter + policy).
Release engineering: docs site, quickstart ("issue → verified MR in 15 minutes on your laptop"), threat model doc, ISO 42001-mapped audit-trail doc, versioning policy for the IR (semver + migration tool), CONTRIBUTING + governance (steering committee, path toward foundation donation), `v1.0.0`.

---

## 7. Testing & quality strategy

- **Golden fixtures** for IR/engine (replay determinism is the invariant).
- **Conformance suites** for runtimes and gateways — the ecosystem contract; publish a "Runs Coxswain" badge program.
- **Chaos tests**: kill the engine mid-loop, kill the sandbox, expire tokens mid-run — resume must be clean.
- **Judge integrity tests**: context isolation, rubric injection resistance (worker output attempting to instruct the judge is treated as data).
- **Security tests**: sandbox egress denial, credential non-exposure in transcripts/evidence, policy bypass attempts.
- **Self-benchmark**: the repo's own issues are the eval set; weekly report of iterations-to-green, cost-per-task, autonomous-merge rate by risk tier.

## 8. Metrics that decide success

Cost per task; iterations-to-green; judge disagreement rate; oscillation rate; % runs through governed gateway channels (target → 100%); repo onboarding time (target < 1 day); and the economic tripwire — **2–4 saved engineer-hours per engineer per month** across ≥2 external pilot teams within a quarter of v1.0, or refocus the wedge.

## 9. Risks & mitigations

- **Semconv/protocol churn** (OTel GenAI pre-1.0; ACP evolving; vendor APIs in beta) → all external strings/surfaces behind mapping layers; pin versions; conformance tests catch drift.
- **Adapter sprawl** → conformance-first development; cloud adapters are community-maintainable because the contract is executable.
- **"Reinvented LangGraph" critique** → true and intended: LangGraph/ADK/Agent Framework are *targets and peers*, not competitors; Coxswain's value is the vendor-neutral IR + verification/evidence/governance layer above them. Ship a LangGraph-interop exporter early to make the posture concrete.
- **Self-evolution risk** → evolve loop scoped to skills/templates only, prediction-gated, fully audited, off by default.
- **Judge gaming** → deterministic gates always precede judges; judges see evidence, not persuasion.

## 10. Non-goals (v1)

A UI builder; a model marketplace; long-horizon consumer memory; replacing CI systems (Coxswain drives them); a proprietary agent (bring any ACP/A2A agent).

---

## 11. Future-proofing: position over artifact

"Build to delete" already concedes that the code cannot be future-proofed. The position can. Six moves, in priority order:

1. **Extract the spec from the implementation.** The Graph IR, loop-contract schema, and conformance behaviors move into a standalone, semver'd spec repo (`cox-spec`, JSON Schema published) under open governance; the engine becomes the *reference implementation*. Target a second, independent implementation within two quarters of v1.0 — a spec with one implementation is an API; with two it's a standard. Donation path: Linux Foundation (where A2A and agentgateway already live) once two external maintainers exist. End state: when a hyperscaler ships "the neutral layer," the cheapest way for them to do it is to *implement Coxswain conformance* — their entry becomes adoption, not displacement.
2. **Weaponize the conformance suite.** The suite, not the adapters, is the moat (the Kubernetes-conformance lesson). Split it into its own repo at Phase 5 exit; run a public "Runs Coxswain" badge program with published results. Goal state: vendors maintain *their own* adapters to keep the badge, flipping maintenance cost outward.
3. **Compound data, not code.** Orchestration code is perishable; longitudinal data is not. The evidence bundles, prediction ledger, and loop telemetry become an open, anonymized, opt-in dataset: loop/graph designs vs. outcomes (iterations-to-green, cost-per-task, oscillation rates, by pattern × model generation). Publish it as the reference benchmark for loop engineering — the SWE-bench move, one layer up. Accumulated data cannot be leapfrogged by a competitor's launch.
4. **Bet on invariants.** Whatever models do, enterprises will need verification, audit trails, identity delegation, and cost control *more* every year, and regulation only compounds (ISO 42001; EU AI Act obligations phasing in through 2027). Maintain a living compliance-mapping document from evidence-bundle fields to control frameworks. Coxswain's terminal identity — the one no model improvement obsoletes — is the **evidence and governance layer**.
5. **Design for capability absorption.** Frontier models will keep eating harness features (planning scaffolds, repair heuristics). Make shedding them a designed path: every harness feature carries a *deprecation predicate* ("disable structured-planning scaffold for model tiers that pass eval Y"), and the evolve loop tests these predicates automatically each model generation. The harness gets thinner as models improve — on purpose, with evidence.
6. **Anti-rug-pull governance from day zero.** Apache-2.0, neutrally-held trademark, published governance charter, and at least two corporate maintainers before v1.0. Post-HashiCorp, enterprises audit this before adopting; the fork-resistance *is* the sales pitch.

**Plan amendments:** add a spec-extraction workstream at Phase 4.5 (`cox-spec` repo + JSON Schema publication); split the conformance suite into its own repo at Phase 5 exit; build the opt-in telemetry/dataset pipeline in Phase 6; ship the compliance-mapping doc in Phase 7.

---

## Appendix A — Claude Code session bootstrap

Paste at the start of every build session:

> You are building **Coxswain** per `coxswain-ai-dlc-harness-plan.md`. Current phase: {N}. Rules: (1) Using AI-DLC — plan first, wait for approval, execute in bolts. (2) Never merge red: `make verify` must pass. (3) Respect the package-boundary matrix; interfaces only across packages. (4) Small reviewable PRs, conventional commits, evidence in the PR description. (5) Any vendor string, protocol attribute, or external API goes behind the designated mapping layer. (6) Update AGENTS.md when build/test/lint behavior changes. Confirm the phase's exit criteria before proposing the plan.

## Appendix B — Key references

- AWS AI-DLC methodology + `awslabs/aidlc-workflows` (open-sourced Nov 2025)
- Amazon Bedrock AgentCore docs (Runtime, Gateway, Identity, Memory, Policy/Cedar, Observability; GA Oct 2025)
- Google Gemini Enterprise Agent Platform docs (ADK, Agent/Platform Runtime, Agent Gateway, Memory Bank; Cloud Next 2026 rebrand)
- Microsoft Foundry (Agent Service hosted agents, Agent Framework, Entra Agent ID, Foundry IQ/Control Plane; Build 2026)
- Anthropic Managed Agents (public beta Apr 8, 2026; $0.08/session-hr; Outcomes; multi-agent preview) + Claude Agent SDK
- agentgateway.dev (Linux Foundation; MCP/A2A/LLM gateway, Rust) + kgateway (K8s Gateway API)
- Agent Client Protocol — agentclientprotocol.com + ACP Registry (Jan 2026)
- A2A — a2a-protocol.org (Linux Foundation, June 2025)
- OpenTelemetry GenAI semantic conventions (gen_ai.*; CNCF graduation May 2026)
- AHE: "Agentic Harness Engineering: Observability-Driven Automatic Evolution of Coding-Agent Harnesses" (Fudan, Apr 2026)
- Loop engineering (June 2026; Cherny/Osmani) and graph engineering (July 2026; Steinberger et al.) discourse
- Anthropic, "Building Effective Agents" (Dec 2024) — evaluator-optimizer origin
