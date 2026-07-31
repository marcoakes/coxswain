# SPEC — intent → spec → plan (P2)

*Drafted 2026-07-31. Binding for `wring spec` and `wring plan`. This is the
slice where "a product manager provides the plan" becomes real, and the one
that carries the most product risk — read §1 before writing code.*

## Positioning

> **Prose in, testable criteria out — and a human approves them before
> anything runs.**

A PM writes what they want in plain language. `wring spec` turns it into a
rubric, gates and a build plan **as files on disk**. Nothing executes until
the human has read and approved them. `wring plan` then compiles the
approved spec into a fleet task file.

## 1. The hard part, named honestly

A PRD is vaguer than an issue. **The failure mode is not a bad build; it is
a confident build of the wrong thing.** Three defences, all structural:

1. **Approval is a file edit, not a keystroke.** The draft lands as
   `wringer.spec.yaml` and the PM edits or approves it. Skimming a prompt
   is easy; a file asks to be read.
2. **Unclear input must produce questions, not guesses.** The drafter is
   instructed to emit `open_questions` for anything it had to assume, and
   **a spec with unanswered required questions cannot be planned** — `wring
   plan` exits 2 listing them. Wringer's oldest law, "never invent a
   command nobody wrote down," applied one level up.
3. **Every criterion must be checkable.** The drafter is told to prefer
   criteria a gate can decide, and to mark the rest `human: true`. A rubric
   full of vibes is a rubric that proves nothing, and the judge already
   distinguishes "not met" from "could not be scored."

## 2. CLI

```bash
wring spec PRD.md                # draft wringer.spec.yaml (dry-run default)
wring spec PRD.md --send         # actually call the LLM
wring spec --print-request       # the exact would-be body, then stop
wring plan                       # approved spec -> tasks.jsonl
wring plan --json
```

**Exit codes**, the family's, plus nothing new: `0` ok · `1` refused because
the spec is unapproved or has open questions (a "no" about the work) · `2`
config/environment · `3` unsafe tree · `4` interrupted.

**`--send` is required to reach the network, exactly as `wring judge`.**
The request is written to disk before any socket opens. The drafter reuses
the `judge:` section's endpoint/model/key rules verbatim — one network
config, one set of safety rules, one auditable path. (If a repo wants a
different model for drafting than for judging, that is a later `spec:`
override; v0 deliberately has one.)

## 3. The artifact — `wringer.spec.v1`

```yaml
schema_version: wringer.spec.v1
approved: false          # THE GATE. wring plan refuses while this is false.
title: Add CSV export to the reports page
intent: |
  Verbatim excerpt of what the human asked for.
open_questions:
  - id: date-format
    question: Which date format should the export use?
    required: true
criteria:                # becomes the judge's rubric
  - id: export-button-exists
    title: A CSV export button appears on the reports page
    required: true
    human: false
gates:                   # proposed .wringer.yaml gates, NOT auto-installed
  - id: test
    run: pytest -q
tasks:                   # becomes tasks.jsonl
  - id: csv-export
    brief: briefs/csv-export.md
    dir: .
```

**Rulings:**

- **`approved: false` is the safety interlock.** The human flips it. No
  flag, no env var and no LLM may flip it — `wring plan` re-reads the file
  from disk every time and refuses while it is false. A `--yes` shortcut is
  explicitly *not* provided; that is the point of the slice.
- **Gates are proposed, never installed.** `wring plan` prints the diff it
  would make to `.wringer.yaml` and the human applies it. Wringer does not
  silently change what "verified" means.
- **Briefs are written as files** and tasks reference them by path —
  invariant 5, the same rule the fleet already obeys.
- The criteria block is a `wringer.rubric.v1` document by construction, so
  the judge consumes it with no translation layer.

## 4. `wring plan`

Reads the approved spec, writes `tasks.jsonl` (fleet-ready) and the brief
files, prints the proposed `.wringer.yaml` gate diff, and stops. It runs
nothing. Refusals: unapproved (1), unanswered required questions (1, listing
them), no spec file (2).

The PM's whole loop becomes: `wring spec PRD.md --send` → read and edit →
set `approved: true` → `wring plan` → `wring fleet tasks.jsonl` → `wring
judge`. Five commands, one of which is reading.

## 5. Non-goals (binding)

Multi-turn conversational refinement (edit the file) · auto-applying gate
changes · auto-approval in any form · estimating effort or cost · design or
visual output · issue-tracker ingestion (P3) · `wring spec` running gates or
touching git.

## 6. Definition of DONE

- [ ] a dry run drafts nothing and sends nothing, writing only the request
- [ ] `--send` against a **fake transport** produces a valid
      `wringer.spec.v1` file from a real example PRD fixture
- [ ] a drafted spec always arrives `approved: false`
- [ ] `wring plan` on an unapproved spec exits 1 and changes nothing
- [ ] `wring plan` with unanswered required questions exits 1 and lists them
- [ ] an approved spec produces a `tasks.jsonl` the fleet actually runs
- [ ] the criteria block validates against `wringer.rubric.v1` unmodified
- [ ] a malformed LLM reply is refused with a clear error, never a
      half-written spec file
- [ ] schemas published under `schema/`, drift test extended
- [ ] docs carry the full captured PM loop: PRD → spec → approve → plan →
      fleet → judge
