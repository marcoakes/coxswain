# The PM loop — a PRD in, a verified change out

*Prose in, testable criteria out — and a human approves them before anything
runs.*

This is the whole of `wring spec` and `wring plan`
([SPEC_INTENT_V0.md](../SPEC_INTENT_V0.md)), end to end, in seven commands —
one of which is reading.

Every block below is **real captured output**, not an illustration. The one
thing standing in for production is the endpoint: a stub on `127.0.0.1`
returned the drafting reply and the verdict, so the transcript is
reproducible and nothing left the machine. Everything else — the files, the
refusals, the exit codes, the fleet, the gates — is Wringer doing its job.

---

## The failure this slice exists to prevent

A PRD is vaguer than an issue, and the danger is not a bad build. It is a
**confident build of the wrong thing** — a plausible spec, cheerfully
executed, that nobody looked at. Three defences, all structural:

1. **Approval is a file edit, not a keystroke.** The draft lands as
   `wringer.spec.yaml`. Skimming a prompt is easy; a file asks to be read.
   There is deliberately **no `--yes`**.
2. **Unclear input produces questions, not guesses.** Anything the drafter
   had to assume becomes an `open_question`, and a spec with an unanswered
   required question **cannot be planned**.
3. **Every criterion must be checkable.** The drafter is told to prefer
   criteria a gate can decide and to mark the rest `human: true` — and a
   `human` criterion is then never sent to a judge at all.

## 0. The input

A product manager writes what they want, in the words they would use:

```markdown
# CSV export for the reports page

Finance keeps asking us for the numbers in a spreadsheet. Right now they
screenshot the reports page and retype it, which is both slow and how the
January mistake happened.

I want a button on the reports page that downloads what is currently on
screen as a CSV — the same rows, respecting whatever filter is applied.
It should be obvious enough that nobody has to be told where it is.
```

The repo already declares its gates and its endpoint in `.wringer.yaml`.
Drafting reuses the `judge:` section verbatim — one network config, one set
of safety rules, one auditable path:

```yaml
version: 1
gates:
  - id: test
    run: "pytest -q"

run:
  worker: "sh ./agent.sh"        # in a real repo: claude -p "$(cat {brief})"
  max_iterations: 2

fleet:
  concurrency: 1
  deadline: 600

judge:
  endpoint: http://127.0.0.1:11713/v1/chat/completions
  model: qwen2.5-coder:7b
  rubric: wringer.rubric.yaml
```

## 1. Draft it — without sending anything

Dry run is the default, here as everywhere:

```console
$ wring spec PRD.md
dry run — the request was built and written; nothing was sent.

Request written to:
.wringer/specs/20260731-231430-d58c/

When you are ready:
  wring spec <PRD> --send
```

The exact bytes that *would* leave the machine are on disk before any socket
is opened. `wring spec --print-request` puts the same body on stdout instead.

## 2. Send it

```console
$ wring spec PRD.md --send
Drafted wringer.spec.yaml — CSV export on the reports page
  4 criteria (1 need a human) · 2 proposed gates · 2 tasks
  1 required question it could not answer for you

  approved: false   ← nothing runs until you change this by hand

Next:
  read wringer.spec.yaml, answer its open questions,
  set 'approved: true', then run: wring plan

Draft evidence: .wringer/specs/20260731-231430-4af4/
```

Both halves of the exchange — `request.json` and `response.json` — stay in
the draft directory. The one function in Wringer that opens a socket is still
`judge.send`; `wring spec` did not add a second.

## 3. Read it

This is the step, and it is the only one Wringer cannot do for you.

