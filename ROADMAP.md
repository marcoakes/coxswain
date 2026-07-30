# Roadmap — the 90-day compression

*Adopted 2026-07-29 after external design review. This document governs
execution order. The [full build plan](wringer-ai-dlc-harness-plan.md)
remains the architectural north star — we are shipping it inside-out:
the differentiated core first (loop contracts, deterministic gates,
worker/judge isolation), the undifferentiated plumbing (multi-cloud
adapters, gateway planes, policy hooks) deferred until the loop exists
and pulled by demand rather than pushed by plan.*

**Hard deadline: `v0.1.0`, first installable release, September 30, 2026.**

## The 90-day arc

### Days 1–30 — v0.1.0, the standalone evidence compiler

⚠️ **Superseded in detail by [SPEC_VERIFY_V0.md](SPEC_VERIFY_V0.md)**
(third external review, 2026-07-30) — the binding implementation
contract. The essence: **`wring verify` ships first as a standalone
evidence compiler**, before `wring run`, before the graph IR, before
judges, before agents. One command that proves whether a change is
mergeable and leaves behind evidence a human or agent can inspect.

- `wring init` — detect project commands, write `.wringer.yaml`.
- `wring verify` — run declared gates in order, write the evidence bundle
  (`manifest.json`, `evidence.jsonl`, `summary.md`, `diff.patch`, gate
  logs). Exit codes are contract. `--json` for agent consumption.
- `wring explain` — compact non-LLM diagnosis of the latest failed run.
- Five-day build order + the "Definition of PROVEN" release bar (CI runs
  `wring verify` on this repo; a sanitized demo bundle is committed; the
  README transcript is real) — all in the spec.

**v0.1.0 tags when the spec's release bar is fully true** — well before
the Sept 30 outer deadline if the bolts land clean.

**After v0.1.0 (v0.2, inside the 90 days) — the loop closes around it:**

- `wring run` = a loop that keeps calling `wring verify` until the evidence
  says stop. Minimal single-loop IR (`loop:repair`), in-memory engine.
- Worker binding = **your existing coding agent via subprocess** (Claude
  Code first; Codex/Gemini CLI next; ACP as the formal wire later).
- One rubric judge via any OpenAI-compatible endpoint (Ollama works);
  dry-run mode keeps demos and CI at zero LLM spend.
- Issue → branch + MR + evidence delivery.

Cut from this slice: graph orchestration, fan-out/fan-in, human interrupt
nodes, all cloud adapters, Cedar/OPA, AGENTS.md autogen, skills registry.

### Days 31–60 — durable execution & anti-thrash

- Event-sourced engine: SQLite-backed run log, checkpoint/resume — crash
  on iteration 4 of 6, `wring resume` continues exactly there.
- Anti-thrash: failure-signature hashing + oscillation detection (same
  signature 3× → exit to `escalate.human`), plateau detection.
- Cost ledger per loop/run (`cost.jsonl` beside the evidence bundle).
- OpenTelemetry GenAI spans for worker and judge — "audit trail as
  byproduct" made real.

### Days 61–90 — the "graph of loops" demo

- `@wringer/ir` v0.2 — a linear chain of loops: scope → plan → repair →
  deliver, with typed edges and explicit feedback paths.
- One `human` interrupt node: pause + webhook/Slack message, resume via
  `wring approve <run-id>`.
- **The credibility moment: Wringer ships a Wringer PR.** Dogfooded,
  with the full evidence bundle and cost ledger in the PR description.
- 5-minute demo video: issue → scope → plan → 3 repair iterations with
  gate failures → human approval → merged MR with evidence.

## OKRs

**Q3 2026:** Wringer reliably turns a GitHub issue into a passing MR for
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
- **v0 implementation is Python** (third review, 2026-07-30: ubiquitous,
  inspectable, `pipx`-installable, right audience — see
  [SPEC_VERIFY_V0.md](SPEC_VERIFY_V0.md)). This supersedes the
  earlier TypeScript-first ruling for v0.1; the TS monorepo remains the
  plan's shape for the later graph engine — revisit at v0.2. Python
  repos are also the first *target* ecosystem (Q3 OKR).

## Risks

| Risk | Mitigation |
|---|---|
| Incumbents (LangGraph, Agent Framework) absorb loop contracts | Ship first; the moat is the verification-first implementation — gates before judges, physical worker/judge isolation |
| No contributors show up | The loop-contract schema is a standalone spec (RFC issues open now); schema adoption wins standards gravity even without the engine |
| Multi-cloud adapters too costly | Deferred; local + Temporal covers most of the durable-execution need |
| LLM costs make demos expensive | Dry-run mode + local models (Ollama) for development |
