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
| README · [QUICKSTART.md](QUICKSTART.md) | landing pages — transcripts are now **real captured output**; if you change console or bundle shape, recapture them rather than editing the numbers by hand |
| [SECURITY.md](SECURITY.md) | the execution model (`.cox.yaml` is code), what a bundle may contain, reporting channel |

Where they disagree about v0.1, the spec wins.

## Current state — Bolt 3 shipped

There **is** code now: `cox init` and `cox verify` work — `verify` runs a
repo's whole declared gate set and writes a real bundle, `cox explain`
diagnoses a finished run, and `--json` feeds agents — with 125 tests
passing on Python 3.11–3.13 (plus macOS) in CI, behind a ruff lint gate.

| Bolt | Spec day | State |
|---|---|---|
| 1 — skeleton | Day 1 | ✅ packaging, config loader, `cox init`, `cox verify` running one gate, `evidence.jsonl` + `manifest.json`, exit codes 0/1/2 |
| 2 — gate runner | Day 2 | ✅ every gate in declared order, `timeout` enforced (process-group kill), stop-on-first-required-failure, optional-gate semantics, per-gate `gates/NNN_id/{stdout.log,stderr.log,result.json}`, `summary.md`, CI |
| 2.5 — review hardening | — | ✅ gate ids validated as slugs, internal git calls bounded, POSIX-only kill declared, ruff lint gate + macOS CI, real transcripts, SECURITY.md |
| 3 — git evidence | Day 3 | ✅ changed/untracked lists, `diff.patch`, `status.txt`, `git.status` event, timestamps on every event, `cox verify --json`, `cox explain` |
| 4 — redaction & safety | Day 4 | ⬜ next: env redaction before write, log truncation, binary exclusion, exit 3 preconditions, exit 4 on SIGINT |
| 5 — dogfood | Day 5 | ⬜ Coxswain verifies Coxswain, CI upgraded to run `cox verify` and upload the bundle, committed sanitized bundle in `.cox.example/`, real README transcript |

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
.venv/bin/pytest                # the gate: all tests, ~6s, must be green
.venv/bin/cox --help
.venv/bin/cox init              # writes .cox.yaml (refuses to overwrite)
.venv/bin/cox verify            # runs every gate, writes .cox/runs/<run_id>/
.venv/bin/cox verify --gate ID  # one gate, numbered as if the full run happened
.venv/bin/cox verify --json     # one object on stdout, no human report
.venv/bin/cox explain           # diagnose the latest run (no LLM)
```

**Two commands are the law until Bolt 5, when `cox verify` on this repo
becomes the gate:**

```bash
.venv/bin/ruff check src tests   # must be clean
.venv/bin/pytest                 # must be green
```

CI mirrors exactly those two:
[`.github/workflows/tests.yml`](.github/workflows/tests.yml) runs ruff
once and pytest on 3.11 / 3.12 / 3.13 plus macOS, for every push and PR.
Bolt 5 upgrades that workflow to run `cox verify` and upload the bundle —
and these two commands are the gates Coxswain's own `.cox.yaml` will
declare. Ruff config lives in `pyproject.toml` (`E,F,W,I,UP,B`,
line-length 88); there is still no `Makefile`, and any further dependency
is a decision to ask about.

Gate output is **captured, never teed**: streams go to the bundle's log
files, and only a failing required gate gets a 20-line tail on the
console. If you are tempted to add `--verbose`, read the spec's demo
block first — the clean console is the product.

## Module map (`src/cox/`)

| Module | Does | Deliberately does not (yet) |
|---|---|---|
| `cli.py` | argparse surface, subcommands, exit codes, the console report, `--json`, and `cox explain`'s rendering | register `--changed-only` or `--output` — see below |
| `config.py` | strict `.cox.yaml` loader → frozen `Config`/`Gate` dataclasses | consume `evidence:` (parsed for shape, stored raw for Bolts 3–4) |
| `detect.py` | the commented `.cox.yaml` template `cox init` writes | actually detect project commands (static template is Day-1-legal per the spec: *"if detection is uncertain, generate comments rather than being clever"*) |
| `git.py` | root detection, HEAD SHA, branch, dirty flag, changed/untracked lists, `diff`/`status` capture; read-only, bounded, never fatal | binary exclusion from the diff (Bolt 4) |
| `gates.py` | run one gate through the shell in the repo root: own process group, `timeout` enforced by SIGTERM→SIGKILL on the group, stdout/stderr captured to files, duration in ms | decide anything about *which* gates run — that is `cli.py`'s sequencing |
| `evidence.py` | allocate `.cox/runs/<run_id>/`, append timestamped `evidence.jsonl`, write `manifest.json`, `gates/NNN_id/` + `result.json`, capture files, and read a finished bundle back (`latest_run`, `read_*`) | redaction and size limits (Bolt 4) |
| `summary.py` | render `summary.md`: repo line, gate table with statuses and log links, the exact rerun command | anything an agent parses — machines read `evidence.jsonl` / `manifest.json` |

`redact.py` appears in the spec's layout and does **not** exist yet by
design — it arrives with Bolt 4.

### Do not add these early

The spec's [Non-goals](SPEC_COX_VERIFY_V0.md#non-goals-for-v010-binding)
are **binding**: no `cox run`, no LLM judge, no issue ingestion, no PR
creation, no Temporal, no OpenTelemetry, no multi-agent anything, no
sandboxing beyond recording repo state.

Also: a flag that half-works is worse than a missing flag, because agents
consume this CLI. `--changed-only` and `--output` stay **unregistered**.
`--changed-only` is deliberately deferred: the spec names it but never
defines it, and the plausible readings (skip a clean tree · scope gates to
changed files · limit what is captured) are different products. Pin the
semantics in the spec before building it.

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

Three conventions inside the bundle are load-bearing:

- **`gates/NNN_<id>/` numbering follows the *declared* order, not the run.**
  `cox verify --gate test` on a three-gate config still writes
  `gates/003_test/`, so a directory name means the same thing in a full
  run, a partial run and a single-gate run.
- **Every event carries `ts`** (local ISO-8601, milliseconds). The spec's
  example was amended in Bolt 3 to match; keep them in step.
- **`git.status` carries `untracked` only when there is something
  untracked**, so the common case stays exactly the spec's shape.
- **The git capture happens before the bundle directory exists**, or
  Coxswain's own `.cox/` would show up as an untracked file in its own
  evidence. Order matters in `cmd_verify`; do not reshuffle it.
- **A `log` field appears on `gate.finished` for failing gates only** —
  it is a pointer to where the reader is being sent, not an inventory
  (every gate's logs are on disk and linked from `summary.md`).
- **Skipped gates leave no trace in `evidence.jsonl` and no directory.**
  They were not run, so claiming otherwise would be a lie; `summary.md`
  is the one place the full declared set appears, marked `skipped`.

**Gate ids are slugs** (`[A-Za-z0-9][A-Za-z0-9_-]*`, ≤64 chars) because
they become directory names: `gates/NNN_<id>/`. A config saying
`id: ../../x` is a parse error, not a path traversal. Widening that
pattern means re-checking every place an id reaches the filesystem.

**v0.1 supports macOS and Linux.** Timeout enforcement needs process
groups (`os.killpg`), which is POSIX-only; `gates.py` degrades to killing
just the shell elsewhere and pyproject's classifiers say so. Windows is a
v0.2 conversation, not a silent failure.

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
3. **Tests come with the commit that needs them**, not later. The existing
   suite is the shape to match: contract assertions (event sequence,
   manifest and `result.json` fields, exit codes, `summary.md` rows),
   scratch-repo fixtures in [tests/conftest.py](tests/conftest.py), and no
   mocking of git or subprocess — a timeout test really spawns `sleep 30`
   and really kills it.
4. **Small conventional commits** — `feat:`, `fix:`, `test:`, `docs:`,
   `chore:`. Evidence in the PR description.
5. **Vendor strings behind mapping layers.** Any external API surface,
   protocol attribute, or vendor identifier goes behind the designated
   mapping module. Pin versions.
6. **Update this file** whenever build/test/run behavior, the module map,
   or the bolt state changes. It is the first thing the next agent reads.

## Repo-specific gotchas

- **The maintainer's Mac may have no git push credential** (no `gh`, no
  SSH keys, no Homebrew). Try `git push`; if it fails, commits queue
  locally and the maintainer pushes, or publishing happens through the
  browser against his logged-in GitHub session — his call, per bolt.
  Never work around it, never handle a token — surface the block and ask.
- **`.cox.yaml` is arbitrary code execution by design** — gates run
  through a shell with the user's privileges. Never add a feature that
  widens that (no fetching a config over the network, no running a gate
  from an untrusted source) without a spec change and a SECURITY.md
  update. Bundles hold raw gate output, so they are unredacted until
  Bolt 4: don't paste one into a public issue.
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
