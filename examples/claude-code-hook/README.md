# The agent loop, in about thirty lines of config

A [Claude Code](https://claude.com/claude-code) hook that runs `wring verify`
after the agent edits a file and hands the result back to it. Passing gates
say nothing. A failing gate stops the agent guessing and gives it the
evidence instead.

This is the v0.1 shape of what `wring run` will own in v0.2: **the agent is
the worker, `wring verify` is the gate, and the evidence bundle is what both
of them argue from.** Nothing here calls an LLM or uploads anything — the
hook only reads what `wring` already wrote to disk.

## Install

1. Copy the hook into your project and make it executable:

   ```bash
   mkdir -p .claude/hooks
   cp wring_hook.py .claude/hooks/
   chmod +x .claude/hooks/wring_hook.py
   ```

2. Merge [`settings.json`](settings.json) into your project's
   `.claude/settings.json` (or `.claude/settings.local.json` to keep it to
   yourself):

   ```json
   {
     "hooks": {
       "PostToolUse": [
         {
           "matcher": "Edit|Write",
           "hooks": [
             {
               "type": "command",
               "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/wring_hook.py",
               "timeout": 120
             }
           ]
         }
       ]
     }
   }
   ```

3. Make sure the repo has gates to run — `wring init` writes them from what
   your project already declares.

The hook no-ops when there is no `.wringer.yaml` and when `wring` is not on
`PATH`, so it is safe to leave configured in a repo that has not opted in.

## What the agent gets

Captured from a real run — a scratch Python repo with `pytest` as its one
declared gate, and `add()` quietly broken:

```
`wring verify` failed — this change is not mergeable yet.

Structured result:
{"status": "failed", "failed_gate": "test", "rerun": "wring verify --gate test", "evidence_dir": ".wringer/runs/20260730-225313-1228"}

Run 20260730-225313-1228 — failed
wheel-smoke @ e8b54e8 (branch main, dirty) · started 2026-07-30T22:53:13+01:00

✗ test failed        0.2s

Failing gate: test
  command    pytest -q
  exit code  1

--- gates/001_test/stdout.log ---
F                                                                        [100%]
=================================== FAILURES ===================================
___________________________________ test_add ___________________________________

    def test_add():
>       assert add(1, 2) == 3
E       assert -101 == 3
E        +  where -101 = add(1, 2)

tests/test_calc.py:5: AssertionError
=========================== short test summary info ============================
FAILED tests/test_calc.py::test_add - assert -101 == 3
1 failed in 0.01s

Full report:
  .wringer/runs/20260730-225313-1228/summary.md

Rerun:
  wring verify --gate test

Fix the failure above, then continue. The whole evidence bundle is on disk at
the evidence_dir named in the structured result — read it rather than guessing
at what broke.
```

Two things arrive together: the machine-readable verdict (`--json`, the same
object any agent or CI step can branch on) and the human-readable diagnosis
(`wring explain`, which is exactly what a person would read). The agent does
not need to re-run the suite to find out what broke, and the bundle is on
disk afterwards for whoever reviews the change.

## Cost, and the honest tradeoff

Running a whole test suite after every edit is the simple version, and for a
fast suite it is the right one. For a slow suite it will make every edit
expensive, and a hook that makes editing expensive gets switched off — which
proves nothing. Narrow it:

```bash
export WRINGER_HOOK_GATES=lint      # one gate; several are space-separated
```

Then keep the full run for a `Stop` hook or for CI, where waiting is free.

## One contract detail worth knowing

A `PostToolUse` hook **cannot block** — the tool has already run. Exiting
non-zero from one does not stop the agent or reliably reach it; it prints at
the human. The way to hand the model something it will act on is to exit
**0** and write this on stdout:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "..."
  }
}
```

That is what [`wring_hook.py`](wring_hook.py) does. If you want a gate that
genuinely *stops* an action, that is a `PreToolUse` hook, and a different
example. See the [hooks reference](https://code.claude.com/docs/en/hooks).

## What is and is not verified here

The hook was exercised exactly as Claude Code invokes it — payload on stdin,
stdout and exit code checked — across four cases: gates passing (silent, exit
0), a gate failing (exit 0 with valid `additionalContext` JSON, output above),
no `.wringer.yaml` (no-op), and malformed stdin (no crash). It has **not**
been run inside a live Claude Code session as part of this repo's automated
tests, because that would mean shipping an agent as a test dependency. If it
misbehaves in a real session, that is a bug worth [an issue](https://github.com/marcoakes/wringer/issues).

The same shape works for any agent that can run a command after an edit —
Codex CLI, Gemini CLI, a `watch` loop, a pre-commit hook. Claude Code is the
example because its hook contract is documented and stable, not because
Wringer is tied to it.
