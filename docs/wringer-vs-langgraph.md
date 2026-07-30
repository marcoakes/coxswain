# Wringer vs LangGraph, CrewAI, and Microsoft Agent Framework — an honest comparison

If you want graph-orchestrated agents today, **use LangGraph or Microsoft
Agent Framework — they are mature, well-documented, and battle-tested.**
This page exists because "reinvented LangGraph" is the obvious critique of
Wringer, and the honest answer is: partly true, deliberately so, and the
differences are exactly the point.

## Where they are better (today, and probably for a while)

| | LangGraph | CrewAI | MS Agent Framework |
|---|---|---|---|
| Maturity & production mileage | ✅ extensive | ✅ large community | ✅ enterprise backing |
| Ecosystem, integrations, docs | ✅ LangChain gravity | ✅ easy on-ramp | ✅ Foundry/Azure native |
| Graph orchestration primitives | ✅ shipped years of it | role-based crews | ✅ workflows + AutoGen lineage |
| Checkpointing / state persistence | ✅ built in | partial | ✅ built in |
| Multi-agent patterns out of the box | ✅ | ✅ its whole thesis | ✅ |

If your need is "orchestrate LLM calls and tools in a graph, in Python,
with a big ecosystem" — stop reading, use LangGraph.

## Where Wringer is different by design

**1. Verification-first, not orchestration-first.** In Wringer,
deterministic gates (build / test / lint / custom linters) *always* run
before any LLM judge, and a loop cannot exit "done" without passing its
declared verifier. Orchestration frameworks let you build this; Wringer
refuses to work without it. The unit of progress is a *verified outcome*
(an MR with evidence), not a completed graph run.

**2. Physical worker/judge isolation.** The judge runs in a separate
context and receives the rubric, the diff, and the gate outputs — never
the worker's chain of reasoning. This is an engine guarantee with tests,
not a prompt-engineering convention. Judge-gaming via persuasive worker
output is treated as an attack surface.

**3. Loop contracts as declarative schema, not code.** Budgets
(`max_iterations`, `max_cost_usd`, `max_wall_clock`, `max_tokens`),
verifier ordering, and exit conditions (`on_budget_exhausted`,
`on_oscillation`, `on_plateau`) are YAML you can diff, review, and
enforce — portable across engines, not Python closures locked to one.
Anti-thrash (failure-signature hashing, plateau detection) is built into
the contract semantics.

**4. Evidence and cost as byproducts.** Every run emits an append-only
`evidence.jsonl` (intent → plan → iterations → gate reports → verdicts →
delivery) and a `cost.jsonl`, aligned to OpenTelemetry GenAI semantic
conventions. If you need to show an auditor *why* an AI-authored change
merged, that artifact — not a re-run — is the answer.

**5. Vendor-neutral IR.** The graph definition references capabilities,
never vendor resources. The same YAML is meant to run locally and on
durable runtimes (Temporal first; others by conformance suite). No
framework lock-in is a hard requirement, not a preference.

## The actual posture: targets, not competitors

LangGraph, ADK, and Agent Framework shipped graph orchestration before
"graph engineering" had a name — which is precisely why Wringer treats
them as **compile targets and peers**, not competitors. A
LangGraph-interop exporter is on the roadmap to make that concrete: bring
your LangGraph graph, wrap its nodes in loop contracts, get gates,
isolation, evidence, and cost governance around it.

## Use which, when

- **Prototyping multi-agent behavior, Python, fast** → CrewAI or LangGraph.
- **Deep Azure/Foundry estate** → Microsoft Agent Framework.
- **You've shipped agent code and been burned** — loops that thrash,
  "done" that wasn't, no audit trail, surprise token bills — and you want
  a ticket to become a *verified, evidenced, budgeted* merge request →
  that is the problem Wringer exists for.

*Corrections welcome — this page is honest or it is worthless. PRs and
issues against any claim here are treated as high-value contributions.*
