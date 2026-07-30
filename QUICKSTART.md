# Quickstart

> ⚠️ **Aspirational until `v0.1.0` tags** — and by the
> [spec's own release bar](SPEC_COX_VERIFY_V0.md#definition-of-proven--the-repo-must-show-its-own-receipts),
> this page must become a **real transcript** before that tag happens.
> Published now so the target is public and the design is held to it.

## One command, and the receipts

```bash
# install (Python 3.11+)
pipx install coxswain

# initialize: detects your build/test/lint commands, writes .cox.yaml
cd my-repo
cox init

# run the gates, capture the evidence
cox verify
```

Output:

```
✓ git status captured
✓ diff captured
✓ lint passed        1.8s
✗ test failed        9.2s

Evidence written to:
.cox/runs/20260730-080601-a13f/

Next:
  open .cox/runs/20260730-080601-a13f/summary.md
  rerun cox verify --gate test
```

What's in the bundle: `manifest.json`, `evidence.jsonl` (append-only
event log), `summary.md`, `diff.patch`, per-gate stdout/stderr logs —
what was checked, what changed, what passed, what failed, and what
commit and environment produced it. See the
[full format](SPEC_COX_VERIFY_V0.md#the-evidence-bundle-this-is-the-product).

## For agents

```bash
# structured back-pressure instead of prose — Claude Code, Codex CLI,
# and Gemini CLI can act on this directly
cox verify --json
```

```json
{
  "status": "failed",
  "failed_gate": "test",
  "rerun": "cox verify --gate test",
  "evidence_dir": ".cox/runs/20260730-080601-a13f"
}
```

```bash
# compact diagnosis of the latest failed run (no LLM involved)
cox explain
```

## What it will NOT do

Write code (the harness never writes code — agents do), call any LLM,
open PRs, replace your CI, upload anything anywhere, or require any
cloud. That's `cox run` and later — see the [roadmap](ROADMAP.md) and
the [v0 spec](SPEC_COX_VERIFY_V0.md).
