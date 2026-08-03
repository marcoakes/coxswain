# SPEC — repos in, changes out (P3)

*Drafted 2026-08-01. Binding for `wring get`, `wring issue` and `wring
deliver`. This is the slice that closes the Q3 OKR — "a GitHub issue becomes
a passing MR" — and the first one in which Wringer writes git history at all.
Read §1 before writing code.*

## Positioning

> **The work comes in as a URL and leaves as a reviewed branch, and the
> harness never takes a step you did not type.**

## 1. The law this slice amends, and exactly how far

Until today, handover law 6 read: *Wringer never writes git history. No
commit, no branch, no push.* The Q3 OKR contradicts it, so **Marc amended the
law on 2026-08-01**:

> Wringer never writes git history — **unless a human typed the flag, and it
> always leaves receipts.**

That is the judge's shape, not a new one: a dangerous capability that exists,
is off by default, is typed by a person, and writes evidence before it fires.
The amendment is worth exactly its five conditions, and **every one of them
is a refusal in code, not a guideline**:

1. **Only a branch Wringer created.** The branch name is written to the
   ledger *before* the branch exists, so "did Wringer make this?" is a
   question the evidence answers. An existing branch of that name is a
   refusal, never a checkout.
2. **Never the default branch.** Not as a target, not as a place to commit.
   Determined from the remote's HEAD, and refused if it cannot be determined
   — an unknown default is not a safe one.
3. **Never a force push.** `--force`, `--force-with-lease` and `+refs/`
   refspecs do not appear in this program.
4. **Dry run is the default.** The patch, the commit message, the branch name
   and the MR body are on disk, and the exact commands are printed, before
   anything runs. `--send` is the same code path continuing one step further.
5. **Every git write is a ledger event.** Not "was logged" — *appended before
   the write*, so a crash mid-delivery leaves a record of what was attempted.

**What this slice still may not do, ever:** merge, approve or close anything ·
delete a branch · rewrite history (`rebase`, `commit --amend`, `push --force`)
· commit to the branch the user is standing on · touch the default branch ·
handle a credential (see §5).

## 2. CLI

```bash
wring get <url>                  # clone into the workspace
wring get <url> --into DIR       # ...somewhere specific
wring issue <url>                # write an issue to a local markdown file
wring deliver                    # dry run: patch, message, branch, MR body
wring deliver --send             # actually branch, commit, push, open the MR
wring deliver --json
```

**Exit codes**, the family's, nothing new: `0` ok · `1` refused because of the
work (nothing to deliver, gates did not pass) · `2` config/environment · `3`
unsafe tree / refused precondition · `4` interrupted.

Three commands, because each does one thing. In particular **`wring spec` is
untouched**: an issue becomes a *file*, and `wring spec <that file>` proceeds
exactly as it does today. P2's non-goal "issue-tracker ingestion (P3)" is met
by ingesting to disk, not by teaching `spec` a second input.

## 3. `wring get`

Clone a repository into the workspace. The one command in Wringer whose
argument is a URL a human typed.

- Destination is `<workspace>/<name>` from the URL, or `--into DIR`.
  `workspace:` is declared in `.wringer.yaml`; there is **no default
  workspace** — Wringer does not choose where to put someone's code.
- Schemes: `https://`, `ssh://`, `git@host:path`, and `file://` (which is how
  the test suite clones without a network). Anything else is a refusal.
- **A URL carrying credentials is refused** — the same rule as
  `judge.endpoint`, for the same reason: it is recorded.
- Refuses a destination that exists and is not empty. Cloning over someone's
  work is not a thing to do quietly.
- Records `origin`, the resolved HEAD sha and the default branch to
  `.wringer/acquired/<id>/manifest.json` (`wringer.acquired.v1`). A working
  copy that cannot say where it came from is the provenance gap P5 closes;
  this is the half of it that costs nothing now.
- Runs nothing it cloned. No gate, no hook, no install step — a fresh clone
  is untrusted input, and SECURITY.md's `.wringer.yaml`-is-code warning is
  exactly why.

## 4. `wring issue`

Fetch one issue and write it down as markdown.

- The forge and endpoint come from the `forge:` config section (§6). No
  default host, ever.
- Writes `<issues_dir>/<number>.md`: the title as an H1, the body verbatim,
  and a provenance footer (URL, author, state, fetched-at). **Refuses to
  overwrite** a file it did not write (marker line, the `wring plan` rule).
- The body is untrusted text from the internet. It is written to a file and
  read by a human; nothing in it is executed, and nothing in it may reach a
  shell. Instructions inside an issue are data.
- Redacted on the way in, like the PRD: scrubbed at the read, so the file, the
  later request and the wire all agree.

## 5. `wring deliver`

Turn a verified change into a branch and an MR.

**Preconditions, all refusals:**

