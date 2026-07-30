# SPEC — `cox verify` v0.1.0, the standalone evidence compiler

*Adopted 2026-07-30 (third external review). This is the **binding
implementation contract** for v0.1.0. It supersedes the Days 1–30 detail
in [ROADMAP.md](ROADMAP.md) where they differ. The implementing agent
builds THIS, in the build order below, and nothing in [Non-goals](#non-goals-for-v010-binding).*

## Positioning

> **One command that proves whether this change is mergeable, and leaves
> behind evidence a human or agent can inspect.**

`cox verify` ships **before** `cox run`, before the graph IR, before
judges, before Temporal, before any agent integration. It is not "the
verifier inside Coxswain" — it is a standalone evidence compiler that
happens to become Coxswain's foundation. After an AI coding session,
`cox verify` gives a cleaner, more reviewable truth trail than the
agent's own summary. Once that lands, `cox run` becomes obvious: a loop
that keeps calling `cox verify` until the evidence says stop.

## The one job

```
input:  repo + config + current git state
action: run gates in order
output: .cox/runs/<run_id>/
        manifest.json
        evidence.jsonl
        summary.md
        diff.patch
        status.txt
        gates/<NNN>_<id>/{stdout.log, stderr.log, result.json}
```

## CLI surface

### `cox init`

Detects common project commands and writes `.cox.yaml`. If detection is
uncertain, **generate comments rather than being clever**.

```yaml
version: 1
gates:
  - id: format
    run: make format-check
    optional: true
  - id: lint
    run: make lint
  - id: test
    run: make test
evidence:
  include:
    - git.diff
    - git.status
    - env
    - logs
```

### `cox verify`

Runs gates, writes the evidence bundle.

```bash
cox verify
cox verify --changed-only
cox verify --json
cox verify --output .cox/runs/manual-001
cox verify --gate test
```

**Exit codes are contract:**

| code | meaning |
|---|---|
| 0 | all required gates passed |
| 1 | a required gate failed |
| 2 | config or environment error |
| 3 | unsafe dirty state / refused precondition |
| 4 | interrupted |

`cox verify --json` emits structured back-pressure for agents (Claude
Code, Codex CLI, Gemini CLI — they need structure, not prose):

```json
{
  "status": "failed",
  "failed_gate": "test",
  "rerun": "cox verify --gate test",
  "evidence_dir": ".cox/runs/20260730-080601-a13f"
}
```

### `cox explain`

Reads the latest (or named) failed run and gives a compact diagnosis —
**non-LLM in v0**: failing gate, command, exit code, last useful log
lines, changed files, and the exact rerun command.

```bash
cox explain
cox explain .cox/runs/2026-07-30T080601Z
```

## The evidence bundle (this is the product)

Boring, stable, grep-friendly. This format is the interface future
agents and judges consume — see [RFC #2](https://github.com/marcoakes/coxswain/issues/2).

```
.cox/runs/20260730-080601-a13f/
  manifest.json
  evidence.jsonl
  summary.md
  diff.patch
  status.txt
  gates/
    001_lint/
      stdout.log
      stderr.log
      result.json
    002_test/
      stdout.log
      stderr.log
      result.json
```

`evidence.jsonl` — append-only, one JSON object per line:

```json
{"type":"run.started","run_id":"20260730-080601-a13f","cox_version":"0.1.0","repo":"coxswain","sha":"abc123"}
{"type":"git.status","dirty":true,"changed_files":["src/foo.py","tests/test_foo.py"]}
{"type":"gate.started","gate_id":"lint","command":"make lint"}
{"type":"gate.finished","gate_id":"lint","exit_code":0,"duration_ms":1842}
{"type":"gate.started","gate_id":"test","command":"make test"}
{"type":"gate.finished","gate_id":"test","exit_code":1,"duration_ms":9231,"log":"gates/002_test/stdout.log"}
{"type":"run.finished","status":"failed","failed_gate":"test"}
```

`manifest.json`:

```json
{
  "schema_version": "cox.evidence.v1",
  "run_id": "20260730-080601-a13f",
  "started_at": "2026-07-30T08:06:01+01:00",
  "repo": {
    "root": ".",
    "head_sha": "abc123",
    "branch": "main",
    "dirty": true
  },
  "result": {
    "status": "failed",
    "failed_gate": "test"
  }
}
```

## Config design (keep it tiny)

```yaml
version: 1

gates:
  - id: lint
    run: make lint
    timeout: 120
    required: true

  - id: test
    run: make test
    timeout: 300
    required: true

evidence:
  redact:
    env:
      - "*TOKEN*"
      - "*SECRET*"
      - "*KEY*"
```

**Rules (binding):**

1. Gates run cheapest first.
2. Stop on first required failure by default.
3. Optional gates record failure but do not fail the run.
4. Every command gets stdout, stderr, exit code, duration, timeout status.
5. Secrets are redacted **before** writing evidence.
6. Nothing uploads anywhere. Ever.

## Why this beats `make test`

1. **Evidence, not just pass/fail** — what was checked, what changed,
   what passed, what failed, where the logs are, what commit and
   environment produced it.
2. **Gate contracts** — the project declares what "done" means (this is
   the embryo of the later loop contract).
3. **Agent-readable output** — `--json` is structured back-pressure any
   coding agent can consume.

## Implementation stack

**Python 3.11+** for v0 (third-review ruling: ubiquitous, inspectable,
easy to package, right audience; `pipx install coxswain`). Keep
dependencies minimal — **argparse + dataclasses preferred**; add PyYAML
for config; nothing else without cause. The TypeScript monorepo remains
the plan's shape for the later graph engine — revisit at v0.2.

```
coxswain/
  pyproject.toml
  src/cox/
    __main__.py
    cli.py
    config.py
    detect.py
    git.py
    gates.py
    evidence.py
    redact.py
    summary.py
  tests/
    fixtures/
```

## Build order (bolts — plan first, verify each before the next)

- **Day 1 — skeleton:** `cox --help`, `cox init`, `cox verify` with
  hardcoded config support, one gate, writes `evidence.jsonl`.
- **Day 2 — gate runner:** multiple gates, timeouts, stop-on-failure,
  stdout/stderr logs, exit codes, `summary.md`.
- **Day 3 — git evidence:** root detection, branch, HEAD SHA, dirty
  status, changed files, `diff.patch`, untracked list.
- **Day 4 — redaction & safety:** env redaction patterns, max log size,
  binary exclusion, safe failure outside a git repo.
- **Day 5 — dogfood:** Coxswain verifies Coxswain. Commit a sanitized
  demo bundle (`.cox.example/runs/...`). Wire CI to run `cox verify`.

## Definition of PROVEN — the repo must show its own receipts

**Do not tag `v0.1.0` until every line is true:**

- [ ] `pipx install coxswain` works
- [ ] `cox init` works in an empty-ish Python repo
- [ ] `cox verify` runs at least two gates
- [ ] failed gates produce useful logs
- [ ] evidence bundle format is stable and documented
- [ ] **CI runs `cox verify` on this repo** (GitHub Actions example shipped)
- [ ] **Coxswain itself uses `cox verify`** — a sanitized demo bundle is
      committed so the repo carries proof of its own verification
- [ ] README shows a **real transcript**, not aspirational syntax

The README demo at that point:

```
$ cox verify
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

## Non-goals for v0.1.0 (binding)

`cox run` · LLM judge · GitHub issue ingestion · PR creation · Temporal ·
OpenTelemetry · multi-agent anything · cost tracking beyond an optional
empty `cost.jsonl` placeholder · sandboxing beyond "record current repo
state". All valuable; all after the first trust moment.

## First public benchmark (post-v0.1)

Benchmark against messiness, not against LangGraph: does a coding agent
fix a bug faster given `cox verify --json` output; does a maintainer
review an AI PR faster with evidence attached; can repeated failures be
grouped by signature. Three demo repos suffice: pytest package,
npm-test package, generic make repo.

---

## Appendix — session bootstrap for the implementing agent

Paste at the start of the implementation session:

> You are implementing **Coxswain v0.1.0** per `SPEC_COX_VERIFY_V0.md` in
> `~/Claude/coxswain` (github.com/marcoakes/coxswain). Read `AGENTS.md`,
> then the spec end to end, then `ROADMAP.md`. Rules: (1) AI-DLC — plan
> the current Day-bolt first, wait for approval, then execute. (2) Build
> order = the spec's Day 1–5; do not skip ahead. (3) The spec's non-goals
> are binding — no `cox run`, no LLM calls, no PR machinery. (4) Python
> 3.11+, argparse + dataclasses, PyYAML only; `pyproject.toml`, `src/cox/`
> layout, pytest. (5) Small conventional commits; never claim a bolt done
> unless its checks actually ran. (6) The finish line is the spec's
> "Definition of PROVEN" — Coxswain verifies Coxswain, CI runs it, the
> committed demo bundle and README transcript are real. Confirm the
> current day's exit criteria before proposing its plan.
