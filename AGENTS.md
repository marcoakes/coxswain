# AGENTS.md

Guidance for AI agents (and humans) working in this repository. Wringer
dogfoods its own principle: *the repo is the agent-experience surface.*

Read this file, then [SPEC_VERIFY_V0.md](SPEC_VERIFY_V0.md) end to
end. The spec is the binding contract for everything in `src/wringer/`.

## What this repo is

Wringer (`wring`) is an open-source, control-plane-agnostic AI-DLC harness:
it compiles intent (issues, PRDs, Slack messages) into verified outcomes
(reviewed MRs with evidence), using graphs of loop-bearing agents,
portable across local, Temporal, AWS AgentCore, Google Agent Engine,
Microsoft Foundry, and Anthropic Managed Agents runtimes.

**v0.1.0 ships one slice of that: `wring verify`, a standalone evidence
compiler.** One command that runs a repo's declared gates and leaves
behind an evidence bundle a human or an agent can inspect. No LLM calls,
no network, no uploads — ever.

### Document hierarchy

| Document | Authority |
|---|---|
| [SPEC_VERIFY_V0.md](SPEC_VERIFY_V0.md) | **binding** for v0.1 implementation — CLI surface, exit codes, bundle format, build order, release bar |
| [SPEC_RUN_V0.md](SPEC_RUN_V0.md) | **binding** for v0.2 slice 1 — `wring run`, the `run:` config section, the loop's rulings and `wringer.loop.v1` |
| [ROADMAP.md](ROADMAP.md) | execution order (90-day compression) |
| [wringer-ai-dlc-harness-plan.md](wringer-ai-dlc-harness-plan.md) | architectural north star (post-v0.1) |
| README · [QUICKSTART.md](QUICKSTART.md) | landing pages — transcripts are now **real captured output**; if you change console or bundle shape, recapture them rather than editing the numbers by hand |
| [examples/claude-code-hook/](examples/claude-code-hook/) | the agent loop as a Claude Code `PostToolUse` hook — an *example*, not part of the package; it ships no code into `src/` and adds no dependency |
| [SECURITY.md](SECURITY.md) | the execution model (`.wringer.yaml` is code), what a bundle may contain, reporting channel |

Where they disagree about v0.1, the spec wins.

## Current state — every bolt shipped; one line from the tag

There **is** code now: `wring init` and `wring verify` work — `verify` runs a
repo's whole declared gate set and writes a real bundle, `wring explain`
diagnoses a finished run, `--json` feeds agents, and secrets never reach the
disk — with 233 tests passing on Python 3.11–3.13 (plus macOS) in CI.
On the `run-v0.2` branch, `wring run` closes the loop around all of it.

**Wringer now verifies Wringer**: [`.wringer.yaml`](.wringer.yaml) declares
this repo's own gates, CI runs `wring verify` and uploads the bundle, and a
real one is committed at [`.wringer.example/`](.wringer.example/). The only
unticked line on the spec's release bar is the PyPI publish, which is the
maintainer's to do.

