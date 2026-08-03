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
- **Python on the host is older than 3.11** — name the problem, do not
  change the system Python.
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

```bash
python3 --version && git --version
```

Correct output: `Python 3.11.x` or newer, and any git version. Python 3.10
or older is a stop condition — Wringer requires 3.11+ and there is no
fallback.

## Step 3 — Install `wring` on the host

The host copy is what runs `wring doctor`, which is how every later step gets
checked. Install from **this clone**, not from PyPI — PyPI still carries
`0.1.0`, which has no `doctor`.

With pipx (preferred — puts `wring` on your PATH and keeps it out of the
system Python):

```bash
pipx install --force .
```

Without pipx:

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -e . && export PATH="$PWD/.venv/bin:$PATH"
```

`--force` and `-e` are what make this step idempotent: running it twice
reinstalls rather than failing.

Verify:

```bash
wring --version && wring doctor --help >/dev/null && echo "doctor present"
```

Correct output: a version line starting `wring 0.2`, then `doctor present`.

- `command not found` → the install directory is not on your PATH. After
  pipx, `pipx ensurepath` and a fresh shell fixes it; after the venv, the
  `export PATH=` above must be in the shell you are using.
- `wring 0.1.0` → an older copy is shadowing this one. Find it with
  `command -v wring` and remove it before continuing.
- no `doctor present` → you installed a build that predates `wring doctor`.
  Re-check that you ran the command from this clone's root.

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
  installs it.
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
export WRINGER_IMAGE="ghcr.io/marcoakes/wringer:main"
```

**`:main` is the only tag published today** — CI pushes it on every commit
to `main`, so it moves. There is no `:latest` and no version tag yet;
versioned tags arrive with the 0.2.0 release. Until then, pin by digest if
you need a fixed image: `docker pull ghcr.io/marcoakes/wringer:main` then
`docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/marcoakes/wringer:main`.

Docker:

```bash
docker pull "$WRINGER_IMAGE"
```

Apple container:

```bash
container images pull "$WRINGER_IMAGE"
```

Pulling an image you already have is a no-op.

Verify — Docker:

```bash
docker image inspect "$WRINGER_IMAGE" --format '{{.Id}}'
```

Apple container:

```bash
container images list | grep wringer
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
docker run --rm -v "$HOME/wringer-workspace:/workspace" -w /workspace "$WRINGER_IMAGE" --version
```

Apple container:

```bash
container run --rm --volume "$HOME/wringer-workspace:/workspace" --workdir /workspace "$WRINGER_IMAGE" --version
```

Correct output: the same `wring 0.2…` line step 3 printed, this time from
inside the container. No key is involved and no network call is made —
this proves the box starts and the mount resolves, and nothing more than
that.

## Step 8 — Run `wring doctor`

`wring doctor` is the machine-checkable precondition check: one line per
check, exit `0` when they all pass.

```bash
wring doctor; echo "doctor exit: $?"
```

Correct output: every check on its own line, all passing, then
`doctor exit: 0`.

If you are an agent, prefer:

```bash
wring doctor --json
```

It prints one object. **Branch on the exit code, not on the prose** — `0`
means every check passed. Read the object to find out which check did not.

The shape to expect (illustrative, not a captured transcript — check names
and order may differ; the contract is one line per check and exit `0` when
all pass):

```
✓ platform            macOS 26.0 (arm64)
✓ container runtime   docker 27.5.1
✓ image               ghcr.io/marcoakes/wringer:main present
✓ workspace           ~/wringer-workspace writable
✗ api key             ANTHROPIC_API_KEY not set
```

**A failing `api key` line at this point is expected, and it is not yours to
fix.** The key arrives in step 9, from the human. Every *other* failing
check maps back to a step above: re-run that step, then re-run
`wring doctor`.

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
  -w /workspace/probe "$WRINGER_IMAGE" verify
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
ls ~/wringer-workspace/wringer/.wringer/runs/
```

Correct output: at least one run directory. Inside it: `manifest.json`,
`evidence.jsonl`, `summary.md`, `diff.patch`, `status.txt`, and `gates/`.

That is the whole claim, checked — the harness ran in the container, the
gates really ran, and there is a bundle on your own disk to read rather than
a status to trust. If a gate *fails*, that is Wringer working correctly:
open `summary.md`, or run `wring explain`.
