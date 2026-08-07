# A claim you can check without trusting anyone

*`wring attest` assembles the provenance claim. `wring audit` checks it —
offline, with no config, by someone who trusts nobody involved. Neither calls
an LLM. Neither opens a socket. There is no `--send` here and there never will
be.*

This is [SPEC_PROVENANCE_V0.md](../SPEC_PROVENANCE_V0.md) end to end. Every
block below is **real captured output** from a scratch repository with a
`file://` remote — reproducible, and nothing left the machine.

---

## The claim, stated whole

> Change **C** was **authorized** by spec **S**, **proven** by gates **G**
> with recorded results against tree **T**, **judged** against rubric **R**
> with verdict **V**, and **delivered** as branch **B** — and every bundle
> backing those clauses is byte-identical to when it was written.

A clause with no inputs is **absent, not invented**. The transcript below has
no spec and no verdict, so it makes three clauses and not five, and it is
still worth having.

## 1. Verify, then plan the delivery

```console
$ wring verify
✓ test passed        0.1s

Evidence written to:
.wringer/runs/20260806-093145-686f/

$ wring deliver
dry run — nothing was written to git.

Would create branch:  wringer/20260806-093145-686f
        targeting:    main
        with:         2 file(s)
```

## 2. Attest

```console
$ wring attest
Attested 20260806-093146-258e

  change         f99761b34632
  signed         N — no signature (git's word, never re-checked here)
  proven by      .wringer/runs/20260806-093145-686f — 1 gate(s) passed against f99761b34632
  delivered as   wringer/20260806-093145-686f -> main (dry_run)

! unsigned — this proves the named bundles are unaltered since they were written, not who produced them, and not that they were not fabricated wholesale.

Written to .wringer/attestations/20260806-093146-258e/
Check it yourself:
  wring audit .wringer/attestations/20260806-093146-258e/attestation.json
```

**That `!` line is the point of the feature as much as the artifact is.** The
word *attestation* sounds cryptographic, and a reader who assumes it means
"signed by someone" has been misled by a green thing that means less than it
looks like. So the limit is in the file, in `--json`, and on the terminal —
and it is a `!`, doctor's mark for *worth knowing, not a problem*, never a
`✗`. Nothing failed.

Delete that sentence from the artifact and `wring audit` refuses it. An
attestation stripped of its own caveats reads as a stronger claim than it is.

## 3. The artifact

```json
{
  "schema_version": "wringer.attestation.v1",
  "signature": null,
  "limits": [
    "unsigned — this proves the named bundles are unaltered since they were written, not who produced them, and not that they were not fabricated wholesale.",
    "digests.json cannot cover itself, so whoever owns the disk can rewrite everything consistently. This is tamper-evidence: a silent edit becomes a detectable one, and nothing more.",
    "..."
  ],
  "proven_by": {
    "run": ".wringer/runs/20260806-093145-686f",
    "head_sha": "f99761b34632…",
    "gates": [{"gate_id": "test", "status": "passed", "exit_code": 0}]
  },
  "change": {
    "commit": "f99761b34632…",
    "commit_signature": {
      "status": "N", "signer": null, "means": "no signature"
    }
  },
  "bundles": [
    {
      "role": "run",
      "path": ".wringer/runs/20260806-093145-686f",
      "digests_sha256": "8bb5d836608ca0e4…",
      "files": 9
    },
    {
      "role": "delivery",
      "path": ".wringer/deliveries/20260806-093145-c20a",
      "digests_sha256": "efe1ddc5f424a0de…",
      "files": 6
    }
  ]
}
```

**Bundles link to each other by path; the attestation re-anchors them by
digest.** `digests_sha256` is the sha256 of each bundle's own `digests.json`
*file*, recorded at attest time. From that moment the chain is
content-addressed even though the manifests only ever named paths — which is
what makes a *self-consistently* rewritten bundle (files and record edited
together) still fail an audit.

**`commit_signature` is free attribution where the repo already has it.**
Wringer touches no key and consults no trust store: it records `git log -1
--format=%G?` verbatim — `G` good, `B` bad, `U` untrusted, `N` none — and
`audit` reports it without re-verifying. A repo that signs its commits gets a
genuine chain for nothing; one that does not records `N` and loses nothing.

## 4. Between the two: `wring doctor`

