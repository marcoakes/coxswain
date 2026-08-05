# Field report — SETUP.md and the Apple `container` path

**Date:** 2026-08-05 · **Repo under test:** `75167c2` (`main`)
**Tested by:** Claude Code on a clean, MDM-managed macOS 26 Apple-silicon host

*Preserved verbatim as primary evidence. This is the first execution of the
Apple `container` path by anyone — CI cannot run it, because GitHub's macOS
runners have no nested virtualisation. The remediation it drives is Phase 1c
of `~/Claude/WRINGER_RELEASE_PLAN.md`.*

---

## 1. Executive summary

**The container story is no longer a claim.** Apple `container` 1.2.0 pulled
the published image, started, resolved a bind mount, ran real gates, and wrote
a complete evidence bundle to the host with correct ownership. Exit 0. The
uid/mount failure mode the runbook warns about **did not occur** — and the
measurements explain why.

**Proven on this host:** steps 1, 2, 3, 6, 7H, 8, 9 verbatim; step 4A once
Apple `container` is installed; step 5 **only with a corrected subcommand**
(AC-01); step 7 and the end-to-end container verify. The bundle contains all
seven documented artefacts, owned by the host user, with `diff.patch` /
`status.txt` legitimately empty on a clean probe and correctly populated on a
dirty one. `wring doctor` is clean from the clone (exit 0) and reports three
`-` skips outside a repository (exit 0). **All nine defects from the
2026-08-04 report are fixed and verified fixed.**

**Broken:** 15 findings — 1 blocker, 3 high, 8 medium, 3 low. Seven
Apple-specific (`AC-*`), eight from re-running the rewritten runbook and
pointing `wring init` at real repositories (`R2-*`).

**Unproven anywhere:** the Docker path on macOS. CI covers Docker on Linux;
Docker Desktop on macOS remains untested by anyone, and AC-02 shows
runtime-specific mount behaviour is real, so that gap matters more than it
looked.

---

## 2. Findings register

| ID | Sev | Area | Finding |
|---|---|---|---|
| AC-01 | BLOCKER | SETUP.md:266,280 | `container images` is not a subcommand; it is `container image` |
| AC-02 | HIGH | SETUP.md:491-496 | `--user`/`-e HOME` not required on Apple `container`; stated failure mode does not occur |
| AC-03 | HIGH | evidence.py:219 | `run_id` stamped in local time, so container and host runs sort out of order |
| R2-07 | HIGH | detect.py:270-274 | Blank template claims "no pyproject.toml" when one exists |
| AC-04 | MEDIUM | SETUP.md:193-196 | `brew install container` unmentioned; only the 95.9 MB signed `.pkg` offered |
| AC-06 | MEDIUM | SETUP.md:210 | Step 4A's expected output wrong twice: status is a table; first run does undocumented setup |
| R2-01 | MEDIUM | SETUP.md:347-356 | Step 8's own command cannot produce the `-` skip lines it documents |
| R2-02 | MEDIUM | SETUP.md:225 | Docker-stub check names `ls -la`, which cannot show the stub |
| R2-03 | MEDIUM | SETUP.md:331 | Step 7H's `git add -A` commits evidence bundles into the probe repo |
| R2-05 | MEDIUM | setup-selftest.sh:15, verify-published.sh:10 | Hardcoded developer-specific temp paths |
| R2-06 | MEDIUM | setup-selftest.sh:16 | Assumes a `.venv` the rewritten step 3 no longer creates |
| R2-08 | MEDIUM | detect.py:286-293 | Template's `make` gates guarantee a failing first `wring verify` |
| AC-05 | LOW | SETUP.md:31 | "v1.0+" stale; current release is 1.2.0 |
| AC-07 | LOW | SETUP.md:269 | Apple unpacks every architecture (~468 MB from a 160 MB pull) |
| R2-04 | LOW | SETUP.md:331,91 | 7H rerun emits a git warning against a blanket "idempotent is harmless" promise |

---

## 3. Environment under test