| Bolt | Spec day | State |
|---|---|---|
| 1 — skeleton | Day 1 | ✅ packaging, config loader, `wring init`, `wring verify` running one gate, `evidence.jsonl` + `manifest.json`, exit codes 0/1/2 |
| 2 — gate runner | Day 2 | ✅ every gate in declared order, `timeout` enforced (process-group kill), stop-on-first-required-failure, optional-gate semantics, per-gate `gates/NNN_id/{stdout.log,stderr.log,result.json}`, `summary.md`, CI |
| 2.5 — review hardening | — | ✅ gate ids validated as slugs, internal git calls bounded, POSIX-only kill declared, ruff lint gate + macOS CI, real transcripts, SECURITY.md |
| 3 — git evidence | Day 3 | ✅ changed/untracked lists, `diff.patch`, `status.txt`, `git.status` event, timestamps on every event, `wring verify --json`, `wring explain` |
| 4 — redaction & safety | Day 4 | ✅ env redaction before write, capped logs with a declared note, binary + textconv exclusion, exit 2 outside a repo, exit 3 mid-merge/rebase, exit 4 on SIGINT with the gate killed |
| 5 — dogfood | Day 5 | ✅ `wring init` detects real commands (pyproject / package.json / Makefile) and gitignores `.wringer/`, `wring verify --output`, Wringer's own `.wringer.yaml`, CI runs `wring verify` + uploads the bundle, committed bundle in `.wringer.example/` |
| v0.2 slice 1 — the loop | — | ✅ `wring run`: `run:` config, verify→brief→worker→verify, plateau fingerprint, `wringer.loop.v1` bundle, loop schemas ([SPEC_RUN_V0.md](SPEC_RUN_V0.md)) |
| 5.5 — pre-publish hardening | — | ✅ interrupted runs named in `summary.md` and diagnosed by `explain`, `latest_run` ordered by time not name, reused `--output` cleared before writing, post-kill drain bounded, event lists scrubbed, `evidence.include` shape-checked |

