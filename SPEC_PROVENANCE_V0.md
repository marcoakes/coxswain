# SPEC — tamper-evident provenance (P5, part 1)

*Drafted 2026-08-03 by the planning window. **DRAFT — awaiting Marc's
approval; not binding until he says so.** His open rulings are marked ⚖.
Builds on machinery that already ships: `digests.json` per bundle,
`prev_hash` on every ledger, `spec_sha256` in deliveries, the rubric's
sha256 in verdicts.*

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

## 5. ⚖ Marc's rulings, needed at approval

1. **Signing.** v0 options: **(a)** unsigned, format leaves a detached-
   signature seat for v1 — *recommended: smallest honest step*; **(b)**
   `ssh-keygen -Y sign` now — real signatures, zero new key
   infrastructure, but law 9 needs a careful line (Wringer *invokes* the
   user's ssh-keygen; it never reads a key).
2. **RFC.** Publish `wringer.attestation.v1` as an RFC issue alongside the
   schema, per the standards play in northstar §9a?

## 6. Non-goals (binding once approved)

Signing beyond ruling 1 · transparency logs · in-toto/SLSA format
compatibility (map later, don't contort now) · attesting anything a bundle
does not already record · network anything.

## 7. Definition of DONE

- [ ] attest over the captured issue→MR loop produces an attestation with
      all five clauses; over a bare verify bundle, a two-clause one
- [ ] audit passes on untouched bundles; **flip one byte in one gate log
      and it names that file and fails** — the money test
- [ ] every §3 refusal has a test that fails without it
- [ ] pre-0.2 committed example bundle is refused with the stated message
- [ ] `wringer.attestation.v1` under `schema/`, freeze-guard extended
- [ ] docs carry a captured attest→doctor→audit transcript, including the
      tamper detection