| Component | Value |
|---|---|
| Platform | `Darwin arm64`, macOS `26.5.2` |
| Default `python3` | `/usr/bin/python3` → 3.9.6 (below the floor) |
| Qualifying Python | `~/.local/bin/python3.12` → 3.12.13 |
| Homebrew | Workbrew 1.7.3 / Homebrew 6.0.15, prefix `/opt/homebrew` |
| Docker | **absent** (stripped stub, see below) |
| Apple `container` | 1.2.0 via `brew install container` |
| Host identity | uid:gid `502:20` |
| `wring` under test | 0.2.0 built from the clone at `75167c2` |

`/Applications/Docker.app` is an empty root-owned directory with every
permission stripped (`d--------- 2 root admin 64`), no binary anywhere, no
socket — an MDM removal leftover, not an install. That produced R2-02.
Package management is **Workbrew** (enterprise-managed Homebrew), which made
`brew install container` the natural route and surfaced AC-04.

**Image identity, verified before any runtime existed:** anonymous
`GET ghcr.io/v2/marcoakes/wringer/manifests/main` → 200, genuine multi-arch
OCI index (linux/amd64 + linux/arm64), `tags: ["main"]`. SETUP.md accurate on
all three points.

---

## 4. Step status matrix

| Step | Verdict | Notes |
|---|---|---|
| 1 in the repo | PASS | Verbatim |
| 2 host prerequisites | PASS | Passes **only** because of the round-1 fix; the old gate hard-stopped here |
| 3 install `wring` | PASS | `uv tool install --force --python 3.12 .` → `wring 0.2.0` |
| 4 pick runtime | PASS | `Darwin arm64` + `26.5.2` → 4A eligible |
| 4A Apple `container` | PASS | After install. Expected output wrong twice (AC-06) |
| 4B Docker | N/A | Not installed; stub detected (R2-02) |
| 5 pull the image | **FAIL as written** | AC-01. Passes with `container image pull` |
| 6 create workspace | PASS | `workspace writable` |
| 7 image runs, sees mount | PASS | `wring 0.2.0` from inside the container, exit 0 |
| 7H host fallback | PASS | Exit 0, bundle on disk. Side effect: R2-03 |
| 8 `wring doctor` | PASS | Exit 0 from clone; three `-` skips, exit 0 outside a repo |
| 9 hand back | PASS | Verbatim; no key touched at any point |
| "What good looks like" | PASS | End-to-end container verify, exit 0, correct host ownership |

---

## 5. Round 1 — the nine fixes, confirmed landed

Commit `75167c2` addresses every item from 2026-08-04. Verified by
re-execution, not by reading: **A** SETUP.md:115 interpreter loop · **B**
:130-154 uv-first with both failure modes named · **C** :358-395 real captured
run + marks table + a test that fails if a check name drifts · **D** :347
heading "from your clone", `SKIP` in `doctor.py` · **E** :349-352 · **F** :501
corrected to `probe` · **G** :505-511 · **H** :41-51 plus step 7H · **I**
:17-20 "Every command block is self-contained".

The test guard added for C is a better fix than was suggested — it makes the
transcript's check names non-rottable.

---

## 6. Findings — detail

### AC-01 — BLOCKER — `container images` is not a subcommand

**Location:** `SETUP.md:266` (pull), `:280` (verify)

```
$ container images pull ghcr.io/marcoakes/wringer:main
Error: Plugin 'container-images' not found.
...
Usage: container [--debug] <subcommand>
exit 64

$ container images list | grep wringer      # as documented
exit 1                                       # no output, no error
```

**Root cause.** Apple `container` 1.2.0 names it `image` (alias `i`), not
`images`. Every plugin is present; the install is fine. Two aggravating
factors: the pull error is **actively misleading** (sends the reader hunting a
missing plugin under two paths, one of which is not a directory), and the
verify form fails **silently** through the pipe — an agent greps, gets no row
and no error, and cannot distinguish "not pulled" from "wrong command".

**Fix.** `container image pull …` and `container image list | grep wringer`.

**Verified corrected:**

```
$ container image pull ghcr.io/marcoakes/wringer:main
[1/2] Fetching image 98% (29 of 30 blobs, 157.4/160.3 MB, 38 KB/s) [20s]
[2/2] Unpacking image for platform linux/amd64 100% (9,140 of 9,140 entries, 220.7/220.7 MB) [21s]
[2/2] Unpacking image for platform linux/arm64 100% (9,142 of 9,142 entries, 247.8/247.8 MB) [23s]
exit 0

$ container image list
NAME                       TAG   DIGEST
ghcr.io/marcoakes/wringer  main  2a9dd63bd91b
```

