# Deployment — running Wringer in a container

`wring` is a pure-Python CLI with one runtime dependency, so putting it in a
container buys nothing on its own. What it buys is a boundary around the
*gates*: the commands your repository declares, which `wring verify` runs
through a shell with whatever privileges the process has. That is the reason
this page exists.

One image serves all three runtimes below — Apple's `container` on macOS 26,
Docker or Podman anywhere, and Kubernetes — because all three consume
standard OCI images.

> **Not a captured transcript.** Other pages in this repo paste real output
> and say so. This one does not: it is the recipe for the image this slice
> publishes, and the commands are the ones to run rather than ones already
> run and pasted back. CI can exercise the Docker path; it cannot exercise
> the Apple-container path, because GitHub's macOS runners have no nested
> virtualization. On macOS, treat this page as a checklist you work through
> by hand.

## Why bother: the isolation gates never had

[SECURITY.md](../SECURITY.md) is blunt about the execution model:

> `wring verify` executes the commands a repository declares, through a
> shell, with your privileges.

`.wringer.yaml` is code, in the same way a `Makefile` is code. v0.1 named
sandboxing an explicit non-goal and told you to run the harness inside your
own container if you needed isolation now. This page is that container, made
official.

What running in a container actually gives you:

- Your home directory, SSH keys, cloud credentials, browser profiles, and
  the rest of your filesystem are not visible to a gate unless you mount
  them. Only `/workspace` is.
- A gate that fills a disk, forks endlessly, or eats memory hits the
  container's limits rather than your laptop's.
- Under Apple's `container`, each container is its own lightweight VM rather
  than a process group sharing your kernel. That is a better boundary than a
  namespace.

What it does **not** give you, stated plainly:

- **This is isolation, not a security boundary against a repository you
  chose to run.** A gate still executes arbitrary code. Container escapes
  exist. Read a stranger's `.wringer.yaml` before you run it — inside a
  container or not.
- The gate has full network access by default. Take it away when your gates
  do not need it (`--network none`, or a `NetworkPolicy` on Kubernetes) —
  many test suites do need it, which is exactly why it is not the default.
- The repository is mounted read-write, because the evidence bundle is
  written into it. Anything a gate can do to your working tree, it can still
  do.
- Redaction is unchanged and still only knows about values that are in the
  environment of the run. A credential a gate reads from a file and prints
  reaches the bundle in a container just as it does outside one.

## The image

```bash
IMAGE=ghcr.io/marcoakes/wringer:main
```

Pin by digest for now — **`:main` is the only tag CI publishes**, and it
moves on every commit. Version tags arrive with 0.2.0. Proving a change against a
moving harness is not proof. A digest (`@sha256:…`) is better still. The
published tags are whatever CI has pushed to the repository's package page —
check there rather than trusting this line.

Three things to know about what is inside:

- **It ships no coding agent.** Not Claude Code, not Codex, not any other —
  by decision, not oversight. Wringer drives a worker you declare; it is
  never the worker, and it does not distribute somebody else's.
- **It is Wringer, not a build environment for your repo.** A gate that runs
  `pytest -q` needs pytest present. Either extend the image
  (`FROM ghcr.io/marcoakes/wringer:main`, add your toolchain) or make the
  first gate the one that installs it. `git` must be present in whatever
  image you end up with — `wring verify` shells out to it.
- Both entry points are installed: `wring` and `wringer`. The rest of this
  page uses `wring`.

## The workspace, and why git history has to come with it

Mount your repository at `/workspace` and make that the working directory.
The mount has to include the `.git` directory, and this is not incidental:

- `wring verify` **refuses to run outside a git repository** and exits `2`.
  A verification claim with no commit behind it is a claim about nothing.
- The manifest records HEAD's SHA, the branch and the dirty flag;
  `evidence.jsonl` carries a `git.status` event; `diff.patch` and
  `status.txt` are git output. Strip the history and the bundle loses the
  answer to "verified *what*, exactly".
- It also refuses (exit `3`) mid-merge, rebase, cherry-pick, revert or
  bisect — including one you started on the host, since it is the same tree.

