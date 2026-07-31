# SPEC — `wring judge` v0.2, slice 2: the rubric judge

*Drafted 2026-07-31 by synthesis of four independent designs (minimalism,
contract-first, safety, testability lenses), each adversarially reviewed.
**Not yet adopted** — §9 carries one decision the maintainer must make first.
[SPEC_VERIFY_V0.md](SPEC_VERIFY_V0.md) and [SPEC_RUN_V0.md](SPEC_RUN_V0.md)
remain binding and unchanged.*

## Positioning

> **The gates said the change works. A judge says whether it is the change
> that was asked for — and shows you exactly what it was told.**

`wring judge` reads a *finished* evidence bundle and a rubric the repo wrote,
and produces a structured verdict. It is a standalone command over a
completed artifact, the way `wring verify` shipped before `wring run` — not a
stage buried inside the loop.

That shape is not a convenience. It is what makes worker/judge isolation
**physical**: the judge reads `.wringer/runs/<id>/`, while everything a worker
ever said lives in `.wringer/loops/<id>/iterations/`. The two trees do not
overlap, so a worker's reasoning cannot reach a judge because there is no code
path along which it could travel.

**Deterministic gates always run first, and a judge never overrides them.**

## 1. The one genuinely new thing

This is the first command in Wringer's history that can open a socket. Every
line of the design below exists to make that fact loud, auditable, and
impossible to trigger by accident.

Three mechanisms carry it:

1. **Dry run is the default.** `wring judge` assembles everything, writes the
   exact request body to disk, and exits **without opening a socket**.
   `--send` is the only way to transmit, and there is no config key and no
   environment variable that can imply it. The word is typed by a human or it
   does not happen.
2. **No default endpoint and no default model, ever.** The same law as
   `run.worker`. A repo with no `judge:` section has no reachable code path
   in the program that opens a connection.
3. **`request.json` is written before the socket opens.** What leaves the
   machine is therefore auditable rather than asserted, and `--dry-run` is
   literally the same code path stopping one step earlier — not a separate
   branch that might drift.

## 2. CLI surface

```bash
wring judge                      # dry run against the latest bundle: builds, sends nothing
wring judge RUN_DIR              # judge a named bundle instead of the latest
wring judge --send               # the only path in Wringer that opens a socket
wring judge --print-request      # write the exact would-be body to stdout, exit 0
wring judge --rubric PATH        # override the configured rubric
wring judge --json               # one object on stdout, no human report
```

**Exit codes.** `0`–`4` keep the meanings the other commands gave them; `5`
is new, and belongs to `wring judge` alone.

| code | meaning |
|---|---|
| 0 | verdict `pass` — every required criterion met. Also a successful dry run, which says so on its first line. |
| 1 | verdict `fail` — a required criterion was not met |
| 2 | config or environment error (no `judge:` section, no rubric, unreadable bundle, `api_key_env` names an unset variable, an endpoint the safety rules reject) |
| 3 | refused — **the bundle's required gates did not pass**, or it records an interrupted run |
| 4 | interrupted |
| 5 | verdict `needs_human` — nothing competent reached a conclusion |

**`5` must never be folded into `1`.** "The evidence says no" and "nothing
competent looked at the evidence" are different claims, and this repo does not
conflate them. A transport failure, a timeout, an unparseable reply, or a
criterion the model declined to score all produce `5`.

**Gates-failed is a refusal, not a verdict.** When the deterministic gates
already said no, a judge has nothing to add and no request is built.

A test asserts `wring verify` and `wring run` can never return `5`.

## 3. Config — the `judge:` section

```yaml
judge:
  endpoint: http://127.0.0.1:11434/v1/chat/completions
  model: qwen2.5-coder:7b
  rubric: rubric.yaml
  api_key_env: OPENAI_API_KEY   # optional — the NAME of a variable, never a key
  timeout: 120                  # optional, default 120, integer >= 1
  max_output_tokens: 1024       # optional, default 1024, integer >= 1
```

**Rules (binding):**

1. `endpoint`, `model` and `rubric` are **required, with no defaults, ever.**
   Wringer contacts the endpoint you wrote down and never one it guessed.
2. **Endpoint safety, checked at parse time:** `https://` anywhere, `http://`
   **only** to loopback. No userinfo (`user:pass@`) and no query string —
   credentials never travel in a URL, and the URL is recorded in the bundle.
3. `api_key_env` names an **environment variable**. Wringer will not read a
   credential from a config file, and the key never appears in config, in
   argv, or in any artifact. **The named variable's value is folded into the
   redactor**, so it cannot reach a bundle even if something echoes it.
   Omitted means no `Authorization` header at all — the Ollama case. Named
   but unset is exit 2, before anything is built.
4. Unknown keys under `judge:` are errors, as everywhere else.
5. A config carrying `judge:` needs Wringer ≥ 0.2. `wring verify` and
   `wring run` neither read it nor care.

Cheap models are the point — this is a rubric check over a diff, not a
reasoning contest — but that is a documented recommendation, never a fallback
the code applies.

## 4. The rubric — `wringer.rubric.v1`

Its own file, not inline in `.wringer.yaml`: its bytes get sent over a wire,
so it needs its own shape and size limits, and the config stays tiny.