**Acceptance test.** On a macOS 26 arm64 host with Apple `container`:
`container image pull` exits 0 and `container image list | grep wringer`
prints one row. Also assert the negative — `container images` must not appear
anywhere in `SETUP.md`.

### AC-02 — HIGH — `--user`/`-e HOME` are not required on Apple `container`

**Location:** `SETUP.md:491-496`. The runbook states: *"Without them the
workspace is read-only to the container and `wring doctor` correctly reports a
blocking problem."* **False on Apple `container`.**

```
WITHOUT --user: uid=1000(wring) gid=1000(wring)
WITH --user 502:20: uid=502 gid=20(dialout)

$ [flagless] touch /workspace/.uid-probe   →  WRITE OK as uid 1000
$ ls -lan ~/wringer-workspace/.uid-probe
-rw-r--r--  1 502  20  0 .uid-probe        # landed as the HOST user

verify exit WITHOUT --user/-e HOME: 0
drwxr-xr-x  9 502  20  288 .               # bundle owned by host user
```

**Root cause.** The image does run as uid 1000. Apple `container` translates
uids across a bind mount, so a uid-1000 process writes successfully and the
file lands owned by `502:20`. Apple behaves like Docker Desktop, not like
Linux. The flags are harmless there — just not load-bearing. **Linux remains
the only case where they are required.**

**Fix.** Replace the closing paragraph of "What good looks like":

> **`--user` and `-e HOME` are required on Linux, and harmless elsewhere.** The
> image runs as uid 1000, a bind-mounted directory keeps its host ownership,
> and Wringer must write its evidence into that mount. On **Linux** that fails
> without these flags, which is why CI passes them on every push. **Docker
> Desktop on macOS** and **Apple `container`** both translate uids across the
> mount, so the flags change nothing there — measured on Apple `container`
> 1.2.0: a flagless run exits 0 and the bundle lands owned by the host user.
> Pass them anyway; one recipe that is correct everywhere beats three that are
> each correct somewhere.

Footnote worth adding: `--user 502:20` reports `gid=20(dialout)` inside the
container — gid 20 is `staff` on macOS, `dialout` on Linux. Harmless, but
confusing in a log.

**Acceptance test.** On Apple `container`: `wring verify` in the mounted probe
exits 0 both with and without the flags, and in both cases every bundle file
is owned by the invoking host uid:gid.

### AC-03 — HIGH — `run_id` is local-time, so host and container runs sort wrongly

**Location:** `src/wringer/evidence.py:219-225`. Working as designed; the
design has a consequence nobody had hit because nobody had run in a container.

```
host  date: 2026-08-05T10:48:50+0100  (BST)
cont. date: 2026-08-05T09:48:51+0000  (UTC)
TZ=   ·   /etc/localtime -> /usr/share/zoneinfo/Etc/UTC
```

| Where | run_id | started_at | Wall clock |
|---|---|---|---|
| Host | `20260805-102717-3470` | `+01:00` | 10:27 |
| Container | `20260805-094741-56d0` | `+00:00` | 10:47 |

The container run happened **20 minutes later** and its `run_id` sorts **40
minutes earlier**. `run_id` is the directory name, so any consumer ordering
runs lexically disagrees with `ls -t`. For a tool whose premise is auditable
evidence, an ambiguous ordering key is worth more than a footnote. Nothing is
lost — `started_at` records the offset — it is the *id* that is ambiguous.

**Fix — recommended.** Stamp the id in UTC; keep `started_at`
local-with-offset for human reading. `timezone` needs adding to the existing
`datetime` import; callers already pass an aware datetime, so
`.astimezone(utc)` is a conversion, not a reinterpretation.

**Breaking change to id format** — ids shift by the host's offset. 0.2.0 is
current and run directories are local artefacts, so now is the cheap moment.
Fallback if unacceptable: document the caveat in `SPEC_RUN_V0.md` and have
run-listing code sort on `started_at`.

