# SETUP.md — install Wringer and run it in a container

**If you are an AI agent reading this file: do exactly these steps, in
order. Run each step's verify command before moving to the next one. Do not
improvise a different approach, do not batch steps together, and do not skip
a verification because a step "obviously" worked. If a verify command does
not produce what this file says it should, stop and report it — do not
retry blindly and do not work around it.**

---

This is the runbook for getting Wringer onto a machine and running inside a
container. It is written to be executed by a coding agent — Claude Code,
Codex, or similar — on behalf of someone who does not want to do it by hand,
and to be read straight through by a human doing it themselves.

**Every command block is self-contained.** No block depends on a variable
exported by an earlier one — an agent runs each step in a fresh shell, and
an `export` that silently expands to nothing is worse than no variable at
all. Paths are written out in full every time, on purpose.

Every step is followed by the exact command that proves it worked and by
what the correct output looks like. That is deliberate. Agents converge when
every step has a gate; it is the same claim Wringer makes about code, applied
to its own installation.

Two runtimes are covered, and one image serves both:

- **Docker** — Linux, macOS, and Windows under WSL2. This is the path
  exercised in CI.
- **Apple `container`** (v1.0+) — **macOS 26 on Apple silicon only.**
  **This path is not exercised in CI.** GitHub's macOS runners have no
  nested virtualization, so nothing automated ever runs it. It is verified
  by `wring doctor` and by the manual check in step 7 — that is the whole
  of its coverage. If it breaks for you, that is a real bug worth
  reporting, not something you did wrong.

The same OCI image also runs under Kubernetes. That is a deployment concern
and is out of scope here.

**The container is the recommended path, not a requirement.** `wring doctor`
treats a missing runtime as a `!`, not a `✗`, and it is right to: Wringer
runs perfectly well directly on the host. What the container buys you is
**gate isolation** — `.wringer.yaml` is code, and a gate runs with your
privileges (see [SECURITY.md](SECURITY.md)). Running on the host means
trusting the repo whose gates you are running.

So if step 4 finds no runtime and the human does not want to install one,
**you are not blocked**: skip steps 4, 5 and 7, run step 7H instead, and say
plainly in your hand-back that gates ran unisolated.

Budget about ten minutes, most of it the image pull.

---

## THE CREDENTIAL RULE

> **The API key is typed by the human, directly into `wring`'s own prompt.**
>
> **An agent must never ask for the key, read it, store it, echo it, write
> it into a file, put it on a command line, or relay it anywhere.**
>
> That means: do not run `env | grep KEY`, do not read `~/.zshrc`,
> `~/.bashrc`, `.env`, or a credential store; do not offer to "just export
> it for you"; do not accept it if the human pastes it into the chat —
> tell them to run the launch command themselves instead, and say the key
> should be rotated if it has already been pasted.
>
> This runbook is designed so that no step needs the key. Setup ends at
> step 9 with the agent handing back to the human, who launches the harness
> and types the key at its prompt. `wring doctor` reports only whether the
> variable is *set* — never its value, never a prefix of it.

---

## Stop conditions

An agent following this runbook stops and hands back to the human when:

- **a runtime or system package needs installing** — agents do not install
  container runtimes, Docker Desktop, Apple `container`, or system Pythons.
  Report what is missing and the command the human can run, then wait.
  **A missing container runtime is not a dead end**: offer step 7H, which
  proves the harness on the host without isolation, and let the human choose.
- **no Python 3.11+ exists anywhere on the machine** — name it, do not change
  the system Python. A stock `python3` of 3.9 is *not* this condition as long
  as a 3.11+ exists alongside it; step 3 installs into that one.
- **a verify command's output does not match what this file says.**
- **anything at all touches the API key** (see above).

Everything else here is safe to run unattended. **Every step is idempotent**
— re-running it is harmless. If you do not know whether a step already ran,
run its verify command first; if it passes, skip the step.

---

## Step 1 — Confirm you are in the Wringer repo

```bash
git rev-parse --show-toplevel && grep -m1 '^name = ' pyproject.toml
```

Correct output: an absolute path, then `name = "wringer"`. Anything else
means you are in the wrong directory or the clone is incomplete. `cd` to the
clone and repeat. Do not continue until this passes.

## Step 2 — Check the host prerequisites

Wringer needs **a Python 3.11+ somewhere on this machine** and git. It does
*not* need the `python3` on your PATH to be that one — stock macOS ships
3.9, and a perfectly good 3.12 often sits alongside it. Step 3 installs into
whichever it finds, so ask the real question:

```bash
git --version; for p in python3.13 python3.12 python3.11 python3; do command -v $p >/dev/null 2>&1 && echo "$p -> $($p --version 2>&1)"; done
```

