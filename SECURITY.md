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

Wringer does not sandbox gates, and v0.1 will not. "Sandboxing beyond
recording current repo state" is an explicit
[non-goal](SPEC_VERIFY_V0.md#non-goals-for-v010-binding) for this
release. If you need isolation now, run `wring verify` inside your own
container.

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
- **No credentials handled.** Wringer reads git state with read-only
  commands and never authenticates anywhere.

## Supported versions

Pre-1.0, only the tip of `main` is supported. There are no released
versions yet, so there is nothing to backport to; fixes land on `main`.

| Version | Supported |
|---|---|
| `main` | ✅ |
| `0.1.0.dev*` (git installs) | reinstall from `main` |