**Acceptance test.**

```python
inst = datetime(2026, 8, 5, 9, 47, 41, tzinfo=timezone.utc)
a = new_run_id(inst.astimezone(timezone(timedelta(hours=1))))
b = new_run_id(inst.astimezone(timezone.utc))
assert a.rsplit("-", 1)[0] == b.rsplit("-", 1)[0] == "20260805-094741"
```

### R2-07 — HIGH — the blank template tells Python users their `pyproject.toml` does not exist

**Location:** `src/wringer/detect.py:270-274`. Run in a real Python project
with `pyproject.toml`, `uv.lock` and a `.venv`:

```
$ wring init
Wrote .wringer.yaml — nothing to detect here, so it is a template.
# Nothing was detected here — no pyproject.toml, package.json or Makefile
```

**The detection is correct and must not change.** `_detect_python` requires
ruff/mypy/pytest in `[tool.*]`, a config file, a dependency name, or real
Python test files. This project declares none, so there is genuinely nothing
to gate, and the docstring rule — *"if detection is uncertain, generate
comments rather than being clever"* — held. Refusing to invent `pytest -q` for
a repo with no tests is correct and **survived first contact with a real
codebase**.

The **message** is the defect. `BLANK_TEMPLATE` is a module constant, so it
cannot say what it found and asserts absence for all three files. A Python
developer reads "no pyproject.toml" while looking at theirs.

**Fix.** Add `seen: tuple[str, ...]` to `Detection`, populate from
`("pyproject.toml", "package.json", "Makefile", "makefile")` that exist, and
replace the constant with a renderer:

```python
def _blank_template(detection: Detection | None = None) -> str:
    seen = detection.seen if detection else ()
    if seen:
        why = (f"# Found {', '.join(seen)}, but nothing in it declares a lint, "
               "typecheck or\n# test command Wringer recognises — so this is a "
               "template, not a\n# guess. Wringer reports commands your repo "
               "already writes down;\n# it never invents one.\n")
    else:
        why = ("# No pyproject.toml, package.json or Makefile here, so there was\n"
               "# nothing to read commands from — this is a template, not a guess.\n")
    return _BLANK_HEAD + why + _BLANK_TAIL
```

`cli.py:314-315`'s summary should follow suit.

**Acceptance test.** Temp dir with a `[project]`-only `pyproject.toml`:
output contains "Found pyproject.toml", must **not** contain "No
pyproject.toml". Empty temp dir: contains "No pyproject.toml".

### AC-04 — MEDIUM — `brew install container` is easier and unmentioned

`SETUP.md:193-196` offers only the signed `.pkg`. There is a bottled
`homebrew-core` formula at the same version — no admin password (Homebrew
writes into its own prefix) versus 95.9 MB and a privileged installer. It is
a **formula**, not a cask. This is how the runtime under test was installed.
Notes worth adding: `/opt/homebrew/bin` must be on `PATH` or the binary is at
`/opt/homebrew/opt/container/bin/container`; and `brew services start
container` is an alternative to `container system start`.

### AC-06 — MEDIUM — step 4A's expected output is wrong twice

**Claim 1:** *"a status line reporting the service is running."* Actual is a
nine-row table:

```
FIELD              VALUE
status             running
appRoot            /Users/you/Library/Application Support/com.apple.container/
installRoot        /opt/homebrew/Cellar/container/1.2.0/
logRoot
apiserver.version  container-apiserver version 1.2.0 (build: release, commit: unspeci)
```

Blank `logRoot` and the truncated `unspeci` are Apple's own output, not
corruption — and an agent told to stop on anything unexpected may stop on them.

**Claim 2, the bigger one.** Nothing warns that the first `container run` does
substantial setup: a kernel fetch and a 65.8 MB init image behind a six-stage
ladder taking ~10s. A runbook whose preamble says *"stop and report"* on
unexpected output **must** show this, or the first person on the Apple path
gets a false stop on a healthy run.

### R2-01 — MEDIUM — step 8 cannot produce the skip lines it documents

Step 8's command is `cd ~/wringer && wring doctor`, but the three skippable
checks are exactly the repo-scoped ones — **from the clone they never skip**.
Nothing in the runbook shows the state it defines. The round-1 fix for D works
correctly; only the documentation cannot demonstrate it. Fix: add the
contrasting outside-a-repo transcript after the clone one.