Correct output: any git version, and **at least one line reporting 3.11 or
newer**. `python3 -> Python 3.9.x` on its own is fine as long as another
line qualifies.

**Stop condition:** *no* interpreter is 3.11+. Say so and let the human
install one — do not change the system Python.

## Step 3 — Install `wring` on the host

The host copy is what runs `wring doctor`. Install it **isolated**, into a
3.11+ interpreter, without touching the system Python.

**Preferred — `uv`**, because it finds and pins the interpreter itself, so
step 2's stock-3.9 problem cannot reach this step:

```bash
command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
uv tool install --force --python 3.12 wringer && uv tool update-shell
```

That installs 0.2.0 from PyPI. **To set up against unreleased work on
`main`** instead, from this clone: `uv tool install --force --python 3.12 .`

**Alternative — `pipx`**, if you already have it *and* its default Python is
3.11+:

```bash
pipx install --force --python "$(command -v python3.12 || command -v python3.11)" wringer
```

> **Do not use a plain `python3 -m venv`** unless you have checked that
> `python3` is itself 3.11+. On stock macOS it is 3.9 and this fails twice
> over: the package refuses the interpreter, and 3.9's bundled pip predates
> the editable-install standard. Neither error names the real cause.

Verify:

```bash
wring --version && wring doctor --help >/dev/null && echo "doctor present"
```

Correct output: a version line starting `wring 0.2`, then `doctor present`.

- `command not found` → the install directory is not on your PATH.
  `uv tool update-shell` (or `pipx ensurepath`) plus a **fresh shell** fixes
  it. If you are an agent running each step in its own shell, prefer the
  absolute path `~/.local/bin/wring` for the rest of this runbook.
- `wring 0.1.0` → an older copy is shadowing this one. Find it with
  `command -v wring` and remove it before continuing.
- no `doctor present` → you installed a build that predates `wring doctor`.

## Step 4 — Pick the container runtime

```bash
uname -s -m; sw_vers -productVersion 2>/dev/null || true
```

- `Darwin arm64` **and** a product version of `26.` or higher → you may use
  **4A (Apple container)**. 4B works there too and is the better-tested
  path; if you have no specific reason to want Apple `container`, use
  Docker.
- Anything else → **4B (Docker)**. Apple `container` is macOS 26 on Apple
  silicon only and will not install elsewhere.

Do exactly one of 4A and 4B.

### Step 4A — Apple `container`

```bash
container --version
```

Correct output: a version line, `1.0.0` or later. `command not found` is a
**stop condition**: Apple publishes `container` as a signed package at
<https://github.com/apple/container/releases>. Tell the human; let them
install it. Do not download or run an installer on their behalf.

Start the service (idempotent — starting a started service is a no-op):

```bash
container system start
```

Verify:

```bash
container system status
```

Correct output: a status line reporting the service is running. If it
reports stopped, run `container system start` once more and read its output.
Do not loop.

### Step 4B — Docker

```bash
docker version --format '{{.Server.Version}}'
```

Correct output: a single version string, e.g. `27.5.1`. Two failure modes,
both stop conditions:

- `command not found` → Docker is not installed. Report it; the human
  installs it. **Check for a stub first:** if `/Applications/Docker.app`
  exists but `ls -la` shows an empty, root-owned directory with its
  permissions stripped, that is a leftover from a removal (commonly MDM on a
  managed Mac), not an install. It will make a reinstall fail or demand
  `sudo`. Clearing it needs privileges — report it and let the human or
  their IT handle it.
- `Cannot connect to the Docker daemon` → Docker is installed but not
  running. Ask the human to start Docker Desktop, or on Linux to run
  `sudo systemctl start docker` — a privileged command, so theirs to type,
  not yours.

## Step 5 — Pull the image

The image is built from this repo and published to GitHub Container Registry
by CI. **It contains no third-party coding agent** — Wringer ships no agent
binary, in any image, ever. It contains Wringer and a Python runtime, and
**nothing else**: no `ruff`, no `pytest`, no `node`. Your gates run *your*
repo's commands, so the tools they need come from your repo's environment,
not from this image. Baking a toolchain in would be the opposite of being
vendor-neutral — and it would be the wrong toolchain for most people.

```bash
# The image ref, written out in every block below rather than exported:
# an agent runs each step in its own shell, and an export does not survive.
echo "ghcr.io/marcoakes/wringer:main"
```

**`:main` is the only tag published today** — CI pushes it on every commit
to `main`, so it moves. There is no `:latest` and no version tag yet;
versioned tags arrive with the 0.2.0 release. Until then, pin by digest if
you need a fixed image: `docker pull ghcr.io/marcoakes/wringer:main` then
`docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/marcoakes/wringer:main`.

