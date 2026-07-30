# AGENTS.md

Guidance for AI agents (and humans) working in this repository. Coxswain
dogfoods its own principle: *the repo is the agent-experience surface.*

Read this file, then [SPEC_COX_VERIFY_V0.md](SPEC_COX_VERIFY_V0.md) end to
end. The spec is the binding contract for everything in `src/cox/`.

## What this repo is

Coxswain (`cox`) is an open-source, control-plane-agnostic AI-DLC harness:
it compiles intent (issues, PRDs, Slack messages) into verified outcomes
(reviewed MRs with evidence), using graphs of loop-bearing agents,
portable across local, Temporal, AWS AgentCore, Google Agent Engine,
Microsoft Foundry, and Anthropic Managed Agents runtimes.

**v0.1.0 ships one slice of that: `cox verify`, a standalone evidence
compiler.** One command that runs a repo's declared gates and leaves
behind an evidence bundle a human or an agent can inspect. No LLM calls,
no network, no uploads — ever.

### Document hierarchy

| Document | Authority |
|---|---|
| [SPEC_COX_VERIFY_V0.md](SPEC_COX_VERIFY_V0.md) | **binding** for v0.1 implementation — CLI surface, exit codes, bundle format, build order, release bar |
| [ROADMAP.md](ROADMAP.md) | execution order (90-day compression) |
| [coxswain-ai-dlc-harness-plan.md](coxswain-ai-dlc-harness-plan.md) | architectural north star (post-v0.1) |
| README · [QUICKSTART.md](QUICKSTART.md) | landing pages — both still carry **aspirational** transcripts that the spec's release bar requires be replaced with real ones before `v0.1.0` tags |

Where they disagree about v0.1, the spec wins.

## Current state — Bolt 1 shipped

There **is** code now: `cox init` and `cox verify` work, 58 tests pass.

| Bolt | Spec day | State |
|---|---|---|
| 1 — skeleton | Day 1 | ✅ packaging, config loader, `cox init`, `cox verify` running **one** gate, `evidence.jsonl` + `manifest.json`, exit codes 0/1/2 |
| 2 — gate runner | Day 2 | ⬜ next: all gates in order, `timeout` enforcement, stop-on-first-required-failure, per-gate `gates/NNN_id/` logs, `summary.md`, full exit-code table |
| 3 — git evidence | Day 3 | ⬜ changed files, `diff.patch`, `status.txt`, untracked list, `--changed-only`, `--json`, `cox explain` |
| 4 — redaction & safety | Day 4 | ⬜ env redaction before write, log truncation, binary exclusion, exit 3 preconditions, exit 4 on SIGINT |
| 5 — dogfood | Day 5 | ⬜ Coxswain verifies Coxswain, CI workflow, committed sanitized bundle in `.cox.example/`, real README transcript |