### R2-02 — MEDIUM — the stub check names a command that cannot show the stub

`ls -la` cannot show it, because the stripped permissions are what stop you
reading it:

```
$ ls -la /Applications/Docker.app     →  ls: Permission denied
$ ls -ld /Applications/Docker.app     →  d---------  2 root  admin  64 ...
```

Fix: `ls -ld`, and show the expected shape. Two entries and 64 bytes is empty.

### R2-03 — MEDIUM — step 7H commits evidence bundles into the probe repo

7H hand-writes `.wringer.yaml` and never calls `wring init`, so the probe gets
no `.gitignore` and its `git add -A` stages the previous run's `.wringer/`.
After two runs: two commits, nine tracked evidence files, no `.gitignore`.
`wring init` gets this right — 7H bypasses the tool's own protection. On a
real repository this pattern would commit evidence into the user's history.
Fix: `printf '.wringer/\n' > .gitignore && git add calc.py .wringer.yaml
.gitignore`.

### R2-05 / R2-06 — MEDIUM — the scripts assume one developer's machine

`setup-selftest.sh:15` and `verify-published.sh:10` default `WORK` to
`/private/tmp/claude-501/-Users-marc-Claude/…`, and both `find … -delete`
under it — pointing a recursive delete at a path chosen for a different
machine. Fix: `${TMPDIR:-/tmp}/wringer-…`.

`setup-selftest.sh:16` prepends `$ROOT/.venv/bin`, which the rewritten step 3
no longer creates — the prepend was a no-op and the script found `wring` only
by falling through to `PATH`. Fix: prefer `~/.local/bin`, keep the venv as
fallback, and **fail loudly** with no `wring` rather than silently testing
whatever is on `PATH`. `SETUP.md:362`'s transcript shows a `.venv` path too.

### R2-08 — MEDIUM — the template guarantees a failing first `wring verify`

All three example gates are `make` targets, so in any repo without a Makefile
the first `wring verify` after `wring init` fails on a healthy tree:

```
✗ format failed      0.5s  (optional)
✗ lint failed        0.0s
make: *** No rule to make target `lint'.  Stop.
exit 1
```

Defensible, but the first thing a new user sees is red and exit 1, which reads
as "the tool is broken". Fix: a passing `placeholder` gate (`run: "true"`)
with the examples commented out, so `wring init && wring verify` exits 0 and
demonstrates the harness.

### AC-05 / AC-07 / R2-04 — LOW

`SETUP.md:31` says "v1.0+"; current is **1.2.0**, and the `images`→`image`
rename means the version matters. · Apple unpacks **every** architecture in
the index, so a 160 MB pull lands as ~470 MB; Docker unpacks only its
platform. · A 7H rerun emits `warning: re-init: ignored --initial-branch=main`
against `SETUP.md:91`'s blanket "idempotent is harmless"; guard with
`[ -d .git ] || git init -q -b main .`.

---

## 7. The Apple path, rewritten — drop-in text

Folds in AC-01, AC-04, AC-05, AC-06, AC-07.

### Replacing SETUP.md:31

```
- **Apple `container`** (1.2.0; the commands here were verified against
  1.2.0) — **macOS 26 on Apple silicon only.** **This path is not exercised
  in CI.** GitHub's macOS runners have no nested virtualization, so nothing
  automated ever runs it. It is verified by `wring doctor`, by the manual
  check in step 7, and by one field run on macOS 26.5.2 / arm64 on
  2026-08-05 — that is the whole of its coverage. If it breaks for you, that
  is a real bug worth reporting, not something you did wrong.
