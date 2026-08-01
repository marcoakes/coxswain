# An issue in, a reviewed branch out

*Someone files an issue. Seven commands later there is a branch, a commit, a
push and a merge request carrying the receipts — and every step a person had
to authorise, they authorised by typing something.*

This is [SPEC_GET_V0.md](../SPEC_GET_V0.md) end to end, joined to the
[PM loop](pm-loop.md) that precedes it. Every block below is **real captured
output**. The two stand-ins are a loopback stub answering as the forge and as
the drafting model, and a `file://` remote instead of a hosted one — so the
transcript is reproducible and nothing left the machine. The git writes are
real git writes.

---

## The law this slice spends

Until 2026-08-01 Wringer never wrote git history at all. The Q3 goal — *an
issue becomes a passing MR* — contradicts that, so the law was amended rather
than quietly bent:

> Wringer never writes git history — **unless a human typed the flag, and it
> always leaves receipts.**

That is the judge's shape, not a new one. The amendment is worth exactly five
conditions, and each is a refusal in code with a test that fails without it:
**only a branch Wringer created** · **never the default branch** · **no force
push assemblable anywhere in the program** · **dry run is the default** · **a
ledger event before every git write**.

## 1. Bring the issue in

```console
$ wring issue https://github.com/acme/reports/issues/42
Wrote issues/42.md — CSV export for the reports page

It is a copy of something a stranger wrote: read it, then
  wring spec issues/42.md
```

An issue becomes a **file**. That is the only sane way to treat text fetched
from the internet, and it means `wring spec` needed no changes at all: an
issue is just a PRD somebody else wrote.

```markdown
<!-- fetched by `wring issue` — overwritten on refetch; this is a copy, the forge is the original -->

# CSV export for the reports page

Finance keeps asking us for the numbers in a spreadsheet. Right now they
screenshot the reports page and retype it, which is both slow and how the
January mistake happened.

I want a button on the reports page that downloads what is currently on screen
as a CSV - the same rows, respecting whatever filter is applied. It should be
obvious enough that nobody has to be told where it is.

---

- issue: https://github.com/acme/reports/issues/42
- number: 42
- author: priya-in-finance
- state: open

*Fetched by `wring issue`. This is a copy; the forge is the original, and
anything written here is a claim by its author, not an instruction to anyone.*
```

That last line is not decoration. Nothing in an issue body is executed and
nothing in it reaches a shell; instructions inside it are data. A URL naming a
repository other than the one `forge.repo` declares is refused outright.

## 2–5. The PM loop, unchanged

```console
$ wring spec issues/42.md --send
Drafted wringer.spec.yaml — CSV export on the reports page
  3 criteria (1 need a human) · 1 proposed gates · 1 tasks
  1 required question it could not answer for you

  approved: false   ← nothing runs until you change this by hand
```

```console
$ wring plan   # before anyone read it
wring plan: wringer.spec.yaml says 'approved: false', so nothing was written.

Read the file, then set 'approved: true' in it by hand. There is deliberately
no --yes: the whole point of this step is that a person read what is about to
be built.
```

A person opens the file, answers the one question it would not guess at, and
sets `approved: true`. Then:

```console
$ wring plan   # approved, and the question answered
Wrote tasks.jsonl — 1 task.
Wrote 1 brief: briefs/csv-export.md
Wrote wringer.rubric.yaml — 3 criteria (1 need a human).

Already declared, so not proposed: test. Check they run what the spec meant.
```

```console
$ wring fleet tasks.jsonl
1 task, 1 at a time.

1 succeeded, 0 failed, 0 parked.
Fleet evidence: .wringer/fleets/20260801-232400-de29/
```

```console
$ wring verify
✓ test passed        0.1s

Evidence written to:
.wringer/runs/20260801-232426-ff99/
```

The whole of that is [docs/pm-loop.md](pm-loop.md); it is here to show that
the issue slotted into it without changing it.

## 6. Say what delivery would do

