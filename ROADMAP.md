# Roadmap — the 90-day compression

*Adopted 2026-07-29 after external design review. This document governs
execution order. The [full build plan](coxswain-ai-dlc-harness-plan.md)
remains the architectural north star — we are shipping it inside-out:
the differentiated core first (loop contracts, deterministic gates,
worker/judge isolation), the undifferentiated plumbing (multi-cloud
adapters, gateway planes, policy hooks) deferred until the loop exists
and pulled by demand rather than pushed by plan.*

**Hard deadline: `v0.1.0`, first installable release, September 30, 2026.**

## The 90-day arc

### Days 1–30 — the "One Loop" MVP

A CLI that takes a GitHub issue, runs a single **repair loop** locally,
and outputs a merge request with an evidence bundle. Nothing more. And
inside it, an even thinner first wedge (second external review):
**`cox verify` + evidence bundles are usable standalone before the loop
exists**, wrapped around the coding agent you already use. Coxswain
never ships an agent.

**Days 1–15 — `cox verify`, standalone.** The first thing a stranger
can adopt:

- `@cox/verify` v0.1 — pluggable gate runner: `build`, `test`, `lint` as
  shell-command gates with structured pass/fail, emitting
  `evidence.jsonl`.
- `cox verify` runs in any repo, around any session — Claude Code, Codex
  CLI, Gemini CLI, or a human — and produces the evidence bundle with no
  loop, no judge, no MR machinery. Gates + receipts, nothing else.

**Days 16–30 — the loop closes around it:**

- `@cox/ir` v0.1 — minimal YAML/JSON schema for a single-loop graph. One
  node kind: `loop:repair`.
- Worker binding = **your existing coding agent via subprocess** (Claude
  Code first; Codex/Gemini CLI next; ACP as the formal wire later).
- One rubric judge ("does this diff satisfy the issue's acceptance
  criteria?") via any OpenAI-compatible endpoint (local models work —
  Ollama for cheap dev).
- `@cox/engine` v0.1 — local in-memory executor: worker → gates → judge →
  iterate or exit. Run persisted as a JSONL evidence bundle.
- `cox run --issue <url> --repo <path>` → branch + MR + `evidence.jsonl`.
- **Dry-run mode**: gates run, judge is a deterministic rubric (no LLM
  call) — demos and CI cost nothing.

Cut from this slice: graph orchestration, fan-out/fan-in, human interrupt
nodes, all cloud adapters, Cedar/OPA, AGENTS.md autogen, skills registry.

### Days 31–60 — durable execution & anti-thrash

- Event-sourced engine: SQLite-backed run log, checkpoint/resume — crash
  on iteration 4 of 6, `cox resume` continues exactly there.
- Anti-thrash: failure-signature hashing + oscillation detection (same
  signature 3× → exit to `escalate.human`), plateau detection.
- Cost ledger per loop/run (`cost.jsonl` beside the evidence bundle).
- OpenTelemetry GenAI spans for worker and judge — "audit trail as
  byproduct" made real.

### Days 61–90 — the "graph of loops" demo

- `@cox/ir` v0.2 — a linear chain of loops: scope → plan → repair →
  deliver, with typed edges and explicit feedback paths.
- One `human` interrupt node: pause + webhook/Slack message, resume via
  `cox approve <run-id>`.
- **The credibility moment: Coxswain ships a Coxswain PR.** Dogfooded,
  with the full evidence bundle and cost ledger in the PR description.
- 5-minute demo video: issue → scope → plan → 3 repair iterations with
  gate failures → human approval → merged MR with evidence.

## OKRs

**Q3 2026:** Coxswain reliably turns a GitHub issue into a passing MR for
**Python repos** under **$2.00** in LLM spend. (`v0.1.0` ships Sept 30.)

**Q4 2026:** TypeScript target repos + the **Temporal** runtime adapter.

## Rulings that changed from the v1.0 plan

- **One hero runtime adapter, not five.** Temporal first — open source,
  widely deployed, and its durable-execution model matches the
  event-sourced engine. AgentCore / Agent Engine / Foundry / Anthropic
  Managed Agents adapters are deferred until the conformance suite exists
  and someone actually asks; the plan's §5 layout keeps their seats.
- **Phases 3–7 of the plan's §6 are deferred**, not deleted — gateway
  plane, policy hooks, context autogen, skills registry, self-evolution
  all wait behind a working, dogfooded loop.
- Implementation language stays **TypeScript** (plan §5 ruling); Python
  is the first *target* ecosystem, not the implementation.

## Risks

| Risk | Mitigation |
|---|---|
| Incumbents (LangGraph, Agent Framework) absorb loop contracts | Ship first; the moat is the verification-first implementation — gates before judges, physical worker/judge isolation |
| No contributors show up | The loop-contract schema is a standalone spec (RFC issues open now); schema adoption wins standards gravity even without the engine |
| Multi-cloud adapters too costly | Deferred; local + Temporal covers most of the durable-execution need |
| LLM costs make demos expensive | Dry-run mode + local models (Ollama) for development |