The `v0.1.0` tag is gated on the spec's
[Definition of PROVEN](SPEC_VERIFY_V0.md#definition-of-proven--the-repo-must-show-its-own-receipts),
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
.venv/bin/pytest                # the gate: all tests, ~10s, must be green
.venv/bin/wring --help
.venv/bin/wring init              # writes .wringer.yaml (refuses to overwrite)
.venv/bin/wring verify            # runs every gate, writes .wringer/runs/<run_id>/
.venv/bin/wring verify --gate ID  # one gate, numbered as if the full run happened
.venv/bin/wring verify --json     # one object on stdout, no human report
.venv/bin/wring explain           # diagnose the latest run (no LLM)
```

**`wring verify` on this repo is the law** — it runs the two gates
[`.wringer.yaml`](.wringer.yaml) declares, which are exactly:

```bash
.venv/bin/ruff check src tests examples   # must be clean
.venv/bin/pytest                 # must be green
```

Run them however you like, but `wring verify` is what CI runs and what the
committed bundle proves. Gates inherit your `PATH`, so the venv has to be on
it (`export PATH="$PWD/.venv/bin:$PATH"`) or `ruff` will not be found — the
same rule as any `Makefile`.

CI mirrors exactly this:
[`.github/workflows/tests.yml`](.github/workflows/tests.yml) runs ruff
once and pytest on 3.11 / 3.12 / 3.13 plus macOS, for every push and PR.
Bolt 5 upgrades that workflow to run `wring verify` and upload the bundle —
and these two commands are the gates Wringer's own `.wringer.yaml` will
declare. Ruff config lives in `pyproject.toml` (`E,F,W,I,UP,B`,
line-length 88); there is still no `Makefile`, and any further dependency
is a decision to ask about.

Gate output is **captured, never teed**: streams go to the bundle's log
files, and only a failing required gate gets a 20-line tail on the
console. If you are tempted to add `--verbose`, read the spec's demo
block first — the clean console is the product.

## Module map (`src/wringer/`)

| Module | Does | Deliberately does not (yet) |
|---|---|---|
| `cli.py` | argparse surface, subcommands, exit codes, the console report, `--json`, `--output`, and `wring explain`'s rendering | register `--changed-only` — see below |
| `config.py` | strict `.wringer.yaml` loader → frozen `Config`/`Gate` dataclasses; validates `evidence.redact` because a typo there must not silently disable redaction | consume `evidence.include` (still shape-only) |
| `detect.py` | find the commands a repo already declares — ruff/mypy/pytest in `pyproject.toml`, npm scripts, Makefile targets — and render `.wringer.yaml`; fall back to a commented template when nothing is found | invent a command nobody wrote down (*"if detection is uncertain, generate comments rather than being clever"*) |
| `git.py` | root detection, HEAD SHA, branch, dirty flag, changed/untracked lists, `diff`/`status` capture, and the refusal checks (`is_repo`, `in_progress`); read-only, bounded, never fatal | write anything — every call here is a read |
| `gates.py` | run one gate through the shell in the repo root: own process group, `timeout` enforced by SIGTERM→SIGKILL on the group, output captured **through a pipe** so it can be scrubbed and capped before it is written, duration in ms | decide anything about *which* gates run — that is `cli.py`'s sequencing |
| `evidence.py` | allocate `.wringer/runs/<run_id>/`, append timestamped `evidence.jsonl`, write `manifest.json`, `gates/NNN_id/` + `result.json`, capture files, and read a finished bundle back (`latest_run`, `read_*`) — scrubbing every write, because the `Bundle` holds the redactor | decide *what* counts as a secret — that is `redact.py` |
| `redact.py` | turn env-var name patterns into the set of secret values, and erase them from text or bytes | look anywhere but the environment |
| `summary.py` | render `summary.md`: repo line, gate table with statuses and log links, the exact rerun command | anything an agent parses — machines read `evidence.jsonl` / `manifest.json` |
| `verify.py` | one verification as a **callable**: snapshot git, open a bundle, run the planned gates, stop on the first required failure, write manifest + summary, return an `Outcome`. Also `plan()` and the `--json` shape both commands share | print anything, or decide an exit code — that is `cli.py`'s |
| `loop.py` | v0.2's `wring run`: verify → brief → worker → verify, the plateau fingerprint, and the `wringer.loop.v1` bundle under `.wringer/loops/` | call an LLM, touch git, or nest a verify bundle inside a loop bundle (runs are referenced by path) |

Every module in the spec's layout now exists.

### Do not add these early

v0.1's [Non-goals](SPEC_VERIFY_V0.md#non-goals-for-v010-binding) still bind
everything under `wring verify`. `wring run` now exists, but only the slice
[SPEC_RUN_V0.md](SPEC_RUN_V0.md) defines: still **no LLM judge, no issue
ingestion, no PR creation, no commits or pushes, no Temporal, no
OpenTelemetry, no multi-agent anything**, and no anti-thrash beyond the
plateau fingerprint. Wringer itself makes **no LLM call and no network call**
— the worker is the user's own program, and every worker in the test suite is
a shell one-liner.

Also: a flag that half-works is worse than a missing flag, because agents
consume this CLI. `--changed-only` stays **unregistered**.
`--changed-only` is deliberately deferred: the spec names it but never
defines it, and the plausible readings (skip a clean tree · scope gates to
changed files · limit what is captured) are different products. Pin the
semantics in the spec before building it.

## Contracts you must not break

**Exit codes** (the spec's table — all five are live now):

| code | meaning |
|---|---|
| 0 | all required gates passed |
| 1 | a required gate failed |
| 2 | config or environment error |
| 3 | unsafe dirty state / refused precondition |
| 4 | interrupted |

**The evidence bundle is the product** — boring, stable, grep-friendly,
and the interface future judges and agents consume ([RFC #2](https://github.com/marcoakes/wringer/issues/2)).
`manifest.json` carries `"schema_version": "wringer.evidence.v1"`;
`evidence.jsonl` is append-only, one JSON object per line, `type` first.
Changing either shape is a spec change, not an implementation detail —
bump the schema version and say so in the commit.

That shape is now **published as JSON Schema** in [`schema/`](schema/), and
[tests/test_schema.py](tests/test_schema.py) fails if the code writes a key
the schema does not declare. Adding a field therefore means editing the
schema in the same commit — which is the point: the version string is what a
new field costs.

Three conventions inside the bundle are load-bearing:

- **`gates/NNN_<id>/` numbering follows the *declared* order, not the run.**
  `wring verify --gate test` on a three-gate config still writes
  `gates/003_test/`, so a directory name means the same thing in a full
  run, a partial run and a single-gate run.
- **Every event carries `ts`** (local ISO-8601, milliseconds). The spec's
  example was amended in Bolt 3 to match; keep them in step.
- **`git.status` carries `untracked` only when there is something
  untracked**, so the common case stays exactly the spec's shape.
- **The git capture happens before the bundle directory exists**, or
  Wringer's own `.wringer/` would show up as an untracked file in its own
  evidence. Order matters in `cmd_verify`; do not reshuffle it.
- **A `log` field appears on `gate.finished` for failing gates only** —
  it is a pointer to where the reader is being sent, not an inventory
  (every gate's logs are on disk and linked from `summary.md`).
- **Skipped gates leave no trace in `evidence.jsonl` and no directory.**
  They were not run, so claiming otherwise would be a lie; `summary.md`
  is the one place the full declared set appears, marked `skipped` — or
  `interrupted` for the one gate a Ctrl-C caught mid-flight, which is
  neither passed nor skipped and still gets no invented `gate.finished`.
- **One directory describes one run.** `--output` reuses the directory it
  is given, so `Bundle.at` first clears the previous bundle (`evidence.jsonl`,
  `manifest.json`, `summary.md`, `diff.patch`, `status.txt`, `gates/`) and
  nothing else — the directory is the caller's. Leaving a stale
  `gates/NNN_id/result.json` behind is how a bundle comes to say a gate
  passed on the same screen its summary calls it skipped.
- **`latest_run` orders by time, never by name.** A `--output` directory can
  be called anything, and as text `manual-001` outranks every real run id
  forever. Ids are dated from their timestamp prefix, other names from their
  mtime.

**Gate ids are slugs** (`[A-Za-z0-9][A-Za-z0-9_-]*`, ≤64 chars) because
they become directory names: `gates/NNN_<id>/`. A config saying
`id: ../../x` is a parse error, not a path traversal. Widening that
pattern means re-checking every place an id reaches the filesystem.

**v0.1 supports macOS and Linux.** Timeout enforcement needs process
groups (`os.killpg`), which is POSIX-only; `gates.py` degrades to killing
just the shell elsewhere and pyproject's classifiers say so. Windows is a
v0.2 conversation, not a silent failure.

**Redaction happens before the write, never after.** The `Bundle` owns a
`Redactor` so every write path scrubs by construction; gate output travels
through a pipe for the same reason. If you add a file to the bundle, add it
through the `Bundle`, or you have quietly opted out of the one guarantee
SECURITY.md makes. Scrub first, *then* truncate — truncation must never be
what saves a secret.

**Config semantics:** validation is strict — unknown keys are errors,
because a typo in a gate definition must not silently change what
"verified" means. `optional` is the canonical field; `required` is
accepted as its negation (the spec spells it both ways); both together
is an error.

**Bundle location:** `.wringer/` is gitignored — real runs stay local
(nothing uploads, ever). The one committed bundle lives in
`.wringer.example/runs/…` and is sanitized by hand.

## Operating rules

1. **AI-DLC discipline.** One bolt at a time: short plan → maintainer's
   approval → execute → verify → commit → report → pause. Do not start
   the next bolt on your own initiative.
2. **Never claim a bolt done unless its checks actually ran.** Paste the
   real command output — `pytest` summary and a `wring` transcript — into
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
- **`.wringer.yaml` is arbitrary code execution by design** — gates run
  through a shell with the user's privileges. Never add a feature that
  widens that (no fetching a config over the network, no running a gate
  from an untrusted source) without a spec change and a SECURITY.md
  update. Bundles are redacted before write, but redaction only knows about
  values in the environment — a secret a gate reads from a file and prints
  is still yours to catch, so read a bundle before pasting it anywhere.
- **Don't run `wring verify` on this repo casually while iterating** — each
  run writes a new `.wringer/runs/<id>/`. Harmless (gitignored), just noisy.
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
