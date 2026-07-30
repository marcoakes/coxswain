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

Two absences carry more weight than any field:

- **A `gate.started` with no matching `gate.finished`** means the run was
  interrupted while that gate was running. No verdict is invented for it, and
  it gets no `result.json` — though its directory and logs may exist, holding
  whatever it printed before it was killed.
- **A gate that was skipped leaves nothing at all** — no event, no directory.
  It did not run, so the bundle says nothing about it. `summary.md` is the one
  place the full declared set appears.

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

They have also been validated with a real JSON Schema engine
(`jsonschema`, draft 2020-12) against passing, failing and interrupted
bundles. That engine is **not** a dependency of this project and CI does not
run it, so treat the in-repo test as the enforced check and the external
validation as a point-in-time confirmation.