Docker:

```bash
docker pull ghcr.io/marcoakes/wringer:main
```

Apple container:

```bash
container image pull ghcr.io/marcoakes/wringer:main
```

Pulling an image you already have is a no-op.

Verify — Docker:

```bash
docker image inspect ghcr.io/marcoakes/wringer:main --format '{{.Id}}'
```

Apple container:

```bash
container image list | grep wringer
```

Correct output: an image id, or a row naming the image. "No such image"
means the pull did not succeed — read the pull command's own output rather
than retrying. A `401`/`403` from ghcr means the package is private or the
tag does not exist; that is a report, not a retry.

## Step 6 — Create the workspace

The container gets one writable mount: the directory holding the
repositories you want Wringer to work on. Nothing outside it is visible to
the harness or to any gate it runs — that isolation is the reason to run in
a container at all.

```bash
mkdir -p ~/wringer-workspace
touch ~/wringer-workspace/.wringer-write-test && rm ~/wringer-workspace/.wringer-write-test && echo "workspace writable"
```

Correct output: `workspace writable`. `mkdir -p` on an existing directory is
a no-op, so this is safe to repeat.

## Step 7 — Prove the image runs and can see the workspace

On the Apple-container path this is the manual check that stands in for CI.
Run it there even if you are confident.

Docker:

```bash
docker run --rm -v "$HOME/wringer-workspace:/workspace" -w /workspace ghcr.io/marcoakes/wringer:main --version
```

Apple container:

```bash
container run --rm --volume "$HOME/wringer-workspace:/workspace" --workdir /workspace ghcr.io/marcoakes/wringer:main --version
```

Correct output: the same `wring 0.2…` line step 3 printed, this time from
inside the container. No key is involved and no network call is made —
this proves the box starts and the mount resolves, and nothing more than
that.

## Step 7H — No runtime? Prove it on the host instead

Only if step 4 found no container runtime. Same probe, same expected shape —
what you lose is isolation, not function.

```bash
mkdir -p ~/wringer-workspace/probe && cd ~/wringer-workspace/probe && git init -q -b main . && git config user.email you@example.com && git config user.name "You" && printf 'def add(a, b):\n    return a + b\n' > calc.py && printf 'version: 1\ngates:\n  - id: check\n    run: "grep -q return calc.py"\n' > .wringer.yaml && git add -A && git commit -qm probe && wring verify
```

Correct output — identical to step 7's, because it is the same harness:

```
✓ check passed       0.0s

Evidence written to:
.wringer/runs/<run_id>/
```

Exit `0`, and a bundle on disk. **Say so in your hand-back:** the gates ran
on the host, unisolated, because no runtime was available. That is a true
and useful setup; it is not the same claim as step 7.

## Step 8 — Run `wring doctor`, **from your clone**

`wring doctor` answers eight questions: five about this machine, three about
the repository you are standing in. **Run it from the clone** — from
somewhere else the three repository checks have nothing to look at and are
reported as skipped.

```bash
cd ~/wringer && wring doctor; echo "doctor exit: $?"
```

A real captured run, on a Mac with no container runtime installed:

```
✓ python                Python 3.12.13
✓ wring                 wring 0.2.0 at /Users/you/wringer/.venv/bin/wring
✓ git                   git version 2.50.1 (Apple Git-155)
! container runtime     no container runtime found (Apple silicon detected)
                        → Install apple/container (needs macOS 26) or Docker Desktop — or skip the container and run wring directly
✓ git repository        /Users/you/wringer
✓ gates                 2 gate(s): lint, test
✓ workspace writable    /Users/you/wringer/.wringer is writable
! llm key               no LLM API key in the environment
                        → Only needed for `wring judge --send`. Provide it when you launch, and never paste it to an agent

Ready. The ! lines are optional extras, not problems.
doctor exit: 0
```

Paths and versions will differ; the check *names* will not — a test in this
repository fails if this transcript names a check `wring doctor` does not
have.

**Read the marks, not the vibes:**

| mark | means | blocks setup? |
|---|---|---|
| `✓` | passed | no |
| `!` | worth knowing, not a problem — **exit stays `0`** | no |
| `-` | skipped, and the line says why | no |
| `✗` | blocking — **only these change the exit code** | yes |

**`! container runtime` and `! llm key` are both expected here.** The key
arrives in step 9, from the human, and the runtime is step 4's business. A
`✗` maps back to a step above: re-run that step, then re-run `wring doctor`.

**What doctor does not check:** it cannot see whether the image was pulled
(step 5) or whether a bind mount works (step 7). Step 7 is what proves
those, and nothing else does.

