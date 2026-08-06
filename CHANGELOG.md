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

- **`wring verify --prove`** — vacuity detection
  ([SPEC_VACUITY_V0.md](SPEC_VACUITY_V0.md)). After the gates pass, re-run
  them against the *pre-change* tree in a scratch worktree detached at HEAD. A
  gate that passes on both proved nothing about the change; **every** required
  gate passing on both is the verdict `gates_vacuous`, which `wring deliver`
  refuses — exit 1, naming the insensitive gates, the one-line fix, and the
  path to both trees' output. There is no `--allow-vacuous`.

  **Switched on by the config, not by a flag.** `run.prove: true` in
  `.wringer.yaml`; `--prove` tightens for one run; `--no-prove` does not exist
  and `wring run --no-prove` exits 2. The reason is authority over the
  supervised party rather than convenience — `wring run` drives an agent that
  writes code, and this check exists to catch that agent writing tautological
  tests, so the invoker must not get to switch it off. Matched deliberately to
  the `approved: false` interlock, so *flags may tighten, never loosen* is one
  rule rather than two precedents.

  **The trap this was built around**, and the reason it is worth the
  complexity: a detached worktree carries tracked files and nothing else, so
  in any repo whose dependencies are gitignored every pre-change gate fails on
  a missing environment — and the comparison reads that as PROOF. The feature
  built to catch reward-hacking would have certified it, on every run. Closed
  by `run.prove_setup` (a failing one yields `inconclusive`, never `proven`)
  and by requiring every `sensitive` row to cite the failure it rests on, so
  `ModuleNotFoundError: No module named 'yourproject'` is legible at a glance
  rather than convincing.

  No configurable ceiling exists, by ruling: skipping the pass would
  reintroduce the vacuity this feature exists to catch. The cost is measured
  instead — `worktree_ms` and `prove_ms` beside the per-gate rows.

  **The limit, stated rather than discovered later:** the pre-change tree is
  HEAD, so this catches green-baseline reward hacking and *cannot* tell you an
  agent neutered a test that was already failing — that gate really does fail
  at HEAD. Catching it would need reverse-patching, which the spec rules out
  by name. Recorded in SPEC_VACUITY_V0 §5a, in the docs, and pinned by a test.