Nothing about `attest` or `audit` needs a container, a key, or a network, and
`doctor` is where you see that stated rather than assumed. The two `!` lines
below are the only things this machine lacks, and neither is on the path:

```console
$ wring doctor
✓ python                Python 3.12.13
✓ wring                 wring 0.3.0 at /Users/marc/.local/bin/wring
✓ git                   git version 2.50.1 (Apple Git-155)
! container runtime     no container runtime found (Apple silicon detected)
                        → Install apple/container (needs macOS 26) or Docker Desktop — or skip the container and run wring directly
✓ git repository        …/wringer-capture-attest/repo
✓ gates                 1 gate(s): test
✓ workspace writable    …/repo/.wringer is writable
! llm key               no LLM API key set — looked for ANTHROPIC_API_KEY, OPENAI_API_KEY
                        → Only needed for `wring judge --send` and for an agent driving `wring run`; this repo declares no name, so those are the well-known ones. Provide it when you launch, and never paste it to an agent

Ready. The ! lines are optional extras, not problems.
```

Exit 0. The same `!` mark `attest` uses for its own limits line, and for the
same reason: worth knowing, not a problem.

## 5. Audit

```console
$ wring audit .wringer/attestations/20260806-093146-258e/attestation.json
✓ attestation.json verifies
  run       .wringer/runs/20260806-093145-686f  (9 files)
  delivery  .wringer/deliveries/20260806-093145-c20a  (6 files)

  2 bundle(s), 15 file(s) — every digest matches and every ledger chain is intact.

! unsigned — this proves the named bundles are unaltered since they were written, not who produced them, and not that they were not fabricated wholesale.
```

The limit is repeated **on success**, deliberately. A passing audit must not
read as a stronger claim than it is.

## 6. The money test — change one byte

Append two characters to a gate's stdout log. Nothing else reads that file
back; nothing else would ever notice.

```console
$ printf 'OK\n' >> .wringer/runs/20260806-093145-686f/gates/001_test/stdout.log

$ wring audit .wringer/attestations/20260806-093146-258e/attestation.json
✗ attestation.json does not verify

  20260806-093145-686f/gates/001_test/stdout.log does not match the digest 20260806-093145-686f recorded for it — that file has changed since the bundle was written
```

Exit 1, and it **names the file**. That is the whole product: not that the
evidence is unforgeable — it is not, and the artifact says so — but that
altering it silently is no longer possible.

## What attest refuses

Each one is a sentence saying why, exit 1, and each has a test that fails
when the refusal is removed — checked by disabling each in turn, not asserted:

- a referenced bundle has no `digests.json` — *cannot attest what cannot be
  checked*. Every pre-0.2 bundle is in this shape, including this repo's own
  committed `.wringer.example/`.
- any digest mismatch, in either direction: a file changed, or a file
  **added** to a bundle after it was written.
- any `prev_hash` chain break in any referenced ledger. That field was written
  on every event since 0.2 and read by nothing until now.
- a verdict whose `mode` is `dry_run` — nothing was judged, so the clause
  would be theatre.
- gates that did not pass. No attestation dresses up a failure.
- `wringer.spec.yaml` saying `approved: false`. `spec_sha256` hashes the file
  *without parsing it*, so an unapproved spec hashes exactly like an approved
  one — the interlock has to be read, not hashed.
- a run whose `vacuity.json` says `gates_vacuous`: its gates passed without
  the change too, so they proved nothing, and an attestation over that would
  be a cryptographic-sounding wrapper around a green tick that cannot fail.

**An honest refusal is the product.** `wring attest` on a doctored bundle
saying *no* is the demo.

## What it is not

Unsigned, by decision rather than omission
([SPEC_PROVENANCE_V0 §5](../SPEC_PROVENANCE_V0.md) ruling 1). Signing in v0
would force four answers nobody asked for, and the last of them is a signing
key in CI — which contradicts the product's most distinctive promise, that it
never touches a credential.

A signature, if one ever arrives, is the **sibling file**
`attestation.json.sig`, never a field inside the payload. That keeps v1 purely
additive: every v0 attestation stays valid byte-for-byte, `audit` gains one
more clause, and no format migration is ever needed. `wring audit` already
ignores a `.sig` it finds rather than choking on it — there is a test.
