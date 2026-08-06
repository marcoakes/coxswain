# Evidence bundle schemas — `wringer.evidence.v1`

JSON Schema (draft 2020-12) for the three machine-readable files in a
`wring verify` bundle. Published so other tools can *target* the format
rather than reverse-engineer it — the point of
[RFC #2](https://github.com/marcoakes/wringer/issues/2).

| Schema | Describes |
|---|---|
| [`manifest.schema.json`](manifest.schema.json) | `manifest.json` — the run's index |
| [`evidence-event.schema.json`](evidence-event.schema.json) | **one line** of `evidence.jsonl`, not the file |
| [`gate-result.schema.json`](gate-result.schema.json) | `gates/NNN_<id>/result.json` |
| [`loop-manifest.schema.json`](loop-manifest.schema.json) | `manifest.json` of a `wring run` loop bundle |
| [`loop-event.schema.json`](loop-event.schema.json) | **one line** of a loop's `loop.jsonl` |
| [`rubric.schema.json`](rubric.schema.json) | `wringer.rubric.v1` — the acceptance criteria `wring judge` weighs a bundle against |
| [`spec.schema.json`](spec.schema.json) | `wringer.spec.v1` — `wringer.spec.yaml`, what `wring spec` drafts and a human approves |
| [`delivery-manifest.schema.json`](delivery-manifest.schema.json) | `wringer.delivery.v1` — what a verified change became: branch, commit, push, MR |
| [`acquired-manifest.schema.json`](acquired-manifest.schema.json) | `wringer.acquired.v1` — where a working copy came from |
| [`digests.schema.json`](digests.schema.json) | `wringer.digests.v1` — `digests.json`, a sha256 per file in a bundle |
| [`untracked.schema.json`](untracked.schema.json) | `wringer.untracked.v1` — superseded by v2 below, still published and still valid; a bare sha256 per *untracked* file |
| [`untracked-v2.schema.json`](untracked-v2.schema.json) | `wringer.untracked.v2` — `untracked.json`, git's *identity* (`"<mode>:<sha256>"`) per *untracked* path in the tree the gates ran against |
| [`fleet-manifest.schema.json`](fleet-manifest.schema.json) | `wringer.fleet.v1` — `manifest.json` of a `wring fleet` bundle |
| [`fleet-event.schema.json`](fleet-event.schema.json) | **one line** of a fleet's `fleet.jsonl` |
| [`judge-verdict.schema.json`](judge-verdict.schema.json) | `wringer.judge.v1` — `verdict.json`, a rubric verdict over a finished bundle |
| [`judge-request.schema.json`](judge-request.schema.json) | `request.json` — exactly what `wring judge` would send, written before any socket opens |

The loop schemas carry their own version, **`wringer.loop.v1`**, moving
independently of the evidence bundle: a loop *references* the runs it drove
(`evidence_dir`) rather than containing them, so the two formats can change
without dragging each other along.

`summary.md`, `diff.patch` and `status.txt` have no schema: they are for
people, and machines should read the three files above instead.

**`response.json` has no schema either, and that is a decision rather than
an omission.** It holds whatever the judge's endpoint returned — an
arbitrary JSON body from a service this project does not control. A schema
for it could only be permissive enough to guarantee nothing, and a
guarantee that means nothing is exactly what the rest of these files exist
to avoid. What Wringer *sends* is schematised, because that is the part
Wringer is answerable for.

## Absence is meaningful

Several keys appear only in the case they describe, and a reader must treat
"absent" as information rather than as "unknown":

- **`untracked`** on `git.status` — present only when something is untracked,
  so the common case keeps the shape the spec published.
- **`log`** on `gate.finished` — present only for a failing gate. It points
  at where a reader is being sent; it is not an inventory. Every gate's logs
  are on disk regardless.
- **`truncated`** on `gate.finished` — present only when `true`. Absent means
  the logs are whole.
- **`failed_gate`** on `run.finished` — present only when a required gate
  failed.

In a loop, the same convention holds: **`failed_gate`** on `verify.finished`
and **`timed_out`** on `worker.finished` appear only in the case they name.

Two absences carry more weight than any field:

- **A `gate.started` with no matching `gate.finished`** means the run was
  interrupted while that gate was running. No verdict is invented for it, and
  it gets no `result.json` — though its directory and logs may exist, holding
  whatever it printed before it was killed.
- **A gate that was skipped leaves nothing at all** — no event, no directory.
  It did not run, so the bundle says nothing about it. `summary.md` is the one
  place the full declared set appears.
- **A `worker.started` with no `worker.finished`** is the same story one level
  up: the loop was interrupted while the worker was running.

## What 0.2.0 freezes

`wringer.evidence.v1` has been frozen since 0.1.0. **At the 0.2.0 tag these
join it**, and become as immutable as it is:

`wringer.loop.v1` · `wringer.fleet.v1` · `wringer.judge.v1` ·
`wringer.rubric.v1` · `wringer.spec.v1` · `wringer.delivery.v1` ·
`wringer.acquired.v1` · `wringer.digests.v1`

Until that tag they are amendable in place on `main`, and every amendment is
named in its commit message. After it, a new field costs a version.

**`wringer.fleet.v1` and `wringer.judge.v1` had no schema FILE until
2026-08-05**, which made their freeze a promise nobody could check — the
shape this repository keeps finding in itself. They are published now, and
they describe what 0.2.0 writes rather than what would have been neater. One
wart is load-bearing: a fleet's `task.finished` carries **three disjoint key
sets** under one `type` (succeeded, failed, and exhausted-with-`on_exhausted:
fail`, which has no `status` at all). The schema models all three. Tidying
it would be amending a frozen format, and the difference between describing
and improving is the whole of law 7.

One correction is worth recording, because it is exactly what this rule
exists to prevent. During 0.2 development `prev_hash` was added to every
evidence event **and marked `required`** in the published schema, with the
version string left at `wringer.evidence.v1`. Two incompatible formats then
claimed one version, and this repo's own committed demo bundle — produced by
0.1.0, the receipt the README points at — failed the schema the repo
publishes. The fix was not a version bump but to stop requiring, in v1, a
field v1 never had. A test now validates `.wringer.example/` on every run;
its absence is why nobody noticed.

## Stability

`schema_version` in `manifest.json` is `wringer.evidence.v1`. These schemas
are strict — `additionalProperties` is `false` — because the version string
is what a new field is supposed to cost. Adding one is a spec change and
bumps the version; it is not an implementation detail.

**The freeze is enforced, not promised.** `frozen.json` records the sha256
of every published schema — the ten from the `v0.2.0` tag captured from the
tag itself, and each later one captured when it was published.
`tests/test_schema.py` fails if any changes a byte or disappears, and it
also fails if a schema is published *without* joining the freeze: a
published format nobody promised to keep is worse than an unpublished one.
Adding a new schema file is always allowed and is how a new format arrives;
editing a frozen one is not, because every bundle already written was
written against it.

**`wringer.untracked.v1` is the first format this rule has retired**, and it
is worth reading as the worked example. v1 recorded a bare sha256 of the
bytes `open("rb")` returned for each untracked path — which follows a
symlink, so it described what the *gates could read* rather than what *git
would commit*, and those are different objects. Fixing it meant changing what
the digests mean, which is exactly the change `additionalProperties` and a
version string exist to price. So `untracked-v2.schema.json` is a new file
carrying `wringer.untracked.v2`, `untracked.schema.json` is untouched and
stays frozen, and anything that read a v1 bundle still reads it. `wring
deliver` treats a v1 record the way it treats a bundle written before the
file existed: names compared, bytes not. The alternative — editing v1's
digest pattern so the new values fit — would have been a silent
reinterpretation of every digest in every existing bundle, which is the one
thing law 7 forbids.

## Targeting these formats

They are published so a tool can target the format rather than
reverse-engineer it, and they belong to nobody — that is the point. If you
are building against one and something is ambiguous, wrong, or missing, an
issue on this repository is the right place, and the format changing
because an outside consumer hit a wall is a good outcome rather than an
embarrassing one.

There is deliberately no formal RFC process yet. A standard needs
constituents before it needs ceremony, and inviting comment into an empty
room spends the one occasion when "here is our format, tell us what is
wrong with it" is a real question.

## How these stay true

[`tests/test_schema.py`](../tests/test_schema.py) runs real verifications —
a failing run with a truncated log and an untracked file, and an interrupted
run — and checks every object produced against the schema that claims to
describe it. If the code grows a field the schema does not declare, the suite
fails. That check is deliberately dependency-free (it compares declared
property names against written keys) so the repo keeps its "PyYAML and
nothing else" rule.

The same file also runs a real JSON Schema engine (`jsonschema`, draft
2020-12) over passing, failing and interrupted bundles, which is what catches
a schema that is itself malformed or a value that breaks a pattern. That
engine is a **dev-only** dependency — the runtime install is still PyYAML and
nothing else — and it does run in CI.

The rubric and the spec are not evidence; they are source, committed and
hand-edited. Their schemas are published for the same reason as the others: so
a tool can target the format instead of reverse-engineering it. Two fields in
them carry a safety meaning rather than a shape:

- **`human: true`** on a criterion — it is never sent to a judge, and comes
  back unscored rather than guessed at.
- **`approved`** on a spec — the interlock. `wring plan` refuses while it is
  false, it is required rather than defaulted so omission is not consent, and
  nothing but a person editing the file may set it. A tool that writes a spec
  and sets this true has not implemented the format; it has removed the only
  thing the format is for.