```yaml
# wringer.spec.v1 — drafted by `wring spec`, approved by you.
#
# Nothing runs until 'approved' below says true, and only a person
# can make it say that: there is no flag, and no --yes.

schema_version: wringer.spec.v1
approved: false        # <- the interlock. `wring plan` refuses while this is false.
title: CSV export on the reports page

# Your own words, quoted from the PRD. Check the criteria below
# against this, not against what you meant to write.
intent: |2
  # CSV export for the reports page

  Finance keeps asking us for the numbers in a spreadsheet. Right now they
  screenshot the reports page and retype it, which is both slow and how the
  January mistake happened.

  I want a button on the reports page that downloads what is currently on
  screen as a CSV — the same rows, respecting whatever filter is applied.
  It should be obvious enough that nobody has to be told where it is.

# Answer each question by writing an 'answer:' line under it,
# or delete the question. `wring plan` refuses while a required
# one is unanswered.
open_questions:
  - id: date-format
    question: Which date format should the CSV use — ISO-8601, or the locale the page is rendered in?
    required: true
    answer: ''
  - id: row-cap
    question: Is there a row count above which the export should stream or refuse?
    required: false
    answer: ''

# The acceptance criteria — a wringer.rubric.v1 document, which is
# what `wring judge` will weigh the finished change against.
# 'human: true' means no judge may score it; a person must.
criteria:
  - id: export-button
    title: A CSV export button is present on the reports page
    guidance: A test renders the page and asserts the button exists.
    required: true
    human: false
  - id: matches-filters
    title: The exported rows are exactly the rows the current filter shows
    guidance: A test applies a filter and compares the CSV rows to the rendered rows.
    required: true
    human: false
  - id: headers-are-stable
    title: Column headers match the on-screen column names
    guidance: A test asserts the header row.
    required: true
    human: false
  - id: discoverable
    title: Someone who has not been told where the button is can find it
    required: true
    human: true

# Proposed gates. `wring plan` prints these as a diff against
# .wringer.yaml and stops — Wringer never installs a gate itself.
gates:
  - id: test
    run: pytest -q
  - id: lint
    run: ruff check .

# The build plan. `wring plan` turns these into tasks.jsonl and
# writes each brief to the path named here.
tasks:
  - id: csv-endpoint
    brief: briefs/csv-endpoint.md
    dir: .
    objective: Add an endpoint that serializes the currently filtered report rows to CSV, reusing the same query the page uses so the two cannot drift apart.
  - id: export-button
    brief: briefs/export-button.md
    dir: .
    objective: Add the export button to the reports page toolbar, wired to the new endpoint and passing the active filter through.
```

Three things in that file are worth naming.

**`intent` is quoted from the PRD, not written by the model.** A drafter
paraphrasing the human's own words inside the artifact the human is about to
approve is the confident-wrong-answer in miniature. The reader checks the
criteria against the quote.

**`discoverable` is `human: true`.** "Someone who has not been told where the
button is can find it" is a real requirement and no test decides it. Wringer's
answer is not to drop it or to let a model guess: it is carried, and marked.

**The `date-format` question was asked rather than assumed.** Wringer's oldest
law — never invent a command nobody wrote down — applied one level up.

## 4. Try to skip the reading

```console
$ wring plan
wring plan: wringer.spec.yaml says 'approved: false', so nothing was written.

Read the file, then set 'approved: true' in it by hand. There is deliberately
no --yes: the whole point of this step is that a person read what is about to
be built.
```

Exit `1`, and the tree is untouched: no `tasks.jsonl`, no briefs, no rubric.
`wring plan` re-reads the file from disk every time, so the interlock is not
a variable anything could have carried over.

Approve it but leave the question open, and it refuses again, differently:

```console
$ wring plan
wring plan: 1 required question in wringer.spec.yaml is unanswered:
  - date-format: Which date format should the CSV use — ISO-8601, or the locale the page is rendered in?

Write an 'answer:' under each, or delete the question if it no longer matters.
Building on an assumption is how the wrong thing gets built confidently.
```

## 5. Answer it, approve it, plan it

The PM edits two lines in the file — an `answer:`, and `approved: true`:

```console
$ wring plan
Wrote tasks.jsonl — 2 tasks.
Wrote 2 briefs: briefs/csv-endpoint.md, briefs/export-button.md
Wrote wringer.rubric.yaml — 4 criteria (1 need a human).

Proposed gates (lint). Wringer does not install these — changing what 'verified' means is yours to do:

--- a/.wringer.yaml
+++ b/.wringer.yaml
@@ -2,6 +2,8 @@
 gates:
   - id: test
     run: "pytest -q"
+  - id: lint
+    run: ruff check .
 
 run:
   worker: "sh ./agent.sh"

Already declared, so not proposed: test. Check they run what the spec meant.

Next:
  point 'judge.rubric:' at wringer.rubric.yaml
  wring fleet tasks.jsonl
```

**The gate is proposed, never installed.** `.wringer.yaml` is unchanged byte
for byte; what you get is a diff `git apply` accepts, and a human decides
whether "verified" now also means `ruff`. A harness that quietly widened its
own definition of proof would be worth nothing.

And when the change *cannot* be expressed as a safe diff — a `.wringer.yaml`
whose gate list is in flow style, say — you get the gates in words and a
sentence saying why, rather than a patch that reads as additive and is not.
Two `gates:` keys is not a merge: YAML keeps the last one, so such a patch
would delete every gate you already had, after you read it and approved it.

