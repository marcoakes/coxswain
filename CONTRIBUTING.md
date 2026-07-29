# Contributing to Coxswain

Thanks for landing here this early. Coxswain is in its **design phase** —
the [v1.0 build plan](coxswain-ai-dlc-harness-plan.md) is published and
Phase 0 (scaffold + verification substrate) is the next unit of work.

## What's valuable right now

- **Design review.** Read the plan and open an issue where you disagree —
  especially on the Graph IR node kinds (§4.1), the loop-contract schema
  (§4.2), and the conformance-suite behaviors (§6 Phase 5). Prior art and
  "this will break because…" reports are the highest-value contributions
  at this stage.
- **Landscape corrections.** §2 is a July 2026 snapshot of a fast-moving
  field. If a vendor surface, protocol, or price changed, file it.
- **Adapter interest.** If you'd want to own a runtime/gateway adapter
  (Temporal, AgentCore, Google, Foundry, Anthropic — or one we haven't
  listed), say so in an issue. Conformance-first: the suite is the
  contract, adapters are community-maintainable.

## Once code exists (Phase 0+)

- `make verify` green is the only law. No PR merges red.
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
