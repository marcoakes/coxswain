# SPEC — tamper-evident provenance (P5, part 1)

*Drafted 2026-08-03 by the planning window. **APPROVED by Marc 2026-08-05 —
both rulings decided (§5). Binding.** Builds on machinery that already
ships: `digests.json` per bundle, `prev_hash` on every ledger,
`spec_sha256` in deliveries, the rubric's sha256 in verdicts.*

## Positioning

> **"Who wrote this code, under whose authority, verified how?" — answered
> by a file, checkable offline, by someone who trusts none of us.**

`wring attest` assembles the claim. `wring audit` checks it. Neither calls
an LLM and neither touches a network, **ever** — these commands *prove*
things, so they live on the never-reaches-a-network side of the line that
README draws. There is no `--send` here and never will be.

## 1. The claim, stated honestly

An attestation says exactly this, each clause anchored to a hash:

> Change **C** (commit sha) was **authorized** by spec **S** (sha256),
> **proven** by gates **G** with recorded results against tree **T**
> (head sha), **judged** against rubric **R** (sha256) with verdict **V**,
> and **delivered** as branch **B** — and every bundle backing those clauses
> is byte-identical to when it was written.

And it must say, in its own artifact, what it does **not** claim:

- **Not tamper-proof.** `digests.json` cannot cover itself; whoever owns
  the disk can rewrite everything consistently. This is tamper-*evidence*:
  a silent edit becomes a detectable one, nothing more. The attestation
  carries this sentence verbatim.
- **Worker identity is recorded, not proven.** The loop wrote down the
  worker command or the ACP agent's self-reported name/version. That is
  provenance of *configuration*, not identity attestation.
- **The clauses it lacks inputs for are absent, not invented.** No spec →
  no `authorized_by` clause. No verdict → no `judged_by`. An attestation
  over a bare `wring verify` bundle is small and still worth having.
- **Unsigned. It does not say who produced it.** v0 attestations carry no
  signature, so they prove the evidence is unaltered and say nothing about
  authorship (ruling 1). The artifact states this itself — see §1a.

## 1a. Saying the limit out loud — BINDING (ruling 1)

The word *attestation* sounds cryptographic, and a reader who assumes it
means "signed by someone" has been misled by a green thing that means less
than it looks like. That is the vacuity failure in a new costume, and this
project has already ruled once this week that a passing artifact must
narrate its own emptiness.

So the limit is **in the artifact and on the terminal**, not only in these
docs:

- `attestation.json` carries `"signature": null` and a `"limits"` array
  whose first entry is, verbatim: *"unsigned — this proves the named
  bundles are unaltered since they were written, not who produced them,
  and not that they were not fabricated wholesale."*
- `wring attest` prints that sentence as a `!` line — doctor's mark for
  "worth knowing, not a problem" — never a `✗`. Nothing failed.
- `wring audit` repeats it on success. A passing audit must not read as a
  stronger claim than it is.
- `--json` carries `signature` and `limits` too. An agent consuming this
  is exactly the reader most likely to over-read a bare `"ok": true`.

**Acceptance:** delete the limits sentence and a test fails.

## 1b. The signature seat — BINDING (ruling 1)

A signature is a **sibling file**, never a field inside a signed payload:

```
attestation.json          the claim
attestation.json.sig      v1, optional, absent in v0
```

This is the pattern this codebase has now used three times against frozen
schemas (`digests.json`, and `vacuity.json` in the sibling spec), and it is
what makes v1 signing purely additive: every v0 attestation stays valid
byte-for-byte, `audit` gains "and the signature verifies" as an extra
clause, and no format migration is ever needed. A signature embedded in the
payload would require canonicalising the JSON before signing — a class of
bug with a long history — and would break every attestation written before
it existed.

When signing does arrive it should be `ssh-keygen -Y`, for a reason that is
about adoption rather than cryptography: developers already have SSH keys,
and GitHub already publishes the public half at `github.com/<user>.keys`,
which solves key *distribution* — the genuinely hard part — for free.

