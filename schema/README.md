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

The loop schemas carry their own version, **`wringer.loop.v1`**, moving
independently of the evidence bundle: a loop *references* the runs it drove
(`evidence_dir`) rather than containing them, so the two formats can change
without dragging each other along.

`summary.md`, `diff.patch` and `status.txt` have no schema: they are for
people, and machines should read the three files above instead.

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

## Stability

`schema_version` in `manifest.json` is `wringer.evidence.v1`. These schemas
are strict — `additionalProperties` is `false` — because the version string
is what a new field is supposed to cost. Adding one is a spec change and
bumps the version; it is not an implementation detail.

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