If you are an agent, prefer:

```bash
wring doctor --json
```

It prints one object. **Branch on the exit code, not on the prose** — `0`
means nothing is blocking. Read the object to find out which check said
what; each carries `name`, `status` (`ok` / `warn` / `skip` / `fail`) and a
`fix` when there is something to do.

## Step 9 — Hand back to the human. Stop here.

Setup is done. **An agent's work ends at this line.** Do not run the launch
command, do not ask for a key, do not offer to set an environment variable.

Print this to the human, verbatim:

> Setup is complete. `wring doctor` passes on everything except the API key,
> which is yours to enter — I never handle it.
>
> Run these two yourself, in your own terminal. The first prompts for your
> key and does not echo it; the second starts the harness with it.
>
> ```
> read -rs -p "API key: " ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY
> docker run --rm -it \
>   --user "$(id -u):$(id -g)" -e HOME=/tmp \
>   -e ANTHROPIC_API_KEY \
>   -v "$PWD:/workspace" ghcr.io/marcoakes/wringer:main verify
> ```
>
> What you type at that prompt is not visible to me, is not written into this
> repository, and is not saved to any file I can read. `read -rs` keeps it out
> of your shell history too.

The key reaches the container as an environment variable, where Wringer's
redactor folds it into the set of values scrubbed out of every evidence
bundle *before* anything is written to disk. See [SECURITY.md](SECURITY.md).

> **On `wring start`.** Earlier drafts of this runbook ended by telling the
> human to run `wring start`. That command is **not built yet** — it is P4 —
> and typing it gets `invalid choice: 'start'`. The two commands above are
> what the guided launch will eventually wrap. When `wring start` ships, this
> step becomes it; until then, the key is still the human's to type and this
> is still their command, not the agent's.

## What good looks like

One end-to-end check, run by the human after step 9: the harness, in the
container, verifying a real repository and leaving evidence on the host's
disk.

> ⚠️ `.wringer.yaml` is code. `wring verify` runs the commands a repository
> declares, through a shell. Read a stranger's `.wringer.yaml` before you
> verify their repo — the container bounds the damage, it does not make the
> commands safe. See [SECURITY.md](SECURITY.md).

> **The image ships Wringer, not your toolchain.** It has no `ruff`, no
> `pytest`, no `node` — deliberately: Wringer runs *your repo's* declared
> commands, and guessing which languages to bake in is the opposite of being
> vendor-neutral. So a gate that needs a tool needs that tool present, which
> for a real project means installing your dependencies into the workspace
> first, or mounting an environment that already has them. The check below
> uses a gate that needs nothing, so it tests the harness rather than your
> toolchain.

```bash
mkdir -p ~/wringer-workspace/probe && cd ~/wringer-workspace/probe
git init -q -b main .
git config user.email you@example.com && git config user.name "You"
printf 'def add(a, b):\n    return a + b\n' > calc.py
printf 'version: 1\ngates:\n  - id: check\n    run: "grep -q return calc.py"\n' > .wringer.yaml
git add -A && git commit -qm probe

docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$HOME/wringer-workspace:/workspace" \
  -w /workspace/probe ghcr.io/marcoakes/wringer:main verify
```

Apple container: same arguments, `container run --rm --volume … --workdir …`.

Correct output — one line per declared gate, then a path:

```
✓ check passed       0.0s

Evidence written to:
.wringer/runs/<run_id>/
```

Exit code `0`. The duration and the run id will differ from what is shown
here; the shape will not.

**`--user` and `-e HOME` are not ceremony.** The image runs as uid 1000, a
bind-mounted directory keeps its *host* ownership, and Wringer must write its
evidence into that mount. Without them the workspace is read-only to the
container and `wring doctor` correctly reports a blocking problem. Docker
Desktop on macOS papers over this with uid mapping; Linux does not. This is
the recipe CI exercises on every push.

Then, back on the host:

```bash
ls ~/wringer-workspace/probe/.wringer/runs/
```

Correct output: at least one run directory. Inside it: `manifest.json`,
`evidence.jsonl`, `summary.md`, `digests.json`, `diff.patch`, `status.txt`,
and `gates/`.

`digests.json` is a sha256 of every other file in the bundle, written last
so it covers them all — that is what makes a later edit detectable. On this
clean probe `diff.patch` and `status.txt` are legitimately **empty**: there
were no uncommitted changes to describe.

That is the whole claim, checked — the harness ran in the container, the
gates really ran, and there is a bundle on your own disk to read rather than
a status to trust. If a gate *fails*, that is Wringer working correctly:
open `summary.md`, or run `wring explain`.