## 1c. Free attribution, where the repo already has it — BINDING (ruling 1)

Wringer touches no key, and it can still carry real attribution for repos
that already sign their commits.

The attestation already names the delivered commit. It additionally
**records what git says about that commit's signature, as a fact, without
judging it**: `git log -1 --format=%G?` yields `G` (good), `B` (bad), `U`
(good, untrusted), `N` (none), and the attestation stores that character
and the reported signer verbatim under `commit_signature`.

- Wringer never verifies a signature and never consults a trust store —
  that is the verifier's job and their trust root, not ours.
- A repo with signed commits gets a genuine chain for nothing: signed
  commit → attestation names that commit → digests prove the bundle.
- A repo without signed commits records `N` and loses nothing.
- `wring audit` reports the recorded value; it does **not** re-verify it,
  and says so. Re-verification would need the verifier's keyring and would
  put a network-shaped dependency on a command that must work on a plane.

## 2. CLI

```bash
wring attest                     # newest delivery, else newest run
wring attest RUN_OR_DELIVERY_DIR
wring attest --json
wring audit ATTESTATION_FILE     # verify offline; exit 0/1
wring audit --json
```

Exit codes, the family's: `0` ok / attestation verifies · `1` **refused or
failed** — the bundle cannot be attested, or the audit found a mismatch ·
`2` config/environment · `4` interrupted.

## 2a. Prerequisite recording fixes (part of this slice, before `attest`)

The review that fed this spec confirmed the gaps precisely
(`wdneldem0.output`, Q1): today **only the verify bundle has digests**.
`attest`'s refusal rules would therefore refuse every judged clause. So
this slice first extends the existing machinery — all sibling-file or
code-only, no frozen schema touched:

- `judge.Bundle`, `deliver.Bundle`, loop and fleet bundles gain the same
  `write_digests()` the verify bundle has, written last.
- The delivery's MR body currently embeds whichever verdict is *newest*,
  never matched to the delivered run (`deliver.py:_verdict`). Match on the
  verdict's `evidence_dir` or embed nothing — a verdict about a different
  change is worse than none.
- `spec_sha256` hashes the file without parsing it: an *unapproved* spec
  hashes identically to an approved one. Attest must load the spec and
  refuse the `authorized_by` clause when `approved` is not true.
- Fix `_clear_previous` to clear `digests.json` in reused `--output` dirs
  (confirmed stale-digest bug — poisonous once `audit` exists).

## 3. `wring attest`

Reads the anchor bundle and follows its recorded links: a delivery names
its `run_dir` and `spec_sha256`; a verdict names its `evidence_dir` and
rubric sha; the run bundle carries the tree. Writes
`.wringer/attestations/<id>/attestation.json` (`wringer.attestation.v1`)
plus `summary.md`. **A new sibling artifact — every frozen schema is
untouched.**

**Bundles link by path; the attestation re-anchors by digest.** At
attest time, every referenced bundle's `digests.json` is *re-verified
against its files* and its sha256 recorded in the attestation. From that
moment the linkage is content-addressed even though the manifests only
named paths.

**Refusals, each exit 1, each a sentence saying why:**

- a referenced bundle has no `digests.json` (pre-0.2) — *"cannot attest
  what cannot be checked"*
- any digest mismatch — the bundle changed since it was written
- any `prev_hash` chain break in any referenced ledger
- a verdict whose `mode` is `dry_run` (nothing was judged; the clause
  would be theatre)
- gates that did not pass (law 3: no attestation dresses up a failure)

An honest refusal is the product. `wring attest` on a doctored bundle
saying **no** is the demo.

## 4. `wring audit`

The inverse, standalone, runnable by a stranger on a bundle directory they
were handed: recompute every digest, re-walk every chain, re-check every
cross-link and hash in the attestation. No config needed — an auditor may
not have `.wringer.yaml` and must not need it. `--json` for CI; the honest
failure output names the first clause that broke and stops.

