# Quickstart

> ⚠️ **Aspirational.** This is the developer experience `v0.1.0` ships on
> **September 30, 2026** ([roadmap](ROADMAP.md)). It is published now so the
> target is public and the design is held to it. Nothing below installs yet.

## Issue → verified MR in five minutes

```bash
# install the CLI (Node 22+)
npm install -g coxswain

# initialize a repo: detects build/test/lint commands, writes coxswain.yaml
cd my-repo
cox init

# point it at an issue — Coxswain runs a repair loop in a local sandbox:
# worker writes code → gates run (build, test, lint) → judge scores the
# diff against the issue's acceptance criteria → iterate or exit
cox run --issue https://github.com/you/my-repo/issues/42

# output: a branch, an open MR, and the receipts
cox evidence open <run-id>
```

What you get with the MR:

- **`evidence.jsonl`** — every iteration: the gate reports, the judge's
  structured verdict, the diffs.
- **`cost.jsonl`** — tokens and spend, per loop, per run.
- A loop that **cannot thrash**: budgets (`max_iterations`, `max_cost_usd`,
  `max_wall_clock`) and oscillation detection are in the loop contract,
  not in your hope.

## Cheap mode

```bash
# gates run for real; the judge is a deterministic rubric — zero LLM spend
cox run --issue <url> --dry-run

# or point the judge at a local model
cox run --issue <url> --judge-endpoint http://localhost:11434/v1
```

## What it will NOT do

Write code itself (the harness never writes code — agents do), replace
your CI, or require any cloud. Local first; [Temporal for durability in
Q4](ROADMAP.md#okrs).
