# Quickstart

> **The transcripts on this page are real** — captured from `cox verify`
> running in a scratch Python repo on 2026-07-30 and pasted unedited. The
> one clearly-marked block at the bottom is not built yet and says so.
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

## One command, and the receipts

`cox init` writes a commented `.cox.yaml`. Edit the gates to match your
project — they are your commands, run in your repo root:

```bash
$ cox init
Wrote .cox.yaml — edit the gates to match this project, then run: cox verify
```

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

Then run the gates:

```
$ cox verify
✓ lint passed        0.1s
✓ test passed        0.2s

Evidence written to:
.cox/runs/20260730-122955-b740/
```

Now break something — here, `add` returns `a - b`:

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
E       assert 0 == 4
E        +  where 0 = add(2, 2)

test_calc.py:5: AssertionError
=========================== short test summary info ============================
FAILED test_calc.py::test_add - assert 0 == 4
1 failed in 0.01s

Evidence written to:
.cox/runs/20260730-123036-ec87/

Next:
  open .cox/runs/20260730-123036-ec87/summary.md
  rerun cox verify --gate test
```

Exit code is `1`. Gate output is captured, not echoed — a passing run stays
quiet, and a failing one shows you the tail of the log it wrote.

## What it leaves behind

```
$ find .cox/runs/20260730-123036-ec87 | sort
.cox/runs/20260730-123036-ec87
.cox/runs/20260730-123036-ec87/evidence.jsonl
.cox/runs/20260730-123036-ec87/gates
.cox/runs/20260730-123036-ec87/gates/001_lint
.cox/runs/20260730-123036-ec87/gates/001_lint/result.json
.cox/runs/20260730-123036-ec87/gates/001_lint/stderr.log
.cox/runs/20260730-123036-ec87/gates/001_lint/stdout.log
.cox/runs/20260730-123036-ec87/gates/002_test
.cox/runs/20260730-123036-ec87/gates/002_test/result.json
.cox/runs/20260730-123036-ec87/gates/002_test/stderr.log
.cox/runs/20260730-123036-ec87/gates/002_test/stdout.log
.cox/runs/20260730-123036-ec87/manifest.json
.cox/runs/20260730-123036-ec87/summary.md
```

`summary.md` is the human's entry point:

```markdown
# cox verify — 20260730-123036-ec87

- repo: **myrepo** @ `2077e9f` (branch `main`, dirty)
- started: 2026-07-30T12:30:36+01:00
- result: **failed** — required gate `test` failed

| gate | status | duration | logs |
|---|---|---|---|
| lint | passed | 0.1s | [stdout](gates/001_lint/stdout.log) · [stderr](gates/001_lint/stderr.log) |
| test | failed | 0.2s | [stdout](gates/002_test/stdout.log) · [stderr](gates/002_test/stderr.log) |
```

`evidence.jsonl` is the machine's — append-only, one object per line:

```json
{"type": "run.started", "run_id": "20260730-123036-ec87", "cox_version": "0.1.0.dev0", "repo": "myrepo", "sha": "2077e9f34e3ed769399baa3d364433c8b5a806e9"}
{"type": "gate.started", "gate_id": "lint", "command": "ruff check ."}
{"type": "gate.finished", "gate_id": "lint", "exit_code": 0, "duration_ms": 72}
{"type": "gate.started", "gate_id": "test", "command": "pytest -q"}
{"type": "gate.finished", "gate_id": "test", "exit_code": 1, "duration_ms": 185, "log": "gates/002_test/stdout.log"}
{"type": "run.finished", "status": "failed", "failed_gate": "test"}
```

Exit codes are contract: `0` all required gates passed · `1` a required gate
failed · `2` config or environment error. (`3` refused precondition and `4`
interrupted are reserved and not yet emitted.)

Other flags that work today:

```bash
cox verify --gate test   # run one gate; its evidence keeps its declared number
cox --version
```

## ⚠️ `.cox.yaml` is code

`cox verify` runs the commands the repo declares, through a shell, with your
privileges — exactly as if you had typed them. **Read a repository's
`.cox.yaml` before running `cox verify` in it**, the same way you would read
its `Makefile`. See [SECURITY.md](SECURITY.md).

## Not built yet — arrives with `v0.1.0`

Everything above is real. Everything in this block is **not implemented**;
it is the remainder of the [v0 spec](SPEC_COX_VERIFY_V0.md) and does not
work if you type it:

```bash
cox verify --json          # structured back-pressure for coding agents
cox verify --changed-only  # gate only what changed
cox explain                # compact non-LLM diagnosis of the last failure
```

Also landing before the tag: `diff.patch` and `status.txt` in the bundle,
secret redaction before write, log-size truncation, and `pipx install
coxswain` from PyPI. Progress is tracked in [AGENTS.md](AGENTS.md); the
release bar is the spec's
[Definition of PROVEN](SPEC_COX_VERIFY_V0.md#definition-of-proven--the-repo-must-show-its-own-receipts).

## What it will never do

Write code (the harness never writes code — agents do), call any LLM, open
PRs, replace your CI, or upload anything anywhere. Evidence stays on your
disk; `.cox/` is gitignored by default.
