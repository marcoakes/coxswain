# Show HN draft — for Marc to edit and post

*Written 2026-08-03. **Not posted.** Posting is Marc's, and so is the final
wording — this is a starting point with every number checked, not a script.*

**✅ The precondition is met (2026-08-03).** `pip install wringer` gives
0.2.0 with all thirteen commands — verified from the index, cache off, by
`scripts/verify-published.sh`. Checked at the same time, because the post
leans on all of it:

| what the post points at | state |
|---|---|
| `pip install wringer` | **0.2.0**, PyYAML the only runtime dep |
| GitHub release `v0.2.0` | published, wheel + sdist attached |
| the RFC issues (the standards line) | **3 open** — #1 loop contract, #2 evidence bundle, #3 gate plugin |
| README / QUICKSTART / SETUP / SECURITY | corrected `e087d1a`; none still says "install from git, not PyPI" |
| the demo the README opens with | `docs/demo.svg`, real capture, regenerable |

**One judgement left, and it is Marc's alone: the incident numbers.** 24
agents, 4 results, 20 identical retries, 8 hours, 50 KB blobs. They are true
and they are verified in the session history of 2026-07-30/31 — but **nothing
in this repository evidences them**, so on Hacker News they stand on his word.
That is a fine thing to post; it is not a thing to post accidentally.

---

## Title options

The title does most of the work. All three lead with the failure, not the
tool:

1. **Show HN: My agent fleet ran for 8 hours and produced nothing. I built the harness that makes that impossible**
2. **Show HN: Wringer – your agent says the tests passed; this proves it**
3. **Show HN: 24 agents, 4 results, 20 identical retries – and the supervision layer it cost me**

(1) is the strongest: it is a confession, it has numbers, and the tool is the
second clause rather than the first. (2) is the better *product* line and the
better fallback if the incident framing feels overplayed.

---

## Body

Last month I left a fleet of coding agents running overnight on a design
task. In the morning: **24 agents spawned, 4 results, and 20 of those agents
had retried the identical failure** — the same deterministic error, the same
50 KB blob handed to each of them inline, over and over, for eight hours.
Every process was alive the whole time. Nothing had happened.

The part that stuck with me was not the waste. It was that I had no way to
tell. "Still running" looked exactly like "working", and the only evidence I
had was each agent's own summary of itself.

That is the thing I think the industry is walking into. Agents are getting
good enough that we stop reading the diffs, and the only thing standing
between us and a codebase nobody has checked is the agent's own report that
it went fine.

So I wrote down what that night had actually taught me, as eight invariants:

- nothing retries without a ceiling
- **nothing retries on an identical failure shape** — the one that would have
  saved all twenty
- nothing waits without a deadline
- **liveness is ledger growth, not a live process**
- work is passed by reference, never as an inline blob
- partial success is reported honestly
- everything resumes from its ledger
- budgets nest

Then I built the harness that enforces them. It is called **Wringer**, it is
Apache-2.0, and the pitch is one sentence:

> Everyone else in this space is selling capability and asking for trust.
> Wringer trusts nothing — including itself.

Not the worker's exit code. Not the agent's summary. Not even the tests the
agent wrote.

**What it actually does.** `wring verify` runs the gates your repo already
declares and writes an evidence bundle: a manifest, a timestamped event log,
the diff, per-gate logs, and a sha256 of every file in it. `wring run` loops
— verify, hand the failure to *your* agent, verify again — and the agent's
exit code never ends the loop; the evidence does. `wring fleet` supervises
hundreds of those under the invariants above. `wring judge` weighs a finished
bundle against a rubric, and is structurally unable to see anything the
worker said. `wring spec` turns a PRD into acceptance criteria a human
approves in a file — there is deliberately no `--yes`. `wring deliver` turns
a verified change into a branch and an MR with the receipts attached.

It ships no agent and calls no model itself. Your agent, your gates, your
endpoint. Nothing that *proves* anything can reach a network at all.

**The part I would want to read.** The repo audits itself: Wringer's own CI
runs `wring verify` on Wringer, a real bundle is committed, and every
transcript in the docs is captured output rather than an illustration. When
I found that `wring deliver` could publish a merge request claiming gates had
passed on a tree they never saw, I reproduced it, fixed it, and wrote the
reproduction into the commit message. That bug is in the CHANGELOG under
Fixed, because a project whose product is honest evidence does not get to
have a quiet Fixed section.

`pip install wringer` · https://github.com/marcoakes/wringer

I would genuinely like to be told where this is wrong. The schemas are
published so other tools can target them rather than reverse-engineer them,
and the open RFCs are the parts I am least sure about.

---

## Notes for posting

- **Every number is verified** in the sessions of 2026-07-30/31. 24 agents,
  4 results, 20 identical retries, 8 hours, 50 KB blobs. Do not round them up.
- **Expect the "another orchestrator" pattern-match.** The counter is the
  incident and the receipts, not a feature list — which is why the numbers
  lead and the command list is one paragraph in the middle.
- **The strongest reply material** is the self-auditing repo: the committed
  bundle, the captured transcripts, the CHANGELOG's Fixed section. If someone
  says "how do I know", that is the answer, and it is checkable in thirty
  seconds.
- **The real metric is not stars** — it is 5–10 strangers running `wring
  verify` in their CI. Watch for that in the replies, and answer those people
  first.
- Post when you can sit with it for a few hours. Half a day of replies is
  worth more than the post.
