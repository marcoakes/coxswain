# Quickstart

> **Every transcript on this page is real** — one session in a scratch Python
> repo on 2026-07-30, captured and pasted unedited, in the order shown. The
> single clearly-marked block at the bottom is not built yet and says so.
>
> `pipx install wringer` from PyPI does **not** work yet — the package is
> unreleased. Install from git, as below.

## Install

Python 3.11+, macOS or Linux.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install "git+https://github.com/marcoakes/wringer"
```

That is the form verified for this page. `pipx install
git+https://github.com/marcoakes/wringer` puts `wring` on your PATH globally
and installs the same package.

## Declare your gates

`wring init` writes a commented `.wringer.yaml`:

```
$ wring init
Wrote .wringer.yaml — edit the gates to match this project, then run: wring verify
```

Edit it to your project's real commands. They run in your repo root, in the
order you list them — cheapest first:

```yaml
version: 1

gates:
  - id: lint
    run: ruff check .
    timeout: 60

  - id: test
    run: pytest -q
    timeout: 300
```

## Verify

```
$ wring verify
✓ lint passed        0.1s
✓ test passed        0.2s

Evidence written to:
.wringer/runs/20260730-160103-3547/
```

Exit code `0`. Now an off-by-one slips into `calc.py`:

```
$ wring verify
✓ lint passed        0.1s
✗ test failed        0.2s

--- gates/002_test/stdout.log ---
F                                                                        [100%]
=================================== FAILURES ===================================
___________________________________ test_add ___________________________________

    def test_add():
>       assert add(2, 2) == 4
E       assert 5 == 4
E        +  where 5 = add(2, 2)

test_calc.py:5: AssertionError
=========================== short test summary info ============================
FAILED test_calc.py::test_add - assert 5 == 4
1 failed in 0.01s

Evidence written to:
.wringer/runs/20260730-160105-830a/

Next:
  open .wringer/runs/20260730-160105-830a/summary.md
  rerun wring verify --gate test
```

Exit code `1`. Gate output is captured, never echoed: a passing run stays
quiet, and a failing one shows the tail of the log it wrote. `deploy`-style
gates listed after a required failure are not run at all.

## What it leaves behind

```
$ find .wringer/runs/20260730-160105-830a | sort
.wringer/runs/20260730-160105-830a
.wringer/runs/20260730-160105-830a/diff.patch
.wringer/runs/20260730-160105-830a/evidence.jsonl
.wringer/runs/20260730-160105-830a/gates
.wringer/runs/20260730-160105-830a/gates/001_lint
.wringer/runs/20260730-160105-830a/gates/001_lint/result.json
.wringer/runs/20260730-160105-830a/gates/001_lint/stderr.log
.wringer/runs/20260730-160105-830a/gates/001_lint/stdout.log
.wringer/runs/20260730-160105-830a/gates/002_test
.wringer/runs/20260730-160105-830a/gates/002_test/result.json
.wringer/runs/20260730-160105-830a/gates/002_test/stderr.log
.wringer/runs/20260730-160105-830a/gates/002_test/stdout.log
.wringer/runs/20260730-160105-830a/manifest.json
.wringer/runs/20260730-160105-830a/status.txt
.wringer/runs/20260730-160105-830a/summary.md
```

`summary.md` is the human's entry point:

````markdown
# wring verify — 20260730-160105-830a

- repo: **demo5** @ `d8970f8` (branch `main`, dirty)
- started: 2026-07-30T16:01:05+01:00
- result: **failed** — required gate `test` failed
- files: 1 changed ([diff.patch](diff.patch), [status.txt](status.txt))

| gate | status | duration | logs |
|---|---|---|---|
| lint | passed | 0.1s | [stdout](gates/001_lint/stdout.log) · [stderr](gates/001_lint/stderr.log) |
| test | failed | 0.2s | [stdout](gates/002_test/stdout.log) · [stderr](gates/002_test/stderr.log) |

Rerun the failing gate:

```
wring verify --gate test
```
````

`evidence.jsonl` is the machine's — append-only, one timestamped object per
line:

```json
{"type": "run.started", "ts": "2026-07-30T16:01:05.176+01:00", "run_id": "20260730-160105-830a", "wringer_version": "0.1.0.dev0", "repo": "demo5", "sha": "d8970f808ec2b607e764d941bab0656cccfcc83f"}
{"type": "git.status", "ts": "2026-07-30T16:01:05.177+01:00", "dirty": true, "changed_files": ["calc.py"]}
{"type": "gate.started", "ts": "2026-07-30T16:01:05.178+01:00", "gate_id": "lint", "command": "ruff check ."}
{"type": "gate.finished", "ts": "2026-07-30T16:01:05.311+01:00", "gate_id": "lint", "exit_code": 0, "duration_ms": 130}
{"type": "gate.started", "ts": "2026-07-30T16:01:05.312+01:00", "gate_id": "test", "command": "pytest -q"}
{"type": "gate.finished", "ts": "2026-07-30T16:01:05.553+01:00", "gate_id": "test", "exit_code": 1, "duration_ms": 240, "log": "gates/002_test/stdout.log"}
{"type": "run.finished", "ts": "2026-07-30T16:01:05.554+01:00", "status": "failed", "failed_gate": "test"}
```