```

### Replacing step 4A in full

    ### Step 4A — Apple `container`

    ```bash
    container --version
    ```

    Correct output: a version line, `1.2.0` or later — e.g.
    `container CLI version 1.2.0 (build: release, commit: unspeci)`. The
    truncated `unspeci` is Apple's own output, not damage.

    `command not found` is **not** a dead end, but installing it is the
    human's call. Two routes, and the first is much lighter:

    - **Homebrew (preferred)** — a bottled `homebrew-core` formula, no admin
      password, installs into Homebrew's own prefix. It is a *formula*, not a
      cask:

      ```bash
      brew install container
      ```

      `container` then resolves if `/opt/homebrew/bin` is on your `PATH`;
      otherwise it is at `/opt/homebrew/opt/container/bin/container`.

    - **Signed package from Apple** — 95.9 MB, needs your admin password:
      <https://github.com/apple/container/releases>.

    Either way the install is **the human's to run**. Do not download or run
    an installer on their behalf.

    Start the service (idempotent — starting a started service is a no-op):

    ```bash
    container system start
    ```

    The formula also offers `brew services start container`, which
    additionally restarts it at login. Either is fine; pick one.

    Verify:

    ```bash
    container system status
    ```

    Correct output is a **table**, not a single line. The row that matters is
    `status  running`:

    ```
    FIELD              VALUE
    status             running
    appRoot            /Users/you/Library/Application Support/com.apple.container/
    installRoot        /opt/homebrew/Cellar/container/1.2.0/
    logRoot
    apiserver.version  container-apiserver version 1.2.0 (build: release, commit: unspeci)
    apiserver.commit   unspecified
    apiserver.build    release
    apiserver.appName  container-apiserver
    ```

    A blank `logRoot` is normal. If `status` reports stopped, run
    `container system start` once more and read its output. Do not loop.

### Replacing the Apple commands in step 5

    Apple container — note the subcommand is `image`, **singular**:

    ```bash
    container image pull ghcr.io/marcoakes/wringer:main
    ```

    Pulling an image you already have is a no-op. Apple `container` unpacks
    **every** architecture in the index, so this 160 MB pull lands as roughly
    470 MB on disk (amd64 and arm64 both); Docker unpacks only the platform it
    needs.

    Verify — Apple container:

    ```bash
    container image list | grep wringer
    ```

    Correct output: one row naming the image, e.g.
    `ghcr.io/marcoakes/wringer  main  2a9dd63bd91b`.

    > **`container images` does not exist.** With the plural you get
    > `Error: Plugin 'container-images' not found.` and exit 64 on the pull,
    > and *silence* on the list — the error goes to stderr, so `| grep` yields
    > nothing and looks like a failed pull. The error also tells you to go
    > hunting for a missing plugin; ignore that, it is the wrong diagnosis.
    > The subcommand is `image` (alias `i`).

### Replacing the Apple command in step 7

    Apple container:

    ```bash
    container run --rm --volume "$HOME/wringer-workspace:/workspace" --workdir /workspace ghcr.io/marcoakes/wringer:main --version
    ```

    Correct output: the same `wring 0.2…` line step 3 printed, this time from
    inside the container.

    **The first `container run` on a machine does extra setup work** — it
    fetches a kernel and a ~66 MB init image, behind a six-stage progress
    ladder. This is expected, happens once, and takes about ten seconds:

    ```
    [0/6] [0s]
    [1/6] Fetching image [0s]
    [2/6] Unpacking image [0s]
    [3/6] Fetching kernel [0s]
    [4/6] Fetching init image [0s]
    [4/6] Fetching init image 66% (3 of 4 blobs, 43.5/65.8 MB, 42.0 MB/s) [8s]
    [5/6] Unpacking init image [8s]
    [5/6] Unpacking init image for platform linux/arm64/v8 [8s]
    [6/6] Starting container [9s]
    wring 0.2.0
    ```

    Later runs skip stages 3 to 5 and start in under a second. No key is
    involved and no network call is made by `wring` itself — this proves the
    box starts and the mount resolves, and nothing more than that.

### Replacing the Apple line under "What good looks like"

    Apple container — same arguments, with Apple's flag spellings. `--user`,
    `-e`, `--volume` and `--workdir` all exist on `container run`:

    ```bash
    container run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
      --volume "$HOME/wringer-workspace:/workspace" \
      --workdir /workspace/probe ghcr.io/marcoakes/wringer:main verify
    ```

    Verified on Apple `container` 1.2.0: exits 0, and every file in the bundle
    lands owned by the invoking host user.

---

## 8. Patch set by file

| File | Findings | Change |
|---|---|---|
| `SETUP.md:31` | AC-05 | 1.0+ → 1.2.0, note field-verification date |
| `SETUP.md:91` | R2-04 | Note the rerun warning, or adopt the guarded `git init` |
| `SETUP.md:187-212` | AC-04, AC-06 | Step 4A rewritten (§7) |
| `SETUP.md:224-229` | R2-02 | `ls -la` → `ls -ld`, show expected shape |
| `SETUP.md:263-286` | AC-01, AC-07 | `image` not `images`; disk note; plural warning |
| `SETUP.md:314-323` | AC-06 | Step 7 Apple block, first-run ladder shown |
| `SETUP.md:331` | R2-03, R2-04 | Explicit `git add`, write `.gitignore`, guard `git init` |
| `SETUP.md:347-395` | R2-01 | Add the outside-a-repo transcript |
| `SETUP.md:362` | R2-06 | Transcript path → `~/.local/bin/wring` |
| `SETUP.md:464-475` | R2-03, AC-02 | Explicit `git add`; Apple flag spellings |
| `SETUP.md:491-496` | AC-02 | Three-runtime `--user` paragraph |
| `src/wringer/evidence.py:219-225` | AC-03 | `run_id` in UTC |
| `src/wringer/detect.py:62-65,72-86,270-301` | R2-07 | `Detection.seen`; blank-template renderer |
| `src/wringer/detect.py:286-293` | R2-08 | Passing placeholder gate, examples commented |
| `src/wringer/cli.py:314-315` | R2-07 | Summary line reflects what was found |
| `scripts/setup-selftest.sh:15-16` | R2-05, R2-06 | Portable `TMPDIR`; PATH plus a hard `wring` check |
| `scripts/verify-published.sh:10` | R2-05 | Portable `TMPDIR` default |

**Suggested commit split**, so each lands with its own test:

1. `fix(setup): container image, not container images` — AC-01 alone, ship first
2. `fix(setup): rewrite the Apple container path` — AC-04, AC-05, AC-06, AC-07
3. `fix(setup): --user is a Linux requirement, not a universal one` — AC-02
4. `fix(init): say what was found, not that nothing exists` — R2-07, R2-08
5. `fix(evidence): stamp run ids in UTC` — AC-03. Breaking; its own commit
6. `fix(scripts): stop hardcoding one developer's temp path` — R2-05, R2-06
7. `fix(setup): probe repo should not commit its own evidence` — R2-03, R2-04
8. `docs(setup): show doctor outside a repo; fix the stub check` — R2-01, R2-02