## 5. Rulings

1. **Signing — DECIDED 2026-08-05: unsigned.** Not the weaker of two
   options; the one that keeps `wring attest` free of setup. Signing in v0
   would force four answers nobody asked for — which key, where the public
   half lives, what `audit` does when it cannot find it, and what CI does —
   and the last means a signing key in CI secrets, which contradicts the
   product's most distinctive promise that it never touches a credential.

   The claim unsigned makes is the one most readers actually need: an
   attestation is usually read by someone who already trusts its source and
   is asking "did the gates really run, and has anything changed since",
   not "did someone forge this". Signing matters when the reader distrusts
   the producer — a real market, but not the first one.

   Binding consequences, each with a test: **§1a** the artifact states its
   own limit, in the file and on the terminal · **§1b** a signature is a
   sibling file so v1 is purely additive · **§1c** the attestation records
   what git says about the delivered commit's signature, giving repos that
   already sign their commits real attribution for free, with Wringer still
   touching no key.

2. **RFC — DECIDED 2026-08-05: not yet, and here is the trigger.**

   Nobody would read it today. The northstar's own sequence says so:
   *"5–10 strangers whose agents run `wring verify` in their CI within a
   quarter — those become the RFC voices that turn the schemas into a
   standard."* The voices come **from** the users. Publishing before the
   launch inverts that and puts an RFC on a repository with no audience.

   The cost is the part worth naming. An RFC issue is a public commitment
   surface: once `wringer.attestation.v1` is out as one, changing it looks
   like breaking a standard even if nobody adopted it. Stacked on law 7
   that freezes the format twice — technically and socially — before it has
   ever been consumed outside this repo. And attestation is the format most
   likely to need changing after first contact, because its whole job is to
   be legible to an auditor and no auditor has read one. Two field reports
   this month found the same shape: what was wrong was what had never been
   executed. A format nobody has consumed is in that category.

   **Instead, and already done:** the schema ships in `schema/` with the
   others, and `schema/README` says plainly that these formats belong to
   nobody, that an issue is the right place to report an ambiguity, and
   that a format changing because an outside consumer hit a wall is a good
   outcome. That is the whole targetable/open/neutral signal at no
   commitment cost.

   **Trigger for revisiting:** the first time someone outside the project
   asks for the format, or tries to consume an attestation and hits
   friction. Then the RFC has a real question attached and a constituency,
   which is the only thing that makes one work.

   **What would flip it:** evidence that a vendor or standards body is
   about to define provenance for AI-written code. Planting a flag early
   beats being late even into an empty room. That is a market-timing call,
   and it is Marc's.

## 6. Non-goals (binding once approved)

Signing in v0 · verifying a commit signature rather than recording it ·
transparency logs · in-toto/SLSA format compatibility (map later, don't
contort now) · attesting anything a bundle does not already record ·
network anything.

## 7. Definition of DONE

- [ ] attest over the captured issue→MR loop produces an attestation with
      all five clauses; over a bare verify bundle, a two-clause one
- [ ] audit passes on untouched bundles; **flip one byte in one gate log
      and it names that file and fails** — the money test
- [ ] every §3 refusal has a test that fails without it
- [ ] pre-0.2 committed example bundle is refused with the stated message
- [ ] **§1a** — the limits sentence is in `attestation.json`, in `--json`,
      and on the terminal for both `attest` and `audit`; deleting it fails
      a test
- [ ] **§1b** — `attestation.json.sig` is absent in v0 and the format needs
      no change to accept one; a fixture attestation with a sibling `.sig`
      still audits clean, ignoring it
- [ ] **§1c** — `commit_signature` records git's `%G?` verbatim; a repo
      with a signed commit records `G`, one without records `N`, and
      `audit` reports without re-verifying either
- [ ] `wringer.attestation.v1` under `schema/`, freeze-guard extended
- [ ] docs carry a captured attest→doctor→audit transcript, including the
      tamper detection