And `diff.patch` is exactly what you were verifying:

```diff
diff --git a/calc.py b/calc.py
index 4693ad3..d3c55d1 100644
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,3 @@
 def add(a, b):
-    return a + b
+    # off-by-one slipped in here
+    return a + b + 1
```

Untracked files are listed in `status.txt` and the `git.status` event, not in
the patch — git cannot diff a file it has never seen, and pretending
otherwise would be a lie in an evidence bundle.

Exit codes are contract, and all five are live: `0` all required gates
passed · `1` a required gate failed · `2` config or environment error ·
`3` refused (see below) · `4` interrupted.

`wring verify` refuses with `3` when the tree is in the middle of a merge,
rebase, cherry-pick, revert or bisect — HEAD and the working tree then
describe a state nobody chose, and "passing" would be a claim about a commit
that does not exist yet. Finish or abort the operation, then verify.

Press Ctrl-C and you get `4`: the gate is stopped (it runs in its own process
group, so Wringer has to do that deliberately) and the partial bundle is
written and marked `interrupted` rather than abandoned half-finished.

## `wring explain` — what just happened

Reads the last run, or one you name. No LLM is involved: every line comes
straight out of the bundle.

```
$ wring explain
Run 20260730-160105-830a — failed
demo5 @ d8970f8 (branch main, dirty) · started 2026-07-30T16:01:05+01:00

✓ lint passed        0.1s
✗ test failed        0.2s

Failing gate: test
  command    pytest -q
  exit code  1

--- gates/002_test/stdout.log ---
F                                                                        [100%]
=================================== FAILURES ===================================
___________________________________ test_add ___________________________________

    def test_add():
>       assert add(2, 2) == 4
E       assert 5 == 4
E        +  where 5 = add(2, 2)

test_calc.py:5: AssertionError
=========================== short test summary info ============================
FAILED test_calc.py::test_add - assert 5 == 4
1 failed in 0.01s

Changed files (1):
  calc.py

Full report:
  .wringer/runs/20260730-160105-830a/summary.md

Rerun:
  wring verify --gate test
```

## For agents: `--json`

`wring verify --json` prints exactly one object and nothing else — no ✓ lines,
no log tails — so a coding agent can act on the result without parsing prose:

```
$ wring verify --json
{"status": "failed", "failed_gate": "test", "rerun": "wring verify --gate test", "evidence_dir": ".wringer/runs/20260730-160105-d217"}
```

Every key is always present, so a consumer never has to tell "passed" apart
from "the tool forgot to mention it": on a passing run `failed_gate` and
`rerun` are `null`. Exit codes are unchanged, and the full bundle is written
either way.

Everything else that works today:

```bash
wring verify --gate test        # one gate; its evidence keeps its declared number
wring explain .wringer/runs/<id>    # diagnose a specific run
wring --version
```

## ⚠️ `.wringer.yaml` is code

`wring verify` runs the commands the repo declares, through a shell, with your
privileges — exactly as if you had typed them. **Read a repository's
`.wringer.yaml` before running `wring verify` in it**, the same way you would read
its `Makefile`. See [SECURITY.md](SECURITY.md).

## Not built yet — arrives with `v0.1.0`

Everything above is real. This is **not implemented** and does not work if
you type it:

```bash
wring verify --changed-only  # gate only what changed
```

Also landing before the tag: real command detection in `wring init`,
`wring verify --output`, and `pipx install wringer` from PyPI. Progress is tracked in
[AGENTS.md](AGENTS.md); the release bar is the spec's
[Definition of PROVEN](SPEC_VERIFY_V0.md#definition-of-proven--the-repo-must-show-its-own-receipts).

## Secrets

Gate output is captured, so a tool that echoes a token would otherwise write
it into the bundle. Before anything is written, Wringer erases the *values*
of environment variables whose *names* match `*TOKEN*`, `*SECRET*` or
`*KEY*`, replacing each with `[REDACTED]`. Add your own patterns — the
defaults always stay on:

```yaml
evidence:
  redact:
    env:
      - "*PASSWORD*"
      - "*_URL"
```

This catches secrets that live in the environment, which is where most of
them are. It cannot catch a credential your gate reads from a file and
prints, so keep reading a bundle before you share it — see
[SECURITY.md](SECURITY.md).

Two other bounds on what a bundle can become: each captured stream is capped
(the tail is kept, and the file says how much was dropped), and binary file
contents never enter `diff.patch`.

## What it will never do

Write code (the harness never writes code — agents do), call any LLM, open
PRs, replace your CI, or upload anything anywhere. Evidence stays on your
disk; `.wringer/` is gitignored by the template.