Three ways this goes wrong in practice:

1. **Mounting a subdirectory.** Mount the directory that contains `.git`,
   not `src/` inside it.
2. **Copying the tree instead of mounting it.** `COPY` in a Dockerfile with
   `.git` in `.dockerignore`, or an exported tarball, produces a workspace
   with no repository in it. Mount, or clone into the volume.
3. **A `.git` that is a file, not a directory** — a git worktree or a
   submodule. It points at a gitdir somewhere else, which must be mounted
   too or git cannot resolve it.

Shallow clones are fine: `wring verify` compares the working tree against
HEAD, and `--depth 1` still has a HEAD.

One ownership footgun, common to every runtime here: git refuses to operate
on a repository owned by a different user (*"detected dubious ownership"*).
Either run the container as the UID that owns the checkout, or tell git the
directory is fine:

```bash
--env GIT_CONFIG_COUNT=1 \
--env GIT_CONFIG_KEY_0=safe.directory \
--env GIT_CONFIG_VALUE_0=/workspace
```

`wring verify --output` can send the bundle to a different mount, but the
repository itself still needs to be writable in practice — git refreshes its
index during `status`, and a read-only `.git` can fail on the lock file.

## The API key

Wringer handles no credentials of its own. A key matters in exactly two
places: `wring judge --send`, when your repo declares a `judge:` section with
an `api_key_env`, and whatever worker command you declare for `wring run`.
**`wring verify` makes no network call and needs no key at all.**

Pass it by environment variable at launch, using the pass-through form —
the name only, no value:

```bash
export ANTHROPIC_API_KEY=...        # in your own shell, typed by you
docker run --rm --env ANTHROPIC_API_KEY ... "$IMAGE" wring verify
```

`--env NAME` copies the value from your ambient environment. `--env
NAME="$NAME"` also works and is worse: the value lands on the command line,
where `ps` and your shell history can see it.

Three rules that do not bend:

- **Never bake a key into the image.** A layer keeps it forever, and anyone
  who pulls the image gets it.
- **Never inline a key in a manifest**, a committed `--env-file`, or
  anything else that goes into git. On Kubernetes it comes from a Secret,
  referenced by name — see [`deploy/k8s-job.yaml`](../deploy/k8s-job.yaml).
- **Never hand a key to a coding agent.** Not pasted into a chat, not
  written to a file for one to read, not relayed. You type it into your own
  shell or your own secret store. An agent setting Wringer up for you never
  needs to see it, and the flow is built so it never does. There is no
  interactive prompt today — the environment variable is how a key reaches
  the container.

What Wringer does with it once it is there: the redactor is built from the
environment before anything is written, so the *value* of any variable whose
*name* matches `*TOKEN*`, `*SECRET*` or `*KEY*` — plus the exact name given
in `judge.api_key_env`, whatever it is called — is replaced with
`[REDACTED]` in gate logs, `diff.patch`, `status.txt`, recorded commands and
`evidence.jsonl`. That happens before the write, not as a cleanup pass. It
is why `ANTHROPIC_API_KEY` is a good name for the variable and `MY_CREDS`
is a bad one.

## Apple container (macOS 26, Apple silicon)

Apple's `container` is 1.0 and consumes standard OCI images, so it runs the
same image as everything else. It is macOS 26 and Apple silicon only.

```bash
container system start                    # once per boot

container run --rm \
  --volume "$PWD:/workspace" \
  --workdir /workspace \
  --env ANTHROPIC_API_KEY \
  "$IMAGE" wring verify
```

The flag names mirror Docker's, but the surface is narrower and still
moving. If one of these is rejected on your version, `container run --help`
is the authority — what matters is the shape: mount the repository, set the
working directory to it, pass the key by environment. On builds without a
`--volume` flag, `--mount source=…,target=…` is the equivalent; on builds
without bare `--env NAME` pass-through, use `--env NAME="$NAME"` and accept
that the value is on the command line.