```yaml
schema_version: wringer.rubric.v1
title: Acceptance criteria
criteria:
  - id: tests-cover-the-change
    title: The change is covered by a test
    guidance: A new behaviour needs a test that fails without it.
    required: true
  - id: no-scope-creep
    title: No unrelated changes
    guidance: The diff should touch only what the task needed.
    required: false
```

Repo-relative, must resolve **inside the repo root** (no `..`, no symlink
escape), ≤ 32 KB, ≤ 20 criteria, ids are slugs like gate ids. Not under
`.wringer/` — that is gitignored, and a rubric is source, not evidence.

## 5. What the judge is allowed to see

**A closed list.** The request builder's signature is
`build_request(evidence_dir: Path, rubric: Rubric) -> dict` — there is no
parameter that could carry a loop, an iteration, a brief or a worker log, so
passing one is a type error rather than a review comment.

It reads exactly:

1. the rubric — title, and each criterion's id, title and guidance;
2. `diff.patch` from the bundle, truncated at 64 KB with a declared marker;
3. the gate table — id, command, exit code, duration, status;
4. repo facts — HEAD sha, branch, dirty flag.

Everything else in the bundle, and the whole of `.wringer/loops/`, is out of
scope by construction.

## 6. The verdict — `.wringer/verdicts/<id>/`, `wringer.judge.v1`

Evidence bundles are referenced by path, never copied — the ruling the loop
already established.

```
.wringer/verdicts/20260731-104200-9c1e/
  verdict.json     # the contract
  request.json     # the exact bytes sent, or that would be sent
  response.json    # the raw reply; absent in dry run and on transport failure
  summary.md       # for people
```

```json
{
  "schema_version": "wringer.judge.v1",
  "verdict_id": "20260731-104200-9c1e",
  "started_at": "2026-07-31T10:42:00+01:00",
  "mode": "dry_run",
  "evidence_dir": ".wringer/runs/20260731-091500-4b2a",
  "rubric": {"path": "rubric.yaml", "sha256": "3f1c…"},
  "endpoint": "http://127.0.0.1:11434/v1/chat/completions",
  "model": "qwen2.5-coder:7b",
  "verdict": "pass",
  "criteria": [
    {"id": "tests-cover-the-change", "met": true, "required": true, "reason": "…"}
  ],
  "duration_ms": 1840
}
```

**There is deliberately no `judge.jsonl`.** An event log orders things that
happen over time; a judgment is one request and one reply, and `verdict.json`
already carries `started_at` and `duration_ms`. That absence is a ruling, not
an oversight — the one place this slice departs from the bundle house style.

## 7. Testability

Everything below runs in CI with **no network and no API key**:

- **Dry run is the default**, so most tests never approach a transport.
- **A fake transport** is injected for `--send` paths; the live transport is
  one small stdlib `urllib` function, and the only untested line is the socket
  itself.
- **The isolation test that must fail loudly:** run a full `wring run` loop
  whose worker prints a distinctive sentinel string, then build a judge
  request from the resulting bundle and assert the sentinel appears **nowhere**
  in `request.json`.
- **Recorded fixtures** stand in for model replies: a pass, a fail, a
  `needs_human`, a malformed body, a timeout.
- Following the house taste, the loop and gate tests keep spawning real
  processes; only the network is faked, because a socket in CI is the one
  thing that would make the suite flaky.

## 8. Non-goals for this slice (binding)

Streaming · retries or fallback models · multiple judges or quorum ·
judge-in-the-loop (`wring run` calling the judge automatically — a later
slice, once the verdict contract has proved itself) · cost ledger ·
per-criterion numeric scoring beyond met/not-met · issue ingestion · PR or MR
creation · any git write · OpenTelemetry.

## 9. The decision this needs before adoption

Wringer currently advertises, in [README.md](README.md) line 57 and without
qualification: **"No LLM, no cloud, no uploads."**

The scoped promises survive this slice untouched — SECURITY.md's "No network"
is written about `wring verify` specifically, and `SPEC_VERIFY_V0.md` rule 6
and `evidence.py` are likewise about the evidence writer. But that README
sentence describes the *product*, and it would become false the first time
anyone types `--send`.

In a repo whose entire pitch is evidence, a stale absolute claim is worse than
a feature nobody shipped. Proposed replacement, for the maintainer to accept,
edit or reject:

> No LLM and no network — by default, and in every command that proves
> anything. `wring judge --send` is the single exception: it exists only when
> your repo declares an endpoint, it writes the exact bytes to disk before it
> opens a socket, and it never runs unless you type `--send`.

**Nothing in this slice gets built until that wording is settled.** The
implementation is otherwise unblocked: every part except the live transport
needs no network at all, so the slice can be built and shipped dry-run-only,
with `--send` landing last behind the agreed wording.

## 10. Definition of DONE

- [ ] `wring judge` dry-runs against a real bundle and writes a verdict bundle
- [ ] a bundle whose gates failed is refused (exit 3), with no request built
- [ ] `--send` against a fake transport produces pass / fail / needs_human
- [ ] a malformed or timed-out reply produces `needs_human` (exit 5), never `fail`
- [ ] the sentinel test proves no worker output reaches `request.json`
- [ ] an endpoint violating the safety rules is rejected at parse time
- [ ] `api_key_env`'s value is redacted everywhere, and absent from `request.json`
- [ ] `wring verify` and `wring run` provably cannot return 5
- [ ] schemas published under `schema/`, with the drift test extended
- [ ] docs carry a real captured transcript of a dry run