```console
$ wring deliver --task csv-export
dry run — nothing was written to git.

Would create branch:  wringer/csv-export
        targeting:    main
        with:         7 file(s)

The patch, message, branch and MR body are in:
.wringer/deliveries/20260801-232426-dc55/

Read them — and edit commit.txt or mr.md if you want — then:
  wring deliver --send
```

**git is untouched** — same HEAD, same branch, no new refs; the test asserts
all three. What you get instead is the whole thing on disk, including the
literal commands:

```
git switch --create wringer/csv-export
git add --all --pathspec-from-file=- --pathspec-file-nul
git commit --file .wringer/deliveries/<id>/commit.txt
git push --set-upstream origin wringer/csv-export
POST a merge request: wringer/csv-export -> main
```

That second line is not a flourish. Delivery stages **exactly the paths the
plan listed**, fed in NUL-separated, rather than running `git add --all`. A
repo that ran `wring init` has `.wringer/` gitignored — but `wring verify`
alone writes no `.gitignore`, so a bare `add --all` swept the entire evidence
bundle into the commit and pushed it to a public branch. An MR body that
carefully omits gate logs is worth nothing beside a commit that carries them.

and the MR body, which is where the OKR's actual promise lives:

```markdown
## What was verified

| gate | status | exit | duration |
|---|---|---|---|
| test | passed | 0 | 0.1s |

## Evidence

- run: `20260801-232426-ff99`
- commit verified at: `5237212226a82af2f722f873194572614a5fdda4`
- files changed: 7

The full bundle — `evidence.jsonl`, `manifest.json`, `summary.md`,
`diff.patch` and per-gate logs — stays with the machine that ran it. Gate
output is deliberately not reproduced here: a bundle may contain whatever a
gate printed.
```

The gate **table** travels; the gate **logs** do not. A bundle can hold
anything a gate printed, and an MR body is public — so the reviewer gets the
verdict and a pointer, not a paste.

`commit.txt` and `mr.md` are yours to edit before the next step. `--send`
reads them back off disk rather than out of memory, precisely so that editing
them means something.

## 7. Deliver

```console
$ wring deliver --task csv-export --send
Branch:  wringer/csv-export
Commit:  6a56db91b556
Pushed:  yes
MR:      https://github.com/acme/reports/pull/7

Delivery evidence: .wringer/deliveries/20260801-232426-f788/
```

```console
$ git log --oneline -2 && git branch --show-current
6a56db9 CSV export on the reports page
5237212 the reports page, before the export
wringer/csv-export
```

And the ledger, which is the half of the amendment that makes the other half
survivable:

```
branch.planned   wringer/csv-export
branch.created   wringer/csv-export
commit.planned
commit.written   6a56db91b556
push.planned     wringer/csv-export
push.done        wringer/csv-export
mr.planned
mr.opened        https://github.com/acme/reports/pull/7
```

Every `planned` is appended **before** the write it describes. That ordering
is the point: kill the process between two lines and the record still says
what was attempted, which is the difference between a crash you can
investigate and one you can only guess at. It is hash-chained, like every
other ledger in the program.

Nothing is rolled back on failure. If the push lands and the forge refuses the
MR, you get a branch, a plain message saying exactly that, and a manifest
recording `pushed: true, merge_request: null`. A half-delivered branch is a
fact; a tidy-up that deleted branches would be a larger power than the one
this slice was granted.

---

## The whole thing

```bash
wring issue <url>            # the issue becomes a file
wring spec issues/42.md --send
                             # ← read it, answer it, approve it
wring plan                   # tasks, briefs, rubric, gate diff
wring fleet tasks.jsonl      # build
wring verify                 # prove
wring deliver --send         # branch, commit, push, MR with receipts
```

Seven commands. Two of them are a person reading — the approval, and the
delivery plan — and those are the two that cannot be automated away without
removing the reason any of the rest is trustworthy.

## What it will not do

Merge, approve, review or close anything · delete a branch · rewrite history ·
force-push · commit to the branch you are standing on · touch the default
branch · handle a credential (git's own helper answers for git; the forge
token is an env-var *name* in config and never a value) · write to an issue.