- **`wring attest` and `wring audit`** — tamper-evident provenance
  ([SPEC_PROVENANCE_V0.md](SPEC_PROVENANCE_V0.md)). `attest` assembles the
  claim: *change C, authorized by spec S, proven by gates G against tree T,
  judged against rubric R with verdict V, delivered as branch B — and every
  bundle backing those clauses is byte-identical to when it was written.*
  `audit` checks it offline, with no config, by someone who trusts nobody
  involved. **Neither calls an LLM and neither opens a socket** — a test
  parses the module's imports rather than grepping its text, so the promise
  cannot be satisfied by deleting the sentence that makes it.

  A clause with no inputs is **absent, not invented**: an attestation over a
  bare `wring verify` bundle carries one clause and is still worth having.
  Bundles link by path; the attestation re-anchors them by digest, recording
  the sha256 of each bundle's `digests.json` file, so a *self-consistently*
  rewritten bundle — files and record edited together — still fails an audit.

  The money test: change one byte in one gate log, and `audit` names that file
  and exits 1. Captured, with the refusals, in
  [`docs/attest-and-audit.md`](docs/attest-and-audit.md).

  **It is unsigned, by decision, and says so in its own artifact.** The word
  *attestation* sounds cryptographic; a reader who assumes it means "signed by
  someone" has been misled by a green thing that means less than it looks
  like. So `attestation.json` carries a `limits` array, `attest` prints the
  first entry as a `!` line (doctor's mark for *worth knowing, not a problem*
  — never `✗`, nothing failed), `audit` repeats it **on success**, and both
  carry it in `--json`. Delete it and `audit` refuses the attestation.
  A signature, if one ever arrives, is the sibling file
  `attestation.json.sig` — never a payload field — so signing stays purely
  additive and every v0 attestation remains valid byte-for-byte.

  `commit_signature` records `git log -1 --format=%G?` verbatim plus the
  reported signer. Wringer touches no key and consults no trust store, and
  `audit` reports the value without re-verifying it: re-verification needs the
  reader's own keyring, which would put a network-shaped dependency on a
  command that must work on a plane. A repo that signs its commits gets a real
  chain for free; one that does not records `N` and loses nothing.

  Seven refusals, each exit 1 and each naming what is wrong: no `digests.json`
  (*cannot attest what cannot be checked* — every pre-0.2 bundle, including
  this repo's committed `.wringer.example/`), a digest mismatch in either
  direction, a broken `prev_hash` chain (**the first code that reads that
  field** — it has been written on every event since 0.2 and verified by
  nothing), a `dry_run` verdict, gates that did not pass, a spec saying
  `approved: false`, and a run recorded `gates_vacuous`. Each was verified by
  disabling it and watching its test fail, not by assertion.

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

### Schema notes

- **`wringer.vacuity.v1`** (`schema/vacuity.schema.json`) — a new sibling
  file, `vacuity.json`, so `wringer.evidence.v1` is untouched. Absent from
  every bundle whose run did not prove, which is what keeps repos that have
  not opted in behaving exactly as they do today.

- **`wringer.attestation.v1`** (`schema/attestation.schema.json`) — a new
  format, so purely additive; no frozen schema is touched. Its optional
  clauses (`authorized_by`, `judged_by`, `delivered_as`) are deliberately not
  `required`: a schema that demanded them would force the invention the spec
  forbids.

- **Every bundle now writes `digests.json`**, not only `wring verify`'s.
  `wring judge`, `wring deliver`, `wring run` and `wring fleet` bundles gain
  it, written last in each path — including `deliver`'s failure path, since a
  failed delivery is still a bundle somebody may audit. No schema moved:
  `wringer.digests.v1` already described the file, and only the verify bundle
  had ever produced one.

- **`wringer.untracked.v2`** (`schema/untracked-v2.schema.json`) supersedes
  `wringer.untracked.v1`. Each entry becomes `"<mode>:<sha256>"` — git's mode
  for the path and the digest of the payload git would store, which for a
  symlink is the link text rather than the referent's bytes. Mode and digest
  are one string so a type flip is a digest change by construction.

  **`wringer.untracked.v1` remains published, frozen and valid.** Its file is
  untouched, anything that read a v1 bundle still reads one, and `wring
  deliver` treats a v1 record the way it treats a bundle written before the
  file existed: names compared, bytes not. Editing v1's digest pattern so the
  new values fit would have silently reinterpreted every digest in every
  bundle already written, which is the one thing law 7 forbids — this is the
  first time that rule has retired a format, and `schema/README.md` carries it
  as the worked example.

### Fixed

*The first six entries close what an adversarial review of the delivery-path
work found: fourteen defects, each reproduced twice. Three were **too loose**
— `wring deliver` published a branch whose tree was not the tree the gates ran
against, and refused nothing. That is the exact failure the delivery-path work
existed to prevent, so it is fixed before anything is built on top.*

- **A rename made in an editor resurrected the deleted file on the delivered
  branch.** `_parse_status` tested the porcelain's *index* column alone, and a
  rename wears its flag in either: `R ` from `git mv`, ` R` from a rename made
  in an editor and then declared with `git add -N`, `RM` from `git mv` plus an
  edit. Missing the middle shape did not merely drop a path — the source was
  then parsed as a status line of its own, so a 3-character path sliced to the
  empty string, which vanished from the NUL-joined pathspec. `git commit
  --only` never named the deletion, and the branch shipped a file the gates
  had seen removed. No refusal, no error. Both columns are tested now.
- **`untracked.json` recorded what the gates could read, not what git would
  commit** — and one confusion caused five defects pointing in both
  directions. It hashed the bytes `open("rb")` returned, which *follows a
  symlink*, while git stores mode `120000` and a blob holding the link *text*.
  Too loose: retargeting a symlink at a file with identical bytes, replacing a
  file with a symlink to a copy of itself, and `chmod +x` on a new script all
  changed the committed tree and all delivered unrefused. Too strict, and
  **unclearable**: a dangling symlink and a symlink to a directory each
  recorded `unreadable`, which delivery refuses — and re-running `wring
  verify` recorded `unreadable` again, so no user action lifted it. And one
  hang: a symlink to a FIFO blocked `open()` forever, so **`wring verify`
  never returned**. It now records git's identity for the path,
  `"<mode>:<sha256 of the committed payload>"`, via `lstat` and `readlink`.
- **A case-only rename stranded the user on a half-made branch.** `git mv
  Foo.py foo.py` on a case-insensitive volume died `will not add file alias`
  *after* `switch --create`. Measured: no path-restricted commit can express
  it at all, and building the tree through a temporary index silently writes
  **both** paths. So it is refused from `plan()`, before any branch exists,
  naming both paths and the remedy.
- **A failed commit no longer abandons the branch it created.** Any failure
  between `switch --create` and the commit left the user standing on a branch
  Wringer had made and walked away from — with the next `wring deliver`
  refusing too, because condition 1 is *only a branch Wringer created* and
  that name now existed. The branch is undone when the commit never happened,
  and never once it has: after that it holds real work, and a failed push is a
  state to report rather than one to delete. The rollback never uses `git
  switch --force`, which is `--discard-changes` and would throw away the
  uncommitted work the failure was about.
- **The delivery pathspec no longer dies on its own size, or double-counts.**
  `_matchable` passed every path as argv: measured, 4500 long paths went
  through and 6000 raised `Argument list too long` — after the branch was
  created. It batches now (`git ls-files` has no `--pathspec-from-file`,
  checked). And `git mv a.c b.c` followed by a new file at `a.c` reports the
  name in both of git's lists, so a two-file change was announced as "3
  file(s)" in the terminal, in `--json`, and in the MR body.
- **A refusal that suggested something which could not clear it.** The
  unresolvable-default message ended "or set the branch name to something that
  is plainly not the default" — but it fires before any branch name is
  resolved, and `deliver.base` cannot clear it either, by design. It now names
  `git fetch` and `git remote set-head`, and the test follows its own
  instructions and checks the refusal is gone.

  Recorded rather than amended: commit `d0f866c` said `untracked.json` closed
  *"the last hole in this function's promise"*. It did not, and a dated note
  in `deliver.py` says so above the function rather than the claim being
  quietly overwritten.

- **An orphaned ACP worker had nothing to reap it.** `_run_worker` writes
  `worker.pgid` the instant the shell worker exists, so a SIGKILL of the loop
  still leaves `wring resume` a process group to clean up. `_run_acp_worker`
  wrote nothing — and the ACP agent runs in its own process group, so a real
  agent, holding a real session and editing a real repo, could outlive its
  supervisor with no record that it had ever existed. `wring resume` exists
  *for* the killed loop, which made this the one path where the supervision
  promise did not hold. `acp.run_turn` now reports its pid the instant the
  process exists — before the handshake, because an agent that hangs during
  `initialize` is exactly the one somebody kills the loop over.
- **The fleet deadline killed the supervisor and left the worker running.**
  `_stop` signalled the child `wring run`'s process group; the worker runs in
  its *own* group — that is how a gate timeout kills a shell and everything it
  spawned — so it survived. A deadline that stops the supervisor and not the
  work it started does not bound anything, which is the one thing a deadline
  is for; `_spawn`'s own comment had said as much about child budgets since it
  was written. Both call sites are fixed, the deadline and the no-progress
  reaper, using the same `worker.pgid` files `wring resume` already reads
  rather than a second way to find the same processes.
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

### Known gaps

Written down rather than dropped. All three were found by an adversarial
audit of this cycle's own work, and all three are outside what the field
report and its remediation plan covered.

- **The template warning reaches `wring verify` and `summary.md`, and no
  further.** `wring explain` re-reads that same bundle and prints an
  unqualified green verdict, and `wring verify --json` reports
  `"status": "passed"` with nothing to distinguish an unconfigured repo from
  a proven one. The ruling for this cycle named the terminal and
  `summary.md`, and the condition is deliberately not recorded in the bundle
  (`wringer.evidence.v1` is frozen), so `explain` has nothing to read. Doing
  this properly means deciding where a "this proved nothing" fact lives
  without moving a frozen schema — a design question, not a fix.
- **Docker Desktop on macOS remains untested by anyone.** Now stated as
  unmeasured everywhere it is claimed, and tracked in
  `docs/MANUAL_CHECKS.md`, but still the project's largest untested surface.
- **The rewritten Apple `container` path has not been re-run on an Apple
  host.** It is transcribed from a captured field run, not re-verified.
  `docs/MANUAL_CHECKS.md` says so and names what the next run must do.

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

  Belt and braces, in the same change: run ordering now prefers a run's own
  record of when it began — `started_at` from `manifest.json` or, for
  `wring judge`, from `verdict.json` — over its directory name, falling back
  to the id (read as UTC) and then to mtime. The id becoming unambiguous is
  the fix; not depending on it is what makes the next timezone a non-event.
  This matters most where there is no record to read: a loop killed
  mid-flight never writes its manifest, and killed loops are the only thing
  `wring resume` exists for.

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
