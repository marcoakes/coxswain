# SPEC — the guided launch (P4)

*Drafted 2026-08-06 by the planning window, then revised against an
adversarial review that found four HIGH defects in the first draft — each is
now a ruling rather than an omission. **APPROVED by Marc 2026-08-06: rulings
1–5 decided under his standing delegation, and both §6 questions answered by
him directly. Binding. There are no approval pauses left in this slice.**
`SPEC_ACP_V0.md`, `SPEC_GET_V0.md`,
`SPEC_VERIFY_V0.md` and `SPEC_SUPERVISION_V0.md` bind; where this deviates
from any of them, §3c-i and §3e say so by name.*

## Positioning

> **"Set this up and start my first build."** — one command that gets a
> product manager from an installed binary to a verified change, without
> handing anyone a credential and without inventing a single command nobody
> wrote down.

`wring start` is the fourteenth command and the program's **first interactive
surface**. Everything else is a file edit between commands or a typed flag.
That is not incidental — it is what this spec has to buy carefully, because
an interactive command cannot be tested, cannot be recorded, and cannot run
in CI unless it is designed not to need a terminal at all.

## 1. What it does, in order

```
wring start
  1. preflight      wring doctor's checks, inline — never repairs
  2. workspace      where cloned repos go (no default, ever)
  3. repo in        EITHER a directory already on disk  -> continue to 4
                    OR a clone -> record it and STOP (§3e)
  4. gates          wring init's detection, shown for confirmation
  5. agent          which ACP agent drives the loop — detected, never assumed
  6. key            typed here, held in memory, never written down
  7. first build    wring verify, then the loop, then the receipt
```

Each step is idempotent, each prints what it decided, and each can be
supplied as a flag instead of asked — except the key, which is never a flag
(§3b, row 5). Step 7 ends on `wring attest`, so the last thing a new user
sees is a receipt a stranger could check offline.

## 2. Exit codes

The family's, nothing new (`AGENTS.md:229-236`): `0` the launch completed ·
`1` the first build's gates failed — a real answer, not a tool error · `2`
config or environment, **including "this is not a terminal and you did not
supply that answer"** · `3` refused: a precondition this command will not
overwrite, guess past, or run untrusted code for · `4` interrupted.

A failure in step 7's receipt — a bundle that cannot be attested — is `3`,
not `1`. `1` means the gates answered no; a receipt that cannot be produced
is a refused precondition, and conflating them would make the exit code lie
about which half failed.

`5` stays reserved for `wring judge` (`cli.py:43-45`). A command with prompts
does not need an exit code to ask for a human.

## 3a. The credential — BINDING (ruling 1)

**`wring start` prompts for the key, holds it in memory for the process it
launches, and writes it nowhere. Not to config, not to disk, not to the
ledger, not to a bundle, not to a process listing.**