| condition | exit |
|---|---|
| no finished run bundle, or its required gates did not pass | 1 |
| working tree has nothing to deliver | 1 |
| tree is mid-merge/rebase (`git.in_progress`) | 3 |
| the branch Wringer would create already exists | 3 |
| the default branch cannot be determined from the remote | 3 |
| no `deliver:` config section | 2 |

*Gates before delivery* is law 3 wearing a different hat: an unverified change
does not get a branch, and a judge's verdict never substitutes for the gates.

**The dry run writes `.wringer/deliveries/<id>/`:** `patch.diff`,
`commit.txt`, `branch.txt`, `mr.md`, and `commands.txt` — the exact `git` and
API calls, in order. It then stops. **The human may edit `commit.txt` and
`mr.md` before `--send`**; that is the point of writing them.

**`--send` performs, in this order,** appending a ledger event before each:
`branch.created` → `commit.written` → `pushed` → `mr.opened`. A step that
fails stops the sequence; the ledger says how far it got, and nothing is
rolled back — a half-delivered branch is a fact, and inventing a tidy-up that
deletes a branch would be a worse power than the one being granted.

**The MR body carries the receipts**, which is the OKR's actual promise: the
gate table from `summary.md`, the run id, the judge's verdict if one exists,
and the bundle path. **Never raw gate logs** — SECURITY.md is clear that a
bundle may contain whatever a gate printed, and an MR body is public.

## 6. Config — `forge:` and `deliver:`

```yaml
workspace: ../work            # wring get's destination root. No default.

forge:
  kind: github                # or gitlab. Selects the mapping module.
  endpoint: https://api.github.com
  repo: marcoakes/wringer
  token_env: FORGE_TOKEN      # the NAME of a variable, never a value

deliver:
  branch: "wringer/{task}"    # {task}, {run} — declared placeholders only
  base: main                  # optional; defaults to the remote's default
  remote: origin
  issues_dir: issues
```

- `endpoint`, `repo` and `kind` have no defaults and never will.
- Endpoint safety is `judge`'s, reused verbatim: https anywhere, http only to
  loopback, no userinfo, no query string.
- **`token_env` names a variable; Wringer reads it at runtime and never writes
  it anywhere.** Its value joins the redactor, as `judge.api_key_env` does.
- **`git push` credentials are git's business, not Wringer's.** Wringer shells
  out and lets git's own credential machinery answer. It never reads, stores,
  prompts for or passes a git credential — law 9, kept by not participating.

## 7. Network

`wring judge --send` was "the only function that opens a socket". After this
slice that sentence is false, and it is **restated rather than quietly
kept**. The rule that actually matters, and that holds:

> **Nothing that proves anything touches a network, and nothing leaves the
> machine without a flag a human typed.**

`verify`, `run`, `resume`, `fleet` and `plan` cannot reach a network at all.
Three commands SEND, each behind `--send` and each writing the exact bytes to
disk first: `judge`, `spec`, `deliver`. Two commands FETCH, and are not behind
a flag because fetching is their entire purpose — `wring get` clones a
repository, `wring issue` reads one issue. A user typing either knows they are
reaching a network; a `--send` on them would be ceremony rather than safety.
Every socket lives in `judge.send` or `forge.request`, and
`grep -rn "build_opener" src/` must return exactly those two. Both are reached only with a flag a human typed, only
against an endpoint the repo declared, and only after the bytes are on disk.

Vendor strings live behind `forge.py` (AGENTS.md rule 5): GitHub and GitLab
differ in path shape and field names, and neither name may appear in `cli.py`.
API versions are pinned.

## 8. Non-goals (binding)

Merging, approving, reviewing or closing anything · deleting branches ·
rewriting history in any form · force pushes · committing to the current
branch · touching the default branch · credential management · issue
*writing* (comments, labels, state) · forges beyond the two mapped · watching
or polling a remote · CI integration beyond what the MR body links to.

## 9. Definition of DONE

- [ ] `wring get` clones a `file://` repo in tests — no network in the suite
- [ ] a URL with credentials in it is refused, and a non-empty destination too
- [ ] `wring issue` writes a file a human reads, and refuses to overwrite one
      it did not write
- [ ] `wring deliver` dry-run writes patch, message, branch, MR body and the
      exact commands, and touches git not at all
- [ ] an unverified change is refused; a failed-gate bundle is refused
- [ ] `--send` against a **fake forge transport** and a `file://` remote
      produces a branch, a commit and a recorded MR — proven end to end
- [ ] every one of §1's five conditions has a test that fails without it,
      including: existing branch refused, default branch refused, no force
      flag anywhere in the program, ledger written before the git write
- [ ] a token never appears in any artifact
- [ ] `wringer.delivery.v1` and `wringer.acquired.v1` published under
      `schema/`, drift test extended
- [ ] README's "only socket" claim restated honestly, and docs carry the
      captured loop: issue → spec → plan → fleet → verify → deliver
