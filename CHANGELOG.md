# Changelog

Notable changes, newest first. Wringer follows [semantic
versioning](https://semver.org/); schema versions move independently of the
package version and are listed per release.

## 0.2.0 — unreleased

The release that turns an evidence compiler into a supervision layer. **Ten
new commands**, and the first release in which Wringer can write git history
at all.

### Added

- **`wring run`** — the repair loop: verify → brief → your worker → verify,
  until the evidence says stop. A worker's exit code never ends the loop.
  Contract: `SPEC_RUN_V0.md`, schema `wringer.loop.v1`.
- **`wring resume`** — continue a loop that was killed mid-flight, from its
  ledger. Spent iterations stay spent.
- **`wring fleet`** — hundreds of queued tasks, bounded concurrency, a
  declared self-healing ladder, liveness measured by ledger growth rather
  than by a process still existing, and honest `{succeeded, failed, parked}`
  counts. Contract: `SPEC_SUPERVISION_V0.md` and its eight invariants.
- **`wring judge`** — a rubric verdict over a *finished* bundle, structurally
  unable to see a worker's output. Dry-run by default. Contract:
  `SPEC_JUDGE_V0.md`, schemas `wringer.judge.v1` and `wringer.rubric.v1`.
- **`wring doctor`** — machine-checkable preconditions, one line per check,
  `--json`, exit 1 on anything blocking. Diagnoses; never repairs.
- **`wring spec` / `wring plan`** — the front door. A PRD in, acceptance
  criteria and a build plan out **as a file a human approves**. `approved:
  false` is an interlock no flag, environment variable or model reply may
  flip, and there is deliberately no `--yes`. Contract: `SPEC_INTENT_V0.md`,
  schema `wringer.spec.v1`.
- **`wring get` / `wring issue` / `wring deliver`** — work in as a URL, out
  as a reviewed branch. Contract: `SPEC_GET_V0.md`, schemas
  `wringer.delivery.v1` and `wringer.acquired.v1`.
- **The ACP worker seam** — `run.worker` takes an `acp:` mapping beside the
  shell form. Wringer is the ACP *client* and never the agent. Contract:
  `SPEC_ACP_V0.md`.
- **An OCI image**, built and run-tested by CI, published to
  `ghcr.io/marcoakes/wringer:main`. It contains Wringer and a Python runtime
  and **nothing else** — your gates run your repo's commands, so your
  toolchain comes from your repo.
- **`digests.json`** in every evidence bundle (`wringer.digests.v1`): a
  sha256 per file, written last so it covers the manifest and the summary.
  A `prev_hash` chain makes the *ledger* tamper-evident; this covers the rest
  of the bundle. Tamper-evidence, not tamper-proofing.
- **Hash-chained ledgers** — `prev_hash` on every event in every ledger.
  Written now, consumed by `wring attest` later.

### Changed

- **Wringer may now write git history — but only on `--send`, only onto a
  branch it created, never the default branch, never a force push, and with
  a ledger event appended before every write.** This is `wring deliver` and
  nothing else; `verify`, `run`, `resume`, `fleet`, `spec` and `plan` still
  touch git not at all. See `SPEC_GET_V0.md` §1.
- **Three commands can now send over a network**, each behind a flag you
  type and an endpoint your repo declared: `judge --send`, `spec --send`,
  `deliver --send`. Two fetch, because fetching is their purpose: `get`,
  `issue`. **Nothing that proves anything touches a network** — that rule is
  unchanged and is the one that matters.
- `wring init` no longer writes a `.gitignore` outside a git repository, and
  says why `wring verify` will refuse there.

### Fixed

- **`wring deliver` could publish a claim of verification about code that
  was never verified** — it read a bundle's *status* without checking the
  bundle described the tree being shipped. It now refuses unless the commit,
  the changed-file set and every tracked byte match the run.
- **A delivery could carry the evidence bundle itself** into a public branch
  — including whatever a gate printed — in any repo that had not run `wring
  init`. It now stages exactly the paths the plan lists.
- **An ACP agent that stopped reading its input could wedge the supervisor
  indefinitely**: the blocking pipe write was armed before either timeout
  existed. Writes are now bounded by the turn's deadline.
- **`judge.timeout` and `forge.timeout` bounded no total** — they are
  per-socket-operation timeouts, and a dribbling endpoint reset them
  forever. Both are now deadlines.
- **`fleet.child.worker_timeout` and `fleet.child.wall_clock` were parsed
  and silently discarded**, so a child could outlive the fleet that spawned
  it. `wring run` gains `--worker-timeout` and `--wall-clock`, and the fleet
  passes them down.

### Schema notes for anyone on 0.1.0

- **`wringer.evidence.v1` is unchanged and remains readable.** Bundles
  produced by 0.1.0 validate against the published schema; bundles produced
  by 0.2.0 additionally carry `prev_hash` on each event and a sibling
  `digests.json`. Both are **optional** to a reader — `prev_hash` was briefly
  marked required in the published schema during 0.2 development, which
  would have invalidated every 0.1.0 bundle including this repo's own
  committed example. That was a mistake and is corrected; a test now
  validates the committed bundle on every run.
- New schemas in this release: `wringer.loop.v1`, `wringer.fleet.v1`,
  `wringer.judge.v1`, `wringer.rubric.v1`, `wringer.spec.v1`,
  `wringer.delivery.v1`, `wringer.acquired.v1`, `wringer.digests.v1`. **All
  freeze at this tag.**

### Upgrading

Nothing to do. `wring verify` behaves as it did, its bundles are readable by
anything that read 0.1.0's, and every new command is opt-in — most require a
config section that does not exist until you add it.

## 0.1.0 — 2026-07-31

The first release: a standalone evidence compiler.

- **`wring init`** — write a `.wringer.yaml` from what your project already
  declares.
- **`wring verify`** — run the declared gates in order and write a portable
  evidence bundle: `manifest.json`, timestamped `evidence.jsonl`,
  `summary.md`, `diff.patch`, `status.txt`, and per-gate logs and results.
  `--json` for agents, `--gate` for one gate, `--output` for a chosen
  directory.
- **`wring explain`** — diagnose a finished run, without an LLM.
- Exit codes 0/1/2/3/4; secrets redacted before any write; gate timeouts
  enforced by process-group kill; schemas published under `schema/`.
- No LLM call and no network call anywhere in the release.

Contract: `SPEC_VERIFY_V0.md`, including its Definition of PROVEN — Wringer
verifies Wringer in CI, with the demo bundle committed, before the tag.