`SETUP.md:598-603` flagged `wring start` as the future home of this step
without settling what it would do with the key — verbatim: *"When `wring
start` ships, this step becomes it; until then, the key is still the human's
to type and this is still their command, not the agent's."* This ruling
settles the question that note left open, and settles it the same way: the
key stays the human's to type.

**Why this does not weaken the promise.** The key has to travel from a
person's head into a process's environment; the only question is by which
route. Today that route is `read -rs` in the user's own shell
(`SETUP.md:583-587`). `wring start` uses the same mechanism — no echo, no
history — and is strictly *stronger* than the failure it exists to prevent: a
PM pasting the key into an agent's chat, which `SETUP.md:70-77` says requires
rotating the key. A prompt inside `wring` is the narrowest path that exists.

**Where the name goes, and it is one place.** The wizard writes the key's
variable name into **`run.worker.acp.env_passthrough`** and nowhere else.

It does **not** write `judge.api_key_env`. That key exists only under
`judge:` (`config.py:112-119`), and `_parse_judge` hard-requires `endpoint`,
`model` and `rubric` (`config.py:588-609`) — three values law 5 forbids
guessing and that §1 never collects. A wizard that emitted `api_key_env`
would either produce a config `config.parse` rejects, or invent an endpoint.
**Judging is not part of the launch**; the closing report names `wring judge`
as the next thing to configure and does not configure it.

**What stays true, and is enforced:**

- **Config records NAMES, never values.** `forge.token_env`,
  `judge.api_key_env` and `run.worker.acp.env_passthrough` keep their
  refusals verbatim (`config.py:400-408`, `611-619`, `782-790`).
- **The value is folded into the redactor before anything runs**, the way
  `cmd_judge` already does it (`cli.py:847`). Fold first, then act — the
  order is the guarantee, and a test fails if it is swapped.
- **The ACP log path must be scrubbed before this ships.** `acp.py:271`
  hands the child a raw file handle and `acp.py:322` writes updates with no
  scrub, unlike the shell path (`gates.py:167-180`). Those logs land in a
  bundle. Until that is fixed, a key passed to an agent can reach a bundle,
  and §8's "no bundle" box is unmeetable. It is a prerequisite of this
  ruling, not an adjacent nicety.
- **It is never persisted.** At the end, `wring start` prints the exact
  command to make it durable and runs neither. Storing a credential is a
  larger power than launching a build, and this slice was not granted it.
- **No vendor string in prose or output.** The variable name comes from the
  agent table (§3c), never a literal in the wizard's own text.

### 3a-i. `getpass` does not read stdin — the TTY gate is load-bearing

CPython's `getpass` opens **`/dev/tty`** directly and only falls back to
`sys.stdin` if that fails. So closing or redirecting stdin does **not** stop
it: a `getpass` call reached under the demo recorder would open the
operator's real terminal, print its prompt where the recording cannot see it,
and block forever — and the recorder cannot escape, because its read loop
exits only on pty EOF or child exit (`scripts/demo_record.py:112, 121`) and
its 30-second cap sits *after* the loop (`:132`).

**Therefore the `stdin.isatty()` gate of §3b is checked before `getpass` is
ever called, and that ordering is a safety property, not a style.** A test
runs the key step with stdin closed *and a controlling tty present* and
asserts exit 2 within a timeout — the shape that would hang if the gate were
removed.

### 3a-ii. The shell-worker asymmetry, named rather than inherited

A shell worker inherits the **operator's entire environment**
(`gates.py:95-102` passes no `env=`); an ACP worker gets `PATH`, `HOME`,
`LANG` plus named passthroughs only (`acp.py:255-262`). A wizard that wrote a
shell worker would silently hand the agent every secret in the shell.

**`wring start` writes an ACP worker or no worker at all.** If the user
declines every agent it writes no `run:` section and says why — it does not
fall back to a shell worker it invented.

## 3b. Interactivity — BINDING (ruling 2)

**Every answer has a non-interactive form. No TTY and a missing answer is
exit 2, never a guess and never a hang.**

| situation | behaviour |
|---|---|
| TTY, answers missing | prompt for exactly those |
| any answer given as a flag | use it, do not ask |
| **all** answers given non-interactively | run start to finish, no prompt |
| no TTY, a flag-answer missing | **exit 2**, naming the flag |
| **the key, non-interactively** | **satisfied by the named variable already being set in the environment; if it is unset and there is no TTY, exit 2 naming the variable** |

**The key is the one answer that is never a flag.** `--key <value>` is a
process listing, which §3a forbids in the same breath as the ledger and the
bundle. Its non-interactive form is the environment variable — which is
exactly how every other command in the program already receives a credential
(`cli.py:847`, `1034`, `1445`, `1518`).

`stdin.isatty()` is the test, and stdin specifically — not stdout. A
pipeline, a CI job and a recorder all present a non-interactive stdin while
stdout may still be a terminal.

**Why refuse rather than fall back.** A silent fallback is how a wizard
proceeds with defaults nobody chose — and this program has no defaults to
fall back to. Exit 2 naming the missing answer is the actionable refusal the
house standard requires (`SPEC_VACUITY_V0.md:133-140`).

### 3b-i. What this makes recordable, and what it does not

Measured, not assumed: **the demo recorder cannot film an interactive
session.** Three independent mechanisms, each verified in source:

1. **`getpass` bypasses stdin entirely** and would block on the operator's
   real terminal — §3a-i. This is the decisive one.
2. Child stdin is `subprocess.DEVNULL` (`scripts/demo_record.py:94`), so
   nothing can be fed to a prompt that *does* read stdin.
3. Capture is line-oriented (`:113-120`): a prompt printed without a trailing
   newline is not a frame of its own — it is buffered and **glued onto
   whatever line comes next**, or flushed only at exit. That produces a
   plausible-looking line no command ever printed, which is worse for law 8
   than an absence would be.

Marc has ruled that the launch GIF waits for P4, which makes P4's captured
transcript the GIF's script. So the transcript films **the non-interactive
surface** — a real `wring start` invocation, really executed, every byte
captured, nothing fabricated. That is also the **documented happy path**: the
north-star's flow is an agent running setup and launching `wring start` at
the end (`WRINGER_NORTHSTAR_PLAN.md:127-136`), and an agent passes flags.

**The key step is deliberately off-camera.** The recorded run has the
variable already set; `wring start` says so on the terminal, and the docs say
in words that the one step a film cannot honestly show is the one where a
human types a secret.

**"No recorder changes" means no new *capability*.** Adding a step function
to `scripts/demo_record.py` is expected — `main()` iterates a hardcoded tuple
(`:157`), so a new recorded command *requires* one, and it gets the
`_listing_step` display-equals-execute guard treatment. What is forbidden is
teaching the recorder to drive a pty or inject keystrokes: synthesised
keystrokes committed to `docs/demo.cast.json` would be fabricated evidence in
the one file law 8 forbids editing.

## 3c. Agent detection and consent — BINDING (ruling 3)

**`wring start` detects, proposes, and writes the worker stanza with consent.
It never installs anything, and it never assumes.**

- **Detection is `shutil.which` over a named table, and nothing cleverer.**
  Present on `PATH` = offered. Absent = named, with the exact install command
  printed for the human to run.
- **The table is the only place a vendor string appears**, per operating
  rule 5 (`AGENTS.md:327-329`) and the `forge.py` precedent: one module maps
  agent id → binary, args, the variable name it expects, its install command.
  The CLI says "the agent", never a product name, as it says "the forge" and
  never "GitHub" (`AGENTS.md:151`).
- **Identity is self-reported and recorded as such.** An ACP agent names
  itself in the `initialize` response (`acp.py:300-303`) and Wringer never
  verifies it. The docs say *recorded*, never *verified* — the distinction
  `SPEC_PROVENANCE_V0.md:91-109` already draws for commit signatures.
- **Consent is the written stanza.** The wizard shows the exact YAML it
  proposes and does not write until the human accepts (`--agent <id>` is that
  acceptance, given ahead of time). Nothing is written on decline.
- **Nothing already auto-approved changes.** In-flight
  `session/request_permission` stays auto-approved-and-recorded per
  `SPEC_ACP_V0.md:73-78`; this ruling covers the config-writing step only.

### 3c-i. Deviation: two documents say `wring start` installs. It does not.

**Both sources, named:**

- `WRINGER_NORTHSTAR_PLAN.md:148-151` — "`wring start` installs the user's
  choice with consent."
- `SPEC_ACP_V0.md:45-48` — an **in-repo binding spec**, whose rule this
  document's preamble says still binds: *"(Consent-based install belongs to
  `wring start`, P4.)"*

**This spec does not install.** Three reasons, the first decisive:

1. **The program already promises the opposite, in shipped strings a user can
   read.** `config.py:773-775` — *"Wringer never bundles or installs one"*;
   `acp.py:276-277` — *"Wringer never installs an agent — install the one you
   declared"*. Falsifying two live error messages to save one paste is the
   wrong trade, and law 8's spirit is that we correct claims rather than
   quietly contradict them.
2. **`SETUP.md:83-88` makes installing a runtime a stop condition** for the
   agent doing setup. It would be strange for the tool to take a power its
   own runbook denies the agent.
3. Running someone's package manager is a larger, less reversible power than
   anything else in this slice.

**Consequence, and it is a §8 box:** `SPEC_ACP_V0.md:47-48`'s parenthetical
must be struck or rewritten in the same commit as this ruling. A binding spec
that still promises the deferred feature is a contradiction, not a footnote.

**Marc confirmed this ruling on 2026-08-06** (§6.2), so the two shipped error
strings stay true and are not to be rewritten.

## 3d. What it will not overwrite — BINDING (ruling 4)

`wring init` refuses to overwrite an existing `.wringer.yaml`
(`cli.py:363-367`) and there is **no config writer in the program** —
`config.py` parses and never emits. So:

- An existing `.wringer.yaml` is **read, never replaced**. The wizard adds
  only absent sections, shows the diff, and refuses (exit 3) rather than
  rewriting a section the user wrote.
- Config emission is a new, tested seam. It must round-trip through
  `config.parse` before being written — a wizard that writes a config the
  parser rejects is a wizard that bricks a repo.
- The wizard keeps **no state of its own in `.wringer.yaml`**: unknown
  top-level keys are hard errors (`config.py:315-317`) and `version` must be
  exactly `1` (`:319-321`). There is no `start:` section, now or later.

## 3e. A clone is untrusted input — BINDING (ruling 5)

**`wring start` never runs gates in a repository it cloned in the same
invocation.** The clone path records provenance, prints the warning
`wring get` already prints, and **stops** — telling the human to read that
repo's `.wringer.yaml` and run `wring start` again inside it.

This is not caution invented here. It is three binding statements the first
draft of this spec walked straight through:

- `SPEC_GET_V0.md:85-87`, binding for the machinery being reused: *"Runs
  nothing it cloned. No gate, no hook, no install step — a fresh clone is
  untrusted input, and SECURITY.md's `.wringer.yaml`-is-code warning is
  exactly why."*
- `SECURITY.md:28-30`: cloning an untrusted repository and running
  `wring verify` in it runs that repository's chosen commands on your
  machine. **Read its `.wringer.yaml` first.**
- `AGENTS.md:340-344`: never widen that *"without a spec change and a
  SECURITY.md update."*

A guided launch that cloned and then executed would be the most dangerous
command in the program, aimed at the least technical user it has. The
second invocation costs one line of typing and is the entire safety property.

**A repo already on disk is different** — the human put it there, and every
other Wringer command already trusts that. Step 7 runs for that case.

### 3e-i. `wring start` becomes a fetch-capable command

Cloning makes it the third. `SPEC_GET_V0.md:174-180` and `AGENTS.md:193-202`
both enumerate the network surface exactly — three SEND commands, two FETCH —
and both enumerations become false the moment this ships. They are restated
in the same commit as the capability (§8), naming `wring start` and the one
condition under which it opens a socket: the user asked it to clone.

## 4. Ordering constraints, measured

- **Config precedes clone.** `wring get` requires `workspace:` in config or
  `--into` before it will clone (`cli.py:1383-1390`). §1's order reflects it.
- **A first build against a fresh template proves nothing.** The blank
  template ships a placeholder gate running `true` (`detect.py:28-47`), and
  `wring verify --json` reports `template_only: true` for exactly this reason
  (`cli.py:2100-2118`). **`wring start` must read that flag and say so.** A
  launch that ends "your first build passed" over a placeholder is a vacuous
  green produced by the onboarding flow — the failure this project exists to
  prevent. It reports the template state and names the next real step, and it
  does **not** attempt a receipt over it (§8 box 1).
- **Gates need the project's own toolchain.** `pytest: command not found` is
  the documented first failure (`QUICKSTART.md:36-41`). Surface it as a
  diagnosis, not a crash.

## 5. Rulings

1. **The credential — DECIDED: prompt, hold in memory, persist nothing; the
   name goes in `env_passthrough` and nowhere else.** Design in §3a. The key
   must reach a process somehow, and a no-echo prompt inside `wring` is the
   narrowest route that exists. `judge.api_key_env` is not written because
   judging is not part of the launch and law 5 forbids guessing the three
   values that section requires.
2. **Interactivity — DECIDED: every answer has a non-interactive form; the
   key's is an environment variable, never a flag; no TTY plus a missing
   answer is exit 2.** Design in §3b. Testable, CI-safe, and recordable —
   and the `isatty` gate is a safety property because `getpass` reads
   `/dev/tty` rather than stdin (§3a-i).
3. **Agent handling — DECIDED: detect, propose, write with consent; never
   install.** Design in §3c, deviation and its two sources at §3c-i.
4. **Overwriting — DECIDED: read, never replace; round-trip before write.**
   Design in §3d.
5. **Clones — DECIDED: clone and stop; never run a cloned repo's gates in
   the same invocation.** Design in §3e. Reinstates `SPEC_GET_V0.md:85-87`,
   which the first draft of this spec contradicted without noticing.

## 6. Marc's answers — DECIDED 2026-08-06

1. **The public promise wording — APPROVED as drafted.** This paragraph ships
   in README, SECURITY.md and SETUP.md **in the same commit as the
   capability**, per the J2 precedent (`WRINGER_NORTHSTAR_PLAN.md:152-156`).
   Verbatim, and a test asserts it is present:

   > *Wringer never stores a credential.* `wring start` will ask for your API
   > key so it can hand it to the build it launches; it keeps it in memory
   > for that session, folds it into the redactor so it cannot reach a
   > bundle, and writes it nowhere. Your config records the *name* of an
   > environment variable, never a key. Nothing else in Wringer ever asks.

   Note what changed and what did not: *"never touches a credential"* becomes
   *"never stores a credential"*. The narrower claim is the true one, and it
   is still the strongest claim in this category any comparable tool makes.

2. **§3c-i stands — `wring start` does NOT install an agent.** Marc confirmed
   2026-08-06. It names the agent and prints the exact install command; the
   human runs it. The two shipped error strings promising Wringer never
   installs one (`config.py:773-775`, `acp.py:276-277`) therefore stay true
   and must not be rewritten. `SPEC_ACP_V0.md:47-48`'s parenthetical is
   struck instead, per §8.

## 7. Non-goals (binding)

A TUI or curses interface — no runtime dependency may be added
(`AGENTS.md:76-77`) · storing credentials in a keychain (printed as a
command; revisit when a field report shows people losing the key between
sessions) · installing agents, runtimes or project dependencies · **running
gates in a repository cloned in the same invocation** (§3e) · a `start:`
config section · configuring a judge · resuming a partially-completed launch
(it is idempotent instead) · replacing `wring init`, `wring get` or
`wring doctor` — the wizard calls their machinery and never reimplements it ·
interactive permission policy for in-flight agent actions
(`SPEC_ACP_V0.md:76-78` defers it, and this slice does not take it) ·
Windows.

## 8. Definition of DONE

- [ ] `wring start` with every answer supplied non-interactively runs start
      to finish with no prompt, **in a repo with real detected gates**, and
      ends on a real `wring attest` receipt. (A template-only repo is a
      separate test and deliberately stops short of a receipt — §4.)
- [ ] the same invocation with stdin closed and one answer missing exits 2
      and names the missing answer; a test asserts the name is in the message
- [ ] **§3a** — the typed key appears in no file the wizard writes, no
      ledger, no bundle, no process listing; asserted by tests that grep for
      the value
- [ ] **§3a** — the wizard writes the key's variable name into
      `run.worker.acp.env_passthrough` and writes no `judge:` section at all
- [ ] **§3a** — the redactor is built before any step that could write, and a
      test fails if the order is swapped
- [ ] **§3a** — `acp.py`'s stderr handle and updates write path are scrubbed
      through the redactor like `gates.py:167-180`, with a test that plants a
      secret in agent output and greps the bundle
- [ ] **§3a-i** — a test runs the key step with stdin closed and a
      controlling tty present, and asserts exit 2 **within a timeout** — the
      shape that hangs if the `isatty` gate is removed
- [ ] **§3a-ii** — the wizard writes an ACP worker or no worker at all; never
      a shell worker
- [ ] **§3b** — no prompt is reachable when stdin is not a TTY; the whole
      surface runs with no terminal and does not hang
- [ ] **§3c** — an absent agent binary is named with its install command and
      nothing is executed; `grep -rn` shows no package-manager invocation in
      `src/`
- [ ] **§3c** — every vendor string lives in one module; a test asserts the
      CLI's own output contains no product name
- [ ] **§3c-i** — `SPEC_ACP_V0.md:47-48`'s "consent-based install belongs to
      `wring start`" parenthetical is struck or rewritten, same commit
- [ ] **§3d** — an existing `.wringer.yaml` is never overwritten; absent
      sections only; exit 3 rather than replacing one the user wrote
- [ ] **§3d** — every emitted config round-trips through `config.parse`
      before it is written
- [ ] **§3e** — a clone stops before any gate runs; a test asserts that a
      repo cloned by `wring start` has no run bundle afterwards
- [ ] **§3e-i** — `SPEC_GET_V0.md:174-180` and `AGENTS.md:193-202` restate
      the network surface with `wring start` in it, same commit
- [ ] **§4** — a launch whose first build ran against the placeholder
      template says so instead of reporting success
- [ ] docs carry a **captured** `wring start` transcript recorded through
      `scripts/demo_record.py` with no new recorder *capability*, and the
      docs state in words that the key step is not in the recording and why
- [ ] every line of the committed cast fits the renderer's fixed 80-column
      canvas (`scripts/demo_render.py:53`), asserted by a test
- [ ] README/SECURITY/SETUP carry the new promise wording, same commit as the
      capability
- [ ] `SETUP.md:598-603`'s "not built yet" note is replaced by the real thing
