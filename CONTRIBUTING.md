# Contributing to Wringer

Thanks for landing here this early. Wringer is **building toward
`v0.1.0` on September 30, 2026** — the ["One Loop" MVP](ROADMAP.md): a
GitHub issue in, a verified merge request with evidence out. The
[build plan](wringer-ai-dlc-harness-plan.md) is the architectural north
star; [ROADMAP.md](ROADMAP.md) governs execution order.

## What's valuable right now

- **The open RFCs.** Three abstractions are being locked down in public,
  as issues titled `RFC:` —
  [the loop-contract schema, the gate plugin interface, and the
  evidence-bundle format](https://github.com/marcoakes/wringer/issues?q=is%3Aissue+RFC).
  If you maintain or use LangGraph, Temporal, CrewAI, or Agent Framework,
  your prior art is exactly what these threads need. Comment before the
  schemas freeze.
- **Design review.** Read the plan and open an issue where you disagree —
  especially on the Graph IR node kinds (§4.1), the loop-contract schema
  (§4.2), and the conformance-suite behaviors (§6 Phase 5). Prior art and
  "this will break because…" reports are the highest-value contributions
  at this stage. This is not a lesser form of contribution here — it is
  the preferred one.
- **Landscape corrections.** §2 is a July 2026 snapshot of a fast-moving
  field. If a vendor surface, protocol, or price changed, file it.
- **Adapter interest.** If you'd want to own a runtime/gateway adapter
  (Temporal, AgentCore, Google, Foundry, Anthropic — or one we haven't
  listed), say so in an issue. Conformance-first: the suite is the
  contract, adapters are community-maintainable.

## Now that code exists

- **The gate is green tests.** Today that is `.venv/bin/pytest` (setup in
  [AGENTS.md](AGENTS.md#build-test-run)); from Bolt 5 onward it is
  `wring verify` on this repo, mirrored in CI. No PR merges red.
- Small, reviewable PRs; conventional commits; evidence in the PR
  description.
- Respect the package-boundary matrix (enforced by lint).
- AI-assisted contributions are welcome and expected — this project is
  built with the methodology it encodes. Follow
  [AGENTS.md](AGENTS.md).

## Governance

Apache-2.0 from day zero. A published governance charter, steering
committee, and foundation-donation path are Phase 7 deliverables (plan
§6/§11). Until then: issues and PRs, benevolent-maintainer mode, and
every decision recorded in the issue that made it.