The `v0.1.0` tag is gated on the spec's
[Definition of PROVEN](SPEC_COX_VERIFY_V0.md#definition-of-proven--the-repo-must-show-its-own-receipts),
not on the code compiling.

## Build, test, run

Python **3.11+**. Dependencies: PyYAML at runtime, pytest for dev —
nothing else without asking.

```bash
python3 -m venv .venv                          # any Python 3.11+
.venv/bin/python -m pip install -e '.[dev]'
```

With [uv](https://docs.astral.sh/uv/) instead (what the maintainer's Mac
uses — its `.venv` is uv-made and has **no pip**, so use `uv pip`):

```bash
export PATH="$HOME/.local/bin:$PATH"
uv venv --python 3.12
uv pip install -e '.[dev]' --python .venv/bin/python
```

Then:

```bash
.venv/bin/pytest                # the gate: all tests, ~2s, must be green
.venv/bin/cox --help
.venv/bin/cox init              # writes .cox.yaml (refuses to overwrite)
.venv/bin/cox verify            # runs a gate, writes .cox/runs/<run_id>/
```

**`.venv/bin/pytest` green is the law until Bolt 5, when `cox verify` on
this repo becomes the gate and CI mirrors it.** There is no `Makefile`
and no lint gate yet — adding `ruff` is a dependency decision, so ask.

## Module map (`src/cox/`)

| Module | Does | Deliberately does not (yet) |
|---|---|---|
| `cli.py` | argparse surface, subcommands, exit codes, console report | register `--json`, `--changed-only`, `--output`, `cox explain` |
| `config.py` | strict `.cox.yaml` loader → frozen `Config`/`Gate` dataclasses | consume `evidence:` (parsed for shape, stored raw for Bolts 3–4) |
| `detect.py` | the commented `.cox.yaml` template `cox init` writes | actually detect project commands (static template is Day-1-legal per the spec: *"if detection is uncertain, generate comments rather than being clever"*) |
| `git.py` | repo root detection, HEAD SHA, branch, dirty flag; read-only, never fatal | changed files, `diff.patch`, `status.txt` (Bolt 3) |
| `gates.py` | run one gate through the shell in the repo root, time it | capture per-gate logs, enforce `timeout`, sequence gates (Bolt 2) |
| `evidence.py` | allocate `.cox/runs/<run_id>/`, append `evidence.jsonl`, write `manifest.json` | `summary.md`, `diff.patch`, `gates/NNN_id/` (Bolts 2–3) |

`redact.py` and `summary.py` appear in the spec's layout and do **not**
exist yet by design — they arrive with Bolts 4 and 2.

### Do not add these early

The spec's [Non-goals](SPEC_COX_VERIFY_V0.md#non-goals-for-v010-binding)
are **binding**: no `cox run`, no LLM judge, no issue ingestion, no PR
creation, no Temporal, no OpenTelemetry, no multi-agent anything, no
sandboxing beyond recording repo state.

Also: a flag that half-works is worse than a missing flag, because agents
consume this CLI. `--json`, `--changed-only`, `--output` and `cox explain`
stay **unregistered** until their bolt lands.

## Contracts you must not break

**Exit codes** (spec table — 0/1/2 are wired, 3/4 are reserved for Bolt 4):

| code | meaning |
|---|---|
| 0 | all required gates passed |
| 1 | a required gate failed |
| 2 | config or environment error |
| 3 | unsafe dirty state / refused precondition |
| 4 | interrupted |

**The evidence bundle is the product** — boring, stable, grep-friendly,
and the interface future judges and agents consume ([RFC #2](https://github.com/marcoakes/coxswain/issues/2)).
`manifest.json` carries `"schema_version": "cox.evidence.v1"`;
`evidence.jsonl` is append-only, one JSON object per line, `type` first.
Changing either shape is a spec change, not an implementation detail —
bump the schema version and say so in the commit.

**Config semantics:** validation is strict — unknown keys are errors,
because a typo in a gate definition must not silently change what
"verified" means. `optional` is the canonical field; `required` is
accepted as its negation (the spec spells it both ways); both together
is an error.

**Bundle location:** `.cox/` is gitignored — real runs stay local
(nothing uploads, ever). The one committed bundle lives in
`.cox.example/runs/…` and is sanitized by hand.

## Operating rules

1. **AI-DLC discipline.** One bolt at a time: short plan → maintainer's
   approval → execute → verify → commit → report → pause. Do not start
   the next bolt on your own initiative.
2. **Never claim a bolt done unless its checks actually ran.** Paste the
   real command output — `pytest` summary and a `cox` transcript — into
   the report. Fabricated or "should work" output is the one unforgivable
   sin in a repo whose entire product is evidence.
3. **Tests come with the commit that needs them**, not later. Bolt 1's
   suite is the shape to match: contract assertions (event sequence,
   manifest fields, exit codes), scratch-repo fixtures in
   [tests/conftest.py](tests/conftest.py), no mocking of git or
   subprocess.
4. **Small conventional commits** — `feat:`, `fix:`, `test:`, `docs:`,
   `chore:`. Evidence in the PR description.
5. **Vendor strings behind mapping layers.** Any external API surface,
   protocol attribute, or vendor identifier goes behind the designated
   mapping module. Pin versions.
6. **Update this file** whenever build/test/run behavior, the module map,
   or the bolt state changes. It is the first thing the next agent reads.

## Repo-specific gotchas

- **The maintainer's Mac has no git push credential** (no `gh`, no SSH
  keys, no keychain entry) and no Homebrew. Commits queue locally; the
  maintainer pushes, or publishing happens through the browser against
  his logged-in GitHub session. Never work around it, never handle a
  token — surface the block and ask.
- **Don't run `cox verify` on this repo casually while iterating** — each
  run writes a new `.cox/runs/<id>/`. Harmless (gitignored), just noisy.
- **Test repos must be isolated from the developer's git config.**
  `tests/conftest.py` pins `user.name`, `user.email` and
  `commit.gpgsign=false` for exactly this reason.
- Unicode `✓`/`✗` in console output is intentional (it is the spec's demo
  shape). Keep the report format aligned with the spec, and update the
  spec first if it must change.

## Conventions

- Python 3.11+, `src/` layout, `from __future__ import annotations`,
  frozen dataclasses for value types, argparse for the CLI, no third-party
  deps beyond PyYAML.
- Comments explain *why*, especially where a spec ruling is non-obvious;
  they do not narrate *what*.
- Apache-2.0; DCO sign-off not required at this stage.
- Docs in Markdown; diagrams as Mermaid or fenced ASCII (both render on
  GitHub).
- The TypeScript monorepo (Node 22, pnpm workspaces, package-boundary
  lint matrix) remains the plan's shape for the **later graph engine** —
  revisit at v0.2. It does not apply to v0.1's Python code.
