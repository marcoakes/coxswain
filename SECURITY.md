# Security

Coxswain is pre-release software (`0.1.0.dev0`). Read this before running
`cox verify` in a repository you did not write.

## Reporting a vulnerability

Use GitHub's private reporting: **Security → Advisories → Report a
vulnerability** on
[this repository](https://github.com/marcoakes/coxswain/security/advisories/new).
That channel is private to the maintainer. Please do not open a public
issue for anything exploitable.

Expect an acknowledgement within a week. There is no bounty; there is
credit in the advisory unless you prefer otherwise.

Non-sensitive hardening ideas are welcome as normal
[issues](https://github.com/marcoakes/coxswain/issues).

## `.cox.yaml` is code

**`cox verify` executes the commands a repository declares, through a
shell, with your privileges.** That is the design — a gate is `make lint`
or `pytest -q`, and Coxswain claims no more authority than you typing it.
The consequence is the same as `Makefile`, `package.json` scripts, or a
`.pre-commit-config.yaml`:

> Cloning an untrusted repository and running `cox verify` in it runs that
> repository's chosen commands on your machine. **Read its `.cox.yaml`
> first.**

Coxswain does not sandbox gates, and v0.1 will not. "Sandboxing beyond
recording current repo state" is an explicit
[non-goal](SPEC_COX_VERIFY_V0.md#non-goals-for-v010-binding) for this
release. If you need isolation now, run `cox verify` inside your own
container.

## What the evidence bundle contains

A bundle (`.cox/runs/<run_id>/`) captures each gate's **full stdout and
stderr**, its command string, the repo's HEAD SHA, branch and dirty flag.

**Until secret redaction lands (Day 4 of the [v0 spec](SPEC_COX_VERIFY_V0.md#build-order-bolts--plan-first-verify-each-before-the-next)),
assume a bundle contains whatever your gates printed** — including tokens
echoed by a misbehaving tool, connection strings in a stack trace, or a
`env`-dumping debug line. Two consequences today:

- `.cox/` is gitignored by the template Coxswain ships. Keep it that way
  until you have read what is inside a bundle.
- Do not attach a bundle to a public issue or PR without reading it.

Redaction (`*TOKEN*`, `*SECRET*`, `*KEY*` patterns applied **before**
write) and log-size truncation are specified and scheduled, not optional.

## What Coxswain never does

- **No network.** `cox verify` makes no outbound connections. Nothing is
  uploaded, phoned home, or telemetered — ever, by design, in every
  release.
- **No writes outside the repo.** Evidence goes to `.cox/runs/` under the
  detected git root. Gate ids are validated as slugs precisely so a config
  cannot direct a write outside the bundle.
- **No credentials handled.** Coxswain reads git state with read-only
  commands and never authenticates anywhere.

## Supported versions

Pre-1.0, only the tip of `main` is supported. There are no released
versions yet, so there is nothing to backport to; fixes land on `main`.

| Version | Supported |
|---|---|
| `main` | ✅ |
| `0.1.0.dev*` (git installs) | reinstall from `main` |
