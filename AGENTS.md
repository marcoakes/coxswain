# AGENTS.md

Guidance for AI agents (and humans) working in this repository. Coxswain
dogfoods its own principle: *the repo is the agent-experience surface.*

## What this repo is

Coxswain (`cox`) is an open-source, control-plane-agnostic AI-DLC harness:
it compiles intent (issues, PRDs, Slack messages) into verified outcomes
(reviewed MRs with evidence), using graphs of loop-bearing agents, portable
across local, Temporal, AWS AgentCore, Google Agent Engine, Microsoft
Foundry, and Anthropic Managed Agents runtimes.

**The plan of record is [`coxswain-ai-dlc-harness-plan.md`](coxswain-ai-dlc-harness-plan.md).**
Read it before proposing changes. §6 defines the phased execution plan;
Appendix A is the session bootstrap prompt.

## Current state

**Pre-Phase-0 (design phase).** There is no code yet — no build, no tests,
no `make verify`. The artifacts that exist:

- `README.md` — the public landing page
- `coxswain-ai-dlc-harness-plan.md` — the v1.0 build plan (plan of record)
- `LICENSE` — Apache-2.0
- `CONTRIBUTING.md`

Phase 0 (monorepo scaffold, `@cox/verify` MVP, boundary linter, CI) is the
next unit of work and its exit criteria are in the plan, §6 Phase 0.

## Operating rules (from the plan, §6 meta)

1. **AI-DLC discipline:** plan first, wait for human approval, execute in
   bolts (hours-to-days units of work).
2. **Never merge red.** Once Phase 0 lands, `make verify` (typecheck +
   lint + unit tests + build) is the universal gate. CI mirrors it.
3. **Package boundaries are law.** No package imports another's internals —
   interfaces only. A custom lint gate enforces the boundary matrix from
   Phase 0 onward.
4. **Small, reviewable PRs.** Conventional commits. Evidence in the PR
   description.
5. **Vendor strings behind mapping layers.** Any external API surface,
   protocol attribute, or vendor identifier goes behind the designated
   mapping module. Pin versions.
6. **Update this file** whenever build/test/lint behavior changes.

## Conventions

- TypeScript strict, Node 22, pnpm workspaces (from Phase 0).
- Apache-2.0; DCO sign-off not required at this stage.
- Docs in Markdown; diagrams as Mermaid or fenced ASCII (both render on
  GitHub).
