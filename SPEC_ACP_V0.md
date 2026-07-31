# SPEC — the ACP worker seam (P1)

*Drafted 2026-07-31. Binding for the `acp:` worker form. Method names below
were verified against the live protocol schema at agentclientprotocol.com,
not recalled. [SPEC_RUN_V0.md](SPEC_RUN_V0.md) and
[SPEC_SUPERVISION_V0.md](SPEC_SUPERVISION_V0.md) are unchanged and still
bind everything the loop does around this seam.*

## Positioning

> **"Any model" stops being a convention and becomes a contract.**

Today a worker is a shell string, and swapping Claude Code for Codex means
rewriting that string and hoping the new CLI takes a prompt the same way.
ACP is an open JSON-RPC-over-stdio standard that a growing set of agents
already speak. Speaking it makes model choice a config line.

**Wringer is an ACP _client_. It is never the agent.** That distinction is
the whole neutrality position: Wringer supervises, the agent writes code.

## 1. Config — the second worker form

```yaml
run:
  worker:
    acp:
      command: claude-code-acp        # required; the agent binary
      args: ["--stdio"]               # optional
      env_passthrough: [ANTHROPIC_API_KEY]   # optional; NAMES only
  worker_timeout: 900
```

`worker` accepts **either** a string (today's shell form, unchanged
forever) **or** a mapping with exactly one key, `acp`. Both together, or
any other key, is a config error. Strict validation as everywhere else.

**Rules (binding):**

1. **No default command.** Same law as `run.worker` and `judge.endpoint`:
   Wringer runs the agent you wrote down, never one it guessed.
2. **`env_passthrough` names variables, never values**, and every named
   variable's value is folded into the redactor before the agent starts —
   so a key cannot reach a ledger even if the agent echoes it. Anything
   *not* named is not passed: the agent gets a minimal environment, not
   the operator's whole shell.
3. **The agent binary is never bundled or auto-installed by Wringer.**
   Absent binary → exit 2 naming what to install. (Consent-based install
   belongs to `wring start`, P4.)

## 2. The exchange, per iteration

One session per iteration — fresh context each lap, which is what makes
the loop's evidence honest rather than a conversation that drifts.

1. Spawn the agent as a subprocess, **own process group**, stdio piped
   (`gates.run`'s machinery, reused — this is the same seam a shell worker
   uses, so timeout, kill and drain behave identically).
2. `initialize` — send `protocolVersion` and `clientCapabilities`
   (declare `fs` read/write; **no terminal capability in v0**). Record the
   negotiated `protocolVersion` and `agentInfo` on the ledger.
3. `session/new` with `cwd` = the repo root. Keep the returned `sessionId`.
4. `session/prompt` with the brief's text as a single text ContentBlock —
   **the same brief file the shell worker gets**, so the two forms are
   comparable and the brief remains the single source of instruction.
5. Handle inbound requests while the turn runs:
   - `session/update` notifications — append a compact line per update to
     `iterations/NNN/worker.stdout.log`, so an ACP worker leaves the same
     shape of evidence a shell worker does.
   - `fs/read_text_file` / `fs/write_text_file` — **served, but bounded**:
     paths must resolve inside the repo root (no `..`, no symlink escape),
     or the request is refused with an error. Wringer is not obliged to
     help an agent write outside the tree it was pointed at.
   - `session/request_permission` — **auto-approve in v0, and record every
     approval on the ledger.** Rationale: the loop is already sandboxed by
     the container (P0) and bounded by the supervision invariants, and a
     prompt nobody is sitting at is not a safety control. An interactive
     policy is a later slice; the ledger is what makes the auto-approval
     auditable rather than invisible.
6. The turn ends on the `session/prompt` response; record its
   `stopReason`. **`stopReason` is recorded and never acted on** — exactly
   as a shell worker's exit code is. The evidence decides.
7. Kill the process group; drain bounded, as ever.

## 3. Failure handling — every case maps to something the loop knows

| What happens | What the loop sees |
|---|---|
| binary missing | exit 2 before the loop starts |
| handshake fails / unsupported protocolVersion | worker "failed", recorded, loop continues (evidence decides) |
| agent exits mid-turn | same as a shell worker crashing |
| turn exceeds `worker_timeout` | process group killed, `timed_out: true` |
| malformed JSON-RPC | logged, turn abandoned, treated as a failed worker turn |

**No new stop reasons, no new exit codes.** An ACP worker that produces no
change still trips `no_progress`; one that produces the same failure twice
still trips the breaker. The supervision invariants do not know or care
which worker form ran, and that is the point.

## 4. Evidence — additive only, `wringer.loop.v1`

`worker.started` gains **optional** keys, present only for ACP workers:
`worker_kind: "acp"`, `agent_name`, `agent_version`, `protocol_version`.
Absent = the shell form, which stays the default reading. A new optional
event, `worker.permission`, records each auto-approved permission request
(`iteration`, `tool`, `outcome`). Schemas and the drift test updated in the
same commit, per house rule.

## 5. Non-goals (binding)

Terminal capability · MCP server passthrough · `session/load` and resumed
agent sessions (a fresh session per iteration is deliberate) · interactive
permission policy · streaming updates to the console (the clean console is
the product) · multiple concurrent agents in one loop (that is the fleet's
job) · Wringer implementing the *agent* side of ACP.

## 6. Definition of DONE

- [ ] a scripted **fake ACP agent** (a Python script in `tests/`, speaking
      real JSON-RPC over stdio) drives a loop to convergence — no network,
      no real agent, no API key in CI
- [ ] the fake agent's `fs/write_text_file` is what fixes the planted bug,
      proving the file-op path end to end
- [ ] a path-escaping `fs/write_text_file` is refused and recorded
- [ ] an agent that exits mid-turn is recorded and the loop continues
- [ ] a turn exceeding `worker_timeout` is killed via its process group
- [ ] `stopReason` appears on the ledger and provably changes no decision
- [ ] a secret named in `env_passthrough` never appears in any artifact
- [ ] shell and ACP workers produce the same *shape* of loop evidence
- [ ] docs carry a real captured transcript of a loop converging over ACP