`container run` pulls the image if it is not already local. The image must
have an `arm64` variant — a multi-arch manifest covers this, but an image
built `linux/amd64` only will not run here.

Nothing about this path runs in CI. If it breaks, it breaks for you first.

## Docker (or Podman)

```bash
docker run --rm \
  --volume "$PWD:/workspace" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  --env ANTHROPIC_API_KEY \
  "$IMAGE" wring verify
```

`podman run` takes the same arguments.

`--user "$(id -u):$(id -g)"` matters more than it looks: without it the
bundle under `.wringer/runs/` is written into your repository owned by
`root`, and you will be deleting it with `sudo` for the rest of the week. It
also sidesteps the git ownership check, because the container is then the
same user that owns the checkout.

Worth adding when your gates allow it:

```bash
  --network none \                        # gates that need no network
  --memory 2g --cpus 2 \                  # a runaway gate hits this, not your laptop
  --read-only --tmpfs /tmp \              # only /workspace stays writable
```

Exit codes pass straight through `docker run`, so the contract is unchanged:
`0` all required gates passed · `1` a required gate failed · `2` config or
environment error · `3` refused · `4` interrupted. `wring verify --json`
still prints exactly one object, which is the form to use when something
else is consuming the result.

## Kubernetes

[`deploy/k8s-job.yaml`](../deploy/k8s-job.yaml) is a minimal Job: one
`wring verify` over a workspace volume, non-root, resource-limited, with the
API key referenced from a Secret by name.

```bash
kubectl apply -f deploy/k8s-job.yaml
kubectl logs -f job/wring-verify
```

Read the comments in it before applying — two of them are about what a gate
is allowed to do to your cluster. The short version:

- `automountServiceAccountToken: false`. A gate is arbitrary code from a
  repository; do not hand it a credential that talks to the API server.
- `backoffLimit: 0`. A failing gate is a verdict, not a flake. Retrying it
  writes a second bundle that says the same thing.
- The workspace is a `PersistentVolumeClaim` you populate yourself — a clone
  in an `initContainer`, a CI step, or a volume you already keep working
  copies on. It must contain `.git`, per the section above.
- The Secret is referenced with `optional: true`, because `wring verify`
  does not need a key. Drop that once something in the Job does.

## Which should I use

| | Use it when | What it costs |
|---|---|---|
| **Apple `container`** | You are on macOS 26 / Apple silicon and want per-container VM isolation without running Docker Desktop | Youngest of the three, macOS-only, and the one path CI cannot exercise |
| **Docker / Podman** | Everywhere else, and for anything scripted — this is the ordinary answer | Shared kernel: isolation, not a boundary |
| **Kubernetes** | You already have a cluster, and want verify running beside CI, on a schedule, or across many repos at once | The most setup, and the workspace becomes a volume problem you have to solve |

If you are not sure, use Docker. If you are on a Mac and the point of the
exercise is keeping an unfamiliar repository's gates away from your home
directory, use Apple's `container`.

## What comes back

Identical to a local run, because it is the same code path: a bundle at
`.wringer/runs/<run_id>/` inside the workspace — which is inside your
repository on the host, since the mount is live. `manifest.json`,
`evidence.jsonl`, `summary.md`, `diff.patch`, `status.txt`, and per-gate
`stdout.log` / `stderr.log` / `result.json`.

`.wringer/` is gitignored by the template `wring init` writes. Keep it that
way, and keep reading a bundle before you attach it to a public issue — a
container changes neither of those.

## Linux: run as your own user

A bind-mounted directory keeps its **host** ownership inside the container,
and Wringer writes its evidence bundle into that mount. The image runs as a
non-root user (uid 1000), so on Linux — where uids are not remapped — a
workspace owned by any other uid is read-only to Wringer, and `wring doctor`
will tell you so rather than failing later and mysteriously:

```bash
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD:/workspace" ghcr.io/marcoakes/wringer:main verify
```

Docker Desktop on macOS and Apple's `container` map ownership for you, so
this flag is harmless there and unnecessary. When in doubt, run
`wring doctor` first — the workspace check exists precisely for this.