Three files come out. `tasks.jsonl`, which is exactly what `wring fleet`
already eats — references, never inline payloads:

```jsonl
{"id": "csv-endpoint", "brief": "briefs/csv-endpoint.md", "dir": "."}
{"id": "export-button", "brief": "briefs/export-button.md", "dir": "."}
```

`wringer.rubric.yaml`, which is the spec's criteria block with **no
translation layer** — the same keys, validated by the judge's own parser
before it was written. The marker comment is a guard, not decoration:
`judge.rubric:` has pointed at a file since v0.2, so a repo adopting `wring
spec` may already have a hand-written rubric, and `wring plan` refuses to
replace one it did not write:

```yaml
# generated by `wring plan` from wringer.spec.yaml — edits here are overwritten; edit the spec
schema_version: wringer.rubric.v1
title: CSV export on the reports page
criteria:
- id: export-button
  title: A CSV export button is present on the reports page
  guidance: A test renders the page and asserts the button exists.
  required: true
  human: false
- id: matches-filters
  title: The exported rows are exactly the rows the current filter shows
  guidance: A test applies a filter and compares the CSV rows to the rendered rows.
  required: true
  human: false
- id: headers-are-stable
  title: Column headers match the on-screen column names
  guidance: A test asserts the header row.
  required: true
  human: false
- id: discoverable
  title: Someone who has not been told where the button is can find it
  required: true
  human: true
```

And a brief per task, carrying the criteria, the PM's decisions, and the PM's
own words down to whatever agent does the work:

```markdown
<!-- generated by `wring plan` from wringer.spec.yaml — edits here are overwritten; edit the spec -->

# csv-endpoint — CSV export on the reports page

## Objective

Add an endpoint that serializes the currently filtered report rows to CSV,
reusing the same query the page uses so the two cannot drift apart.

## Acceptance criteria

These are what the change will be judged against.

- **export-button** — A CSV export button is present on the reports page
  - A test renders the page and asserts the button exists.
- **matches-filters** — The exported rows are exactly the rows the current filter shows
  - A test applies a filter and compares the CSV rows to the rendered rows.
- **headers-are-stable** — Column headers match the on-screen column names
  - A test asserts the header row.
- **discoverable** — Someone who has not been told where the button is can find it _(a human scores this)_

## Decisions already made

- **Which date format should the CSV use — ISO-8601, or the locale the page is
  rendered in?** ISO-8601 always. Finance re-imports these and locale dates
  broke it once.

## What the product manager asked for

...
```

## 6. Build it

```console
$ wring fleet tasks.jsonl
2 tasks, 1 at a time.

2 succeeded, 0 failed, 0 parked.
Fleet evidence: .wringer/fleets/20260731-231526-aa92/
```

Each task is an ordinary `wring run` loop: verify → brief → worker → verify,
under the supervision invariants — bounded retries, no retry on a repeated
failure shape, liveness measured by ledger growth. Wringer never wrote to git;
the change is in the working tree, for a person to commit.

## 7. Prove it, then judge it

```console
$ wring verify
✓ test passed        0.1s

Evidence written to:
.wringer/runs/20260731-231536-ef89/
```

```console
$ wring judge --send
✓ export-button
✓ matches-filters
✓ headers-are-stable
? discoverable  (needs a human)

Verdict: needs_human
  required criteria only a human can score: discoverable

Judgment written to:
.wringer/verdicts/20260731-231537-dd61/
```

Exit `5`, and this is the honest answer rather than a disappointing one. The
gates passed. Three of the four criteria were scored and met. The fourth was
**never sent** — it is not in the prompt and not in the set of ids the model
was allowed to answer with — so nobody guessed at it, and the verdict says
what is actually true: a person still has to look at the button.

"The evidence says no" and "nothing competent looked at the evidence" are
different claims, and Wringer has always refused to collapse them. `human:
true` is that principle applied to the criteria a rubric should not pretend
to decide.

---

## The whole loop

```bash
wring spec PRD.md --send     # draft
                             # ← read it, answer it, approve it
wring plan                   # tasks, briefs, rubric, gate diff
wring fleet tasks.jsonl      # build
wring verify                 # prove
wring judge --send           # weigh it against what was approved
```

Five commands, one of which is reading — and the reading is the one that
cannot be automated away, because it is the entire point.

## What this deliberately does not do

Multi-turn conversational refinement (edit the file) · auto-applying gate
changes · auto-approval in any form · estimating effort or cost · design or
visual output · issue-tracker ingestion (that is P3) · running gates or
touching git from `wring spec`.