---

## 9. Test coverage to add

The round-1 guard in `tests/test_doctor.py` is the right pattern. Extend it.

**Cheap, runs anywhere in CI**

1. **Grep guards on SETUP.md** — `container images` never appears;
   `ls -la /Applications/Docker.app` never appears.
2. **Grep guard on `scripts/`** — no `claude-50[0-9]`, no
   `-Users-[a-z]*-Claude`. Catches R2-05 permanently.
3. **`run_id` timezone invariance** — the unit test in AC-03.
4. **Blank-template wording** — the two cases in R2-07.
5. **Fresh-init exit code** — `wring init && wring verify` exits 0 in an empty
   repo (R2-08).
6. **Extend `setup-selftest.sh`** — assert three `-` lines and three
   `"status": "skip"` entries outside a repo (R2-01); fail loudly with no
   `wring` on PATH (R2-06).
7. **7H hygiene** — run 7H twice, assert one commit and no tracked
   `.wringer/` (R2-03).

**Cannot run in CI — needs a manual macOS checklist.** Everything
Apple-specific: GitHub's macOS runners have no nested virtualisation, so
`container system start` cannot work there. Suggested: `docs/MANUAL_CHECKS.md`
with the Apple sequence, a place to record the host and date it last passed,
and a pointer from `SETUP.md:31`. §7 above is a first draft of that checklist.
The Docker-stub check (R2-02) belongs there too, since it needs a stub.

---

## 10. Appendix — `wring init` against real repositories

Step 4's purpose was to find out whether detection survives contact with a
codebase nobody designed it around. **It does.** The finding is a wording bug,
not a detection bug.

