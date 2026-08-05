# Manual checks — what CI structurally cannot run

Some of this project's claims cannot be tested by any workflow, on any
runner, ever. Not "we have not got round to it": **structurally cannot**.
GitHub's macOS runners have no nested virtualization, so `container system
start` cannot work there, so the entire Apple `container` path is beyond
CI's reach by construction. The Docker-stub check (R2-02) is beyond it for a
different reason — it needs a machine with a stripped `Docker.app` to look
at, which is a state you inherit rather than create.

The honest answer to that is not to quietly assume those paths work. It is
to make the manual coverage **recorded and dated**, so anyone can see how
old the evidence is and what it actually covered.

**If you run one of these sequences, add a row.** A check nobody wrote down
is a check nobody ran — this file is subject to law 1 like everything else.

---

## Coverage record

**Last passed** — one row per host that has actually executed a sequence.

| Sequence | Host | OS | Runtime | Date | Commit | Result |
|---|---|---|---|---|---|---|
| Apple `container` | Apple silicon, MDM-managed, uid:gid `502:20` | macOS 26.5.2, `Darwin arm64` | Apple `container` 1.2.0 (Homebrew formula, Workbrew 1.7.3 / Homebrew 6.0.15) | 2026-08-05 | `75167c2` | **Passed with corrections applied by hand** — see the note below |
| Docker stub (R2-02) | Apple silicon, MDM-managed | macOS 26.5.2 | none — `/Applications/Docker.app` present as a stripped stub | 2026-08-05 | `75167c2` | **Observed, not executed as a sequence.** `d--------- 2 root admin 64`, no binary, no socket — seen while diagnosing step 4B. Sequence C below was written afterwards and has never been run as written |
| Docker Desktop on macOS | — | — | — | **never** | — | **UNCLAIMED — never tested by anyone** |
| Docker on Linux | GitHub Actions `ubuntu-latest` | — | Docker (CI) | every push | `main` | Automated; see `.github/workflows/tests.yml` |

### About the 2026-08-05 Apple row

This is a **captured fact**, and it is worth being exact about what it
covers, because it is the only evidence the Apple path has.

On 2026-08-05 a clean, MDM-managed macOS 26 Apple-silicon host executed
`SETUP.md` at `75167c2` end to end — the first execution of the Apple
`container` path by anyone. It proved a great deal: the published image
pulled, `container` started, the bind mount resolved, real gates ran, and a
complete seven-artefact evidence bundle landed on the host **owned by the
host user** (`502:20`) from a process running as uid 1000 inside the
container. Exit 0. The full transcript is preserved verbatim in
[field-report-2026-08-05.md](field-report-2026-08-05.md).

What it does **not** mean: that the runbook as written at `75167c2` worked.
It did not. `SETUP.md` said `container images pull`, which does not exist
(AC-01), and the operator got there by correcting the command by hand. The
runbook was then rewritten from that run's captured output — but **the
rewritten text has never itself been executed on an Apple host.** It is
transcribed evidence, not re-verified evidence.

So the next Apple run has a specific job: run the rewritten sequence
verbatim, change nothing, and add a row. Until then the Apple row says
"passed with corrections applied by hand", because that is what happened.

### About the Docker Desktop row

`--user`/`-e HOME` behaviour is genuinely runtime-specific — AC-02 measured
Apple `container` translating uids across a bind mount, exactly unlike
Linux. CI covers Docker on Linux and one field run covers Apple `container`.
**Nobody has ever run Wringer under Docker Desktop on macOS**, and SETUP.md
makes claims about it. That makes it this project's largest untested
surface, and it is listed here so it is visible rather than assumed.

---

## Sequence A — the Apple `container` path

**Requires:** macOS 26 on Apple silicon. **Time:** about ten minutes, most
of it the pull. **No API key is involved at any point** — if any step asks
for one, stop: that is a bug in the runbook, not a step to complete.

Run these from a clone of this repository, verbatim from `SETUP.md`. The
point is to execute what the runbook *says*, not what you know it means. If
a command needs correcting to work, that correction is a finding — record it
rather than fixing it silently and reporting a pass.

- [ ] **1. In the repo.** `git rev-parse --show-toplevel && grep -m1 '^name = ' pyproject.toml`
      → an absolute path, then `name = "wringer"`.
- [ ] **2. Host prerequisites.** SETUP.md step 2's interpreter loop
      → any git version, and at least one line reporting Python 3.11+.
      A stock `python3 -> 3.9.x` alongside a qualifying one is fine.
- [ ] **3. Install `wring`.** `uv tool install --force --python 3.12 .`
      → `wring --version` starts `wring 0.2`, then `doctor present`.
      Note **where** it landed; `uv tool install` uses `~/.local/bin`.
- [ ] **4. Pick the runtime.** `uname -s -m; sw_vers -productVersion`
      → `Darwin arm64` and `26.` or higher, so 4A is eligible.
- [ ] **4A. `container --version`** → `1.2.0` or later. A truncated
      `commit: unspeci` is Apple's own output, not damage.
- [ ] **4A. Install if missing** — `brew install container` (a *formula*,
      not a cask; no admin password). The install is the human's to run.
- [ ] **4A. `container system start`**, then `container system status`
      → a **table**, with the row `status  running`. A blank `logRoot` is
      normal.
- [ ] **5. `container image pull ghcr.io/marcoakes/wringer:main`**
      → exit 0. **`image`, singular.** Apple unpacks *every* architecture in
      the index, so a ~160 MB pull lands as roughly 470 MB on disk.
- [ ] **5. `container image list | grep wringer`** → exactly one row naming
      the image.
- [ ] **6. Workspace.** `mkdir -p ~/wringer-workspace` and the write probe
      → `workspace writable`.
- [ ] **7. The image runs and sees the mount.** `container run --rm --volume
      "$HOME/wringer-workspace:/workspace" --workdir /workspace
      ghcr.io/marcoakes/wringer:main --version`
      → the same `wring 0.2…` line, from inside the container. **The first
      `container run` on a machine** fetches a kernel and a ~66 MB init
      image behind a six-stage ladder, taking about ten seconds. Expected,
      once.
- [ ] **8. `wring doctor` from the clone** → exit 0; the `!` lines for
      container runtime and llm key are expected.
- [ ] **8. `wring doctor` from a directory that is not a repo** → exit 0,
      and **three `-` lines**. (`setup-selftest.sh` asserts this too, so a
      disagreement between them is itself a finding.)
- [ ] **9. Hand back.** No key touched at any point in the sequence.
- [ ] **End to end.** The "What good looks like" probe, run through
      `container run … verify` → exit 0, a bundle on disk, and **every file
      in it owned by your host uid:gid**, not by uid 1000. Check with
      `ls -lan`.
- [ ] **AC-02, both ways.** Run the same verify **without** `--user` and
      `-e HOME`. On Apple `container` it should also exit 0 and also land
      owned by the host user — the flags are required on Linux and harmless
      here. If it *fails* on your host, that is a finding and SETUP.md's
      three-runtime paragraph is wrong.
- [ ] **Record it.** Add a row to the coverage table above: host, OS,
      runtime version, date, commit, result.

---

## Sequence B — the Docker Desktop path on macOS

**Never run by anyone.** There is no checklist here yet because writing one
from imagination is how the last set of findings happened — a runbook whose
steps had never been executed. Whoever runs this first should follow
`SETUP.md`'s 4B/5/7 branch verbatim, write down what actually happened, and
turn that into this section.

The one thing worth knowing in advance: AC-02 claims Docker Desktop
translates uids across a bind mount the way Apple `container` does. That
claim is **inherited from an older draft of SETUP.md and has never been
measured.** Measuring it is the most valuable thing this sequence can do.

---

## Sequence C — the Docker stub check (R2-02)

**Requires:** a machine where `/Applications/Docker.app` exists as a
removal leftover — typically an MDM-managed Mac where Docker Desktop was
uninstalled centrally. You cannot usefully create this state; you either
have it or you do not.

- [ ] `docker version --format '{{.Server.Version}}'` → `command not found`.
- [ ] `ls -ld /Applications/Docker.app` → something shaped like
      `d---------  2 root  admin  64`. **`-ld`, not `-la`**: the stripped
      permissions are exactly what stops `ls -la` reading the directory, so
      the plural-listing form returns `Permission denied` and tells you
      nothing.
- [ ] Confirm the diagnosis holds: no binary inside, no socket. This is a
      leftover, not an install, and clearing it needs privileges — it is the
      human's or their IT's to do, never the agent's.
- [ ] **Record it.** Add a row above.

---

## What is *not* here, and why

These are covered by automated tests and do not belong on a manual list.
They are named so nobody adds them again out of caution:

- `container images` and `ls -la /Applications/Docker.app` never appearing as
  a *command* a runbook tells you to run — `tests/test_docs.py`. Prose may
  still name them, and does: the fixes for both explain the broken form on
  purpose, and a warning that cannot spell the wrong command is not a
  warning. The guards distinguish a ```bash fence (an instruction) from an
  untagged one (a transcript of what happened).
- No script defaulting to one developer's sandbox path — `tests/test_docs.py`.
- The scratch tree a script may recursively delete always ends in a component
  the tool chose — `tests/test_scratch.py`.
- SETUP.md's step 7H and the selftest's copy of it not drifting apart —
  `tests/test_docs.py`.
- `run_id` being timezone-invariant — `tests/test_evidence.py`.
- The blank template naming what it found — `tests/test_detect.py`.
- `wring init && wring verify` exiting 0 in an empty repo, and saying the
  run proved nothing — `tests/test_init.py`.
- Step 7H's hygiene, and doctor's three skips outside a repo —
  `scripts/setup-selftest.sh`.

The dividing line is simple: if a check can run without a container runtime
and without a specific broken machine, it is a test, not a checklist item.
