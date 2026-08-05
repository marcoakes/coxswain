# Changelog

Notable changes, newest first. Wringer follows [semantic
versioning](https://semver.org/); schema versions move independently of the
package version and are listed per release.

## Unreleased

Fifteen findings from the second field run — and the first execution of the
Apple `container` path by anyone, on a clean MDM-managed macOS 26 Apple
silicon host. CI structurally cannot run that path (GitHub's macOS runners
have no nested virtualization), so every `AC-*` finding below is information
no test, review or amount of reading could have produced. The full transcript
is preserved verbatim at `docs/field-report-2026-08-05.md`.

The through-line, for the second report running: **most of these were steps
whose gate had never been executed.** So the test coverage is the deliverable
here, not the fixes.

### Added

- **`docs/MANUAL_CHECKS.md`** — a dated record of the checks CI structurally
  cannot run: the Apple `container` sequence, the Docker-stub check, and a
  "last passed" table naming host, OS, runtime version, date and commit. It
  carries an explicit **unclaimed** row for Docker Desktop on macOS, which
  nobody has ever tested and which `AC-02` showed matters more than it looked.
- **Guards against every regression below**, in `tests/test_docs.py`,
  `tests/test_detect.py`, `tests/test_init.py`, `tests/test_evidence.py` and
  `scripts/setup-selftest.sh`.
- **`scripts/scratch.sh`** — one place deciding where a script may create and
  destroy a scratch tree, defaulting to `$TMPDIR` and refusing `/`, `$HOME`
  and relative paths.

### Fixed

- **`SETUP.md`: `container image`, not `container images`** (BLOCKER). Apple
  `container` 1.2.0 spells the subcommand singular. The plural exits 64 on a
  pull with a misleading "missing plugin" diagnosis, and fails *silently*
  through a pipe on a list — so an agent cannot tell "not pulled" from "wrong
  command", and the runbook's own stop condition never fires.
- **`SETUP.md`: the Apple path, rewritten.** `brew install container` (a
  formula, no admin password) offered alongside the 95.9 MB signed `.pkg`;
  `container system status`'s real nine-row table instead of "a status line";
  the first `container run`'s six-stage kernel-and-init-image setup
  documented so a healthy run stops being a false stop; the ~470 MB on-disk
  cost of a 160 MB pull; and the version corrected from "v1.0+" to 1.2.0.
- **`SETUP.md`: `--user`/`-e HOME` are a Linux requirement, not a universal
  one.** The runbook claimed that without them the workspace is read-only and
  `wring doctor` reports a blocking problem. Measured false on Apple
  `container`, which translates uids across the mount: a flagless run exits 0
  and the bundle lands owned by the host user. The flags stay in every
  recipe; only the false claim about their absence changed.
- **`wring init` says what it found**, instead of asserting that all three
  build-config files are absent. Pointed at a real Python project it reported
  "no pyproject.toml" while the developer was looking at theirs. The
  *detection* was correct and is unchanged — the repo declares no ruff, mypy
  or pytest, so there was genuinely nothing to gate, and refusing to invent
  `pytest -q` is the documented rule holding under first contact.
- **`wring init && wring verify` exits 0 in an unconfigured repo.** The
  template's three example gates were all `make` targets, so the first run
  after `init` went red and exited 1 on a healthy tree. It now ships a
  passing `placeholder` gate — and says, on the terminal and in `summary.md`,
  that the run proved nothing until you replace it. A green exit that
  quietly means nothing would be the vacuous evidence this project exists to
  prevent.
- **Scripts no longer default to one developer's sandbox.** Five of them
  pointed `rm -rf` or `find -delete` at a hardcoded path named after one
  machine's uid and one user's home. `setup-selftest.sh` additionally
  prepended a `.venv` the current install path never creates, so it silently
  tested whatever `wring` was on `PATH` — or nothing. It now names the binary
  under test and exits 2 when there is none.
- **`SETUP.md`: the probe repo no longer commits its own evidence.** Step 7H
  hand-writes its config and never calls `wring init`, so it got no
  `.gitignore` and its `git add -A` staged the previous run's `.wringer/` —
  measured at two runs, two commits, nine tracked evidence files. On a real
  repository that pattern commits raw gate output into the user's history.
- **`SETUP.md`: step 8 now shows what a skip looks like.** It documented three
  `-` lines outside a repository and then gave a command run *from* the
  clone, where those three never skip. A captured contrasting transcript was
  added, and `setup-selftest.sh` asserts three `-` lines and three
  `"status": "skip"`.
- **`SETUP.md`: the Docker-stub check uses `ls -ld`.** It named `ls -la`,
  which the stub's own stripped permissions defeat — a diagnostic that fails
  in exactly the case it diagnoses.

### Changed

- **BREAKING — `run_id` is stamped in UTC**, not in the host's local time.
  A run id is a directory *name*, and names get sorted; a container has no
  reason to share its host's timezone, and this project's own image resolves
  to `Etc/UTC`. A field run on 2026-08-05 measured a container run that
  happened twenty minutes *after* a host run of the same repository carrying
  an id that sorted forty minutes *before* it, so `ls` and `ls -t` disagreed
  about which run was newest. For a tool whose premise is auditable evidence
  that is a defect, not a preference.

  **Existing run directories are unaffected** — nothing is renamed, nothing
  is migrated, every bundle already on disk stays exactly as it is. Only
  newly created ids shift, by your UTC offset. `started_at` in the manifest
  is unchanged and stays local-with-offset: it is the field humans read.
  `wringer.evidence.v1` is untouched, and its own description of `run_id`
  already told readers not to parse it for a timestamp.

  Taken now because the format only gets more expensive to change: 0.2.0 is
  two days old and run directories are local artefacts nobody has archived.

  Belt and braces, in the same change: Wringer no longer orders runs by
  directory name anywhere. `wring explain` and `wring resume` pick the
  latest run by the manifest's `started_at`, falling back to the id and then
  to mtime. The id becoming unambiguous is the fix; not depending on it is
  what makes the next timezone a non-event.

## 0.2.0 — 2026-08-03

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
