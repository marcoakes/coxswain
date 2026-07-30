# Quickstart

> **Every transcript on this page is real** — one session in a scratch Python
> repo on 2026-07-30, captured and pasted unedited, in the order shown. The
> single clearly-marked block at the bottom is not built yet and says so.
>
> `pipx install coxswain` from PyPI does **not** work yet — the package is
> unreleased. Install from git, as below.

## Install

Python 3.11+, macOS or Linux.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install "git+https://github.com/marcoakes/coxswain"
```

That is the form verified for this page. `pipx install
git+https://github.com/marcoakes/coxswain` puts `cox` on your PATH globally
and installs the same package.

## Declare your gates

`cox init` writes a commented `.cox.yaml`:

```
$ cox init
Wrote .cox.yaml — edit the gates to match this project, then run: cox verify
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
$ cox verify
✓ lint passed        0.1s
✓ test passed        0.2s

Evidence written to:
.cox/runs/20260730-160103-3547/
```

Exit code `0`. Now an off-by-one slips into `calc.py`:

```
$ cox verify
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
.cox/runs/20260730-160105-830a/

Next:
  open .cox/runs/20260730-160105-830a/summary.md
  rerun cox verify --gate test
```

Exit code `1`. Gate output is captured, never echoed: a passing run stays
quiet, and a failing one shows the tail of the log it wrote. `deploy`-style
gates listed after a required failure are not run at all.

## What it leaves behind

```
$ find .cox/runs/20260730-160105-830a | sort
.cox/runs/20260730-160105-830a
.cox/runs/20260730-160105-830a/diff.patch
.cox/runs/20260730-160105-830a/evidence.jsonl
.cox/runs/20260730-160105-830a/gates
.cox/runs/20260730-160105-830a/gates/001_lint
.cox/runs/20260730-160105-830a/gates/001_lint/result.json
.cox/runs/20260730-160105-830a/gates/001_lint/stderr.log
.cox/runs/20260730-160105-830a/gates/001_lint/stdout.log
.cox/runs/20260730-160105-830a/gates/002_test
.cox/runs/20260730-160105-830a/gates/002_test/result.json
.cox/runs/20260730-160105-830a/gates/002_test/stderr.log
.cox/runs/20260730-160105-830a/gates/002_test/stdout.log
.cox/runs/20260730-160105-830a/manifest.json
.cox/runs/20260730-160105-830a/status.txt
.cox/runs/20260730-160105-830a/summary.md
```

`summary.md` is the human's entry point:

````markdown
# cox verify — 20260730-160105-830a

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
cox verify --gate test
```
````

`evidence.jsonl` is the machine's — append-only, one timestamped object per
line:

```json
{"type": "run.started", "ts": "2026-07-30T16:01:05.176+01:00", "run_id": "20260730-160105-830a", "cox_version": "0.1.0.dev0", "repo": "demo5", "sha": "d8970f808ec2b607e764d941bab0656cccfcc83f"}
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

Exit codes are contract: `0` all required gates passed · `1` a required gate
failed · `2` config or environment error. (`3` refused precondition and `4`
interrupted are reserved and not yet emitted.)

## `cox explain` — what just happened

Reads the last run, or one you name. No LLM is involved: every line comes
straight out of the bundle.

```
$ cox explain
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
  .cox/runs/20260730-160105-830a/summary.md

Rerun:
  cox verify --gate test
```

## For agents: `--json`

`cox verify --json` prints exactly one object and nothing else — no ✓ lines,
no log tails — so a coding agent can act on the result without parsing prose:

```
$ cox verify --json
{"status": "failed", "failed_gate": "test", "rerun": "cox verify --gate test", "evidence_dir": ".cox/runs/20260730-160105-d217"}
```

Every key is always present, so a consumer never has to tell "passed" apart
from "the tool forgot to mention it": on a passing run `failed_gate` and
`rerun` are `null`. Exit codes are unchanged, and the full bundle is written
either way.

Everything else that works today:

```bash
cox verify --gate test        # one gate; its evidence keeps its declared number
cox explain .cox/runs/<id>    # diagnose a specific run
cox --version
```

## ⚠️ `.cox.yaml` is code

`cox verify` runs the commands the repo declares, through a shell, with your
privileges — exactly as if you had typed them. **Read a repository's
`.cox.yaml` before running `cox verify` in it**, the same way you would read
its `Makefile`. See [SECURITY.md](SECURITY.md).

## Not built yet — arrives with `v0.1.0`

Everything above is real. This is **not implemented** and does not work if
you type it:

```bash
cox verify --changed-only  # gate only what changed
```

Also landing before the tag: secret redaction before write, log-size
truncation, binary exclusion from the diff, exit codes `3` and `4`, and
`pipx install coxswain` from PyPI. Progress is tracked in
[AGENTS.md](AGENTS.md); the release bar is the spec's
[Definition of PROVEN](SPEC_COX_VERIFY_V0.md#definition-of-proven--the-repo-must-show-its-own-receipts).

## What it will never do

Write code (the harness never writes code — agents do), call any LLM, open
PRs, replace your CI, or upload anything anywhere. Evidence stays on your
disk; `.cox/` is gitignored by the template.