Two repos, neither with first-party tests — worth stating plainly, because it
bounds what this tested. One Python voice-interview project with
`pyproject.toml`, `uv.lock` and a `.venv` (its 5292 apparent test files are all
inside `.venv/site-packages` — dependencies, not its own suite); one plain
JS/HTML game with no `package.json`. Both produced a **byte-identical** blank
template and both failed identically at `make lint`.

What the run proved beyond detection:

- **Fail-fast works.** `lint` is required; when it failed, `test` never ran and
  `summary.md` recorded `test | skipped | —`.
- **Optional gates are marked, not fatal** — `format` shows `failed (optional)`.
- **Dirty-tree capture works, first time exercised.** The clean probe leaves
  `diff.patch` and `status.txt` at 0 bytes; a real repository with uncommitted
  work fills them (18396 and 102 bytes respectively).
- **`wring init` writes a `.gitignore` entry** — exactly the protection step 7H
  lacks (R2-03).

## 11. Appendix — the container evidence bundle, verbatim

```
$ container run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
    --volume "$HOME/wringer-workspace:/workspace" \
    --workdir /workspace/probe-clean ghcr.io/marcoakes/wringer:main verify
[0/6] … [6/6] Starting container [0s]
✓ check passed       0.0s

Evidence written to:
.wringer/runs/20260805-094741-56d0/
exit 0

$ ls -lan …/.wringer/runs/20260805-094741-56d0/
drwxr-xr-x  9 502  20   288 .
-rw-r--r--  1 502  20     0 diff.patch
-rw-r--r--  1 502  20   831 digests.json
-rw-r--r--  1 502  20  1027 evidence.jsonl
drwxr-xr-x  3 502  20    96 gates
-rw-r--r--  1 502  20   329 manifest.json
-rw-r--r--  1 502  20     0 status.txt
-rw-r--r--  1 502  20   420 summary.md
```

All seven documented artefacts present, every one owned by `502:20` — the host
user — written from a process running as uid 1000 inside the container.

```json
{
  "schema_version": "wringer.evidence.v1",
  "run_id": "20260805-094741-56d0",
  "started_at": "2026-08-05T09:47:41+00:00",
  "repo": {"root": ".", "head_sha": "d2fbf8cc…", "branch": "main", "dirty": false},
  "result": {"status": "passed", "failed_gate": null}
}
```

That `+00:00` against a host running at `+01:00` is AC-03.

---

## 12. Limits of this report

- **Docker was never exercised.** No Docker on this host. Every Docker command
  in `SETUP.md` remains unverified on macOS; CI covers Linux. Given AC-02
  showed mount behaviour is genuinely runtime-specific, Docker Desktop on
  macOS is now the largest untested surface.
- **One Apple host, one OS version** — macOS 26.5.2, arm64, `container` 1.2.0
  via Homebrew. The `.pkg` route was not tested.
- **The `probe` repository was not pristine** for some runs (that is R2-03), so
  `probe-clean` and `probe-noflags` were created fresh for the measurements.
- **No first-party test suite was ever run through a gate.** Neither real repo
  had one, so gate execution was proven only against `grep`, `make` and `true`.
- **The API key was never involved.** No step needed it; nothing read a shell
  profile, `.env` or a credential store.
- **`scripts/setup-selftest.sh` was read, not run.** R2-05 and R2-06 come from
  reading it.

---

## 13. Suggested order of work

1. **AC-01** — one word, unblocks the entire Apple path. Ship alone.
2. **R2-07** and **R2-08** — the `wring init` first-contact experience. This is
   what a new user meets first, and today it misinforms them and then fails.
3. **AC-02** — replace a false claim with a measured one.
4. **AC-03** — decide UTC now while the id format is still cheap to change.
5. **§7** — land the rewritten Apple path wholesale.
6. **R2-05, R2-06** — the scripts, with the §9 grep guards so they cannot
   regress.
7. **R2-01 to R2-04** — documentation accuracy and probe hygiene.
8. **§9** — the test coverage, and `docs/MANUAL_CHECKS.md` for what CI
   structurally cannot reach.

The through-line: this runbook's own claim is that every step should have a
gate. Most of these findings are steps whose gate had never been executed. §9
is the part that stops that recurring.
