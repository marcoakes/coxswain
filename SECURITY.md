# Security

Wringer is young software (`0.1.0`). Read this before running
`wring verify` in a repository you did not write.

## Reporting a vulnerability

Use GitHub's private reporting: **Security → Advisories → Report a
vulnerability** on
[this repository](https://github.com/marcoakes/wringer/security/advisories/new).
That channel is private to the maintainer. Please do not open a public
issue for anything exploitable.

Expect an acknowledgement within a week. There is no bounty; there is
credit in the advisory unless you prefer otherwise.

Non-sensitive hardening ideas are welcome as normal
[issues](https://github.com/marcoakes/wringer/issues).

## `.wringer.yaml` is code

**`wring verify` executes the commands a repository declares, through a
shell, with your privileges.** That is the design — a gate is `make lint`
or `pytest -q`, and Wringer claims no more authority than you typing it.
The consequence is the same as `Makefile`, `package.json` scripts, or a
`.pre-commit-config.yaml`:

> Cloning an untrusted repository and running `wring verify` in it runs that
> repository's chosen commands on your machine. **Read its `.wringer.yaml`
> first.**

Wringer does not sandbox gates *itself*, and it never will — a tool that ran
your commands somewhere other than where you pointed it would be lying about
what it verified. **The container is the answer**, and since 0.2 it is a
supported, documented one rather than a suggestion.

Run the harness in the published image and a repository's gates execute
inside that container's isolation instead of against your home directory:

```bash
docker run --rm -v "$PWD:/workspace" ghcr.io/marcoakes/wringer:main verify
```

The same image runs under Apple's `container` on macOS 26 and as a
Kubernetes Job — see [docs/deployment.md](docs/deployment.md).

**What that is and is not.** It is meaningful isolation: a gate that deletes
`$HOME`, installs packages, or scribbles outside the repo hits the
container's filesystem, not yours. It is **not** a security boundary against
a repository you have chosen to run and actively distrust. The container has
your workspace mounted read-write by design — that is where evidence goes —
so a hostile gate can still corrupt the tree you gave it, and container
escapes exist. Treat it as the difference between a mistake and a disaster,
not as permission to run untrusted code.

Two things it does refuse. It will not verify outside a git repository
(exit `2`), because a verification claim with no commit behind it is
meaningless; and it will not verify while a merge, rebase, cherry-pick,
revert or bisect is half-finished (exit `3`), because the tree then
describes a state nobody chose. A gate id is also validated as a slug, so a
config cannot use it to write outside the run directory.

## What the evidence bundle contains

A bundle (`.wringer/runs/<run_id>/`) captures each gate's **full stdout and
stderr**, its command string, the repo's HEAD SHA, branch and dirty flag.

**Secrets are redacted before anything is written.** The values of
environment variables whose names match `*TOKEN*`, `*SECRET*` or `*KEY*` —
plus any pattern the repo adds under `evidence.redact.env` — are replaced
with `[REDACTED]` in gate logs, `diff.patch`, `status.txt`, recorded
commands and `evidence.jsonl`. This happens *before* the write, not as a
cleanup pass: the raw value never reaches the file. That is why gate output
travels through a pipe instead of straight to a file descriptor.

**What redaction does not do.** It knows about values that are in the
environment of the run. It cannot know about:

- a credential your gate reads from a file (or a vault) and then prints;
- a secret shorter than 6 characters, which is deliberately ignored — a
  two-character "secret" would match half the log and destroy the evidence;
- a token that appears only in a form the redactor never saw, e.g. base64 of
  the real value.

So the standing advice holds:

- `.wringer/` is gitignored by the template Wringer ships. Keep it that way.
- **Read a bundle before you attach it to a public issue or PR.**

Two further bounds on what a bundle can become: each captured stream is
capped (the tail is kept and the file states how many bytes were dropped),
and binary file contents never enter `diff.patch` — not even when the
repository's own `.gitattributes` defines a `textconv` driver that would
turn them into text.

## What Wringer never does

- **No network, with one command as the declared exception.**
  `wring verify`, `wring run`, `wring resume`, `wring fleet` and
  `wring explain` make no outbound connections — nothing is uploaded, phoned
  home, or telemetered, ever, by design, in every release.
  **`wring judge --send` is the exception, and it is opt-in three times
  over:** it exists only when your repo declares a `judge.endpoint`, it runs
  only when you type `--send` (the default builds the request and sends
  nothing), and it writes `request.json` — the exact bytes — to disk *before*
  it opens the socket, so what left the machine is auditable rather than
  asserted. Plain `http://` is refused to anything but loopback, redirects
  are not followed, and `judge.api_key_env` names a variable whose value is
  folded into the redactor so it cannot reach any artifact.
- **No writes outside the repo.** Evidence goes to `.wringer/runs/` under the
  detected git root. Gate ids are validated as slugs precisely so a config
  cannot direct a write outside the bundle.
- **No credential is ever read from a config file, stored, or relayed.** A repo names an environment *variable*; Wringer reads its value at runtime, folds it into the redactor so it cannot reach an artifact, and passes it to one request. Git's own credential helper answers for git — Wringer never sees that one at all.

  *Wringer never stores a credential.* `wring start` will ask for your API
  key so it can hand it to the build it launches; it keeps it in memory for
  that session, folds it into the redactor so it cannot reach a bundle, and
  writes it nowhere. Your config records the *name* of an environment
  variable, never a key. Nothing else in Wringer ever asks.

  There is deliberately **no `--key` flag**: a value on a command line is a
  process listing anyone on the machine can read. Its non-interactive form is
  the variable already being set, which is how every other command here
  receives one. And `wring start` prints the command to make it durable
  rather than running it — storing a credential is a larger power than
  launching a build.
- **Read-only git, except one command.** Wringer reads git state with read-only
  commands and never authenticates anywhere.

## Supported versions

Pre-1.0, **only the newest release and the tip of `main` are supported.**
Fixes land on `main` and reach you in the next release; nothing is
backported to an older one.

| Version | Supported |
|---|---|
| `main` | ✅ |
| `0.2.0` (PyPI, current) | ✅ |
| `0.1.0` (PyPI) | upgrade — `pip install -U wringer` |
| `*.dev*` (git installs) | reinstall from `main` or PyPI |

Upgrading from 0.1.0 needs nothing: `wring verify` behaves as it did, its
bundles stay readable, and every command added since is opt-in. See
[CHANGELOG.md](CHANGELOG.md).
