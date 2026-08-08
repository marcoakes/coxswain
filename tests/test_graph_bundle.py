"""The graph run bundle (SPEC_GRAPH_V0.md §4).

Every house rule the other bundles obey, and for the reasons this month
supplied rather than out of symmetry:

- **chained from day one**, so `wring audit`'s machinery covers graph runs
  without a retrofit;
- **a redactor built from `declared_secret_names` on every write**, because
  two of this month's leaks were write paths that skipped one;
- **`state.json` is a convenience snapshot and the ledger is the truth**, so
  a doctored snapshot changes nothing;
- **`digests.json` last**, covering everything else the run wrote.
"""

from __future__ import annotations

import json

import pytest

from wringer import evidence, graph

MINIMAL = """\
version: 1
id: tiny
budgets:
  wall_clock: 600
nodes:
  only:
    kind: human
    prompt: "Look at it."
    then: done
"""


def events(bundle) -> list[dict]:
    text = (bundle.directory / graph.EVENTS_FILENAME).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_a_bundle_lands_under_wringer_graphs(repo):
    bundle = graph.Bundle.create(repo / graph.GRAPHS_DIRNAME)

    assert bundle.directory.is_dir()
    assert bundle.directory.parent.name == "graphs"
    assert bundle.directory.parent.parent.name == ".wringer"
    # The house id format, so graph runs sort beside every other artifact.
    assert bundle.graph_run_id == bundle.directory.name


def test_every_event_is_chained(repo):
    """`prev_hash` from the first line, so a graph bundle is tamper-evident
    the same way a loop's is — and `wring audit` needs no special case."""
    bundle = graph.Bundle.create(repo / graph.GRAPHS_DIRNAME)
    bundle.event("graph.started", graph_id="tiny")
    bundle.event("node.started", node_id="only", kind="human")

    recorded = events(bundle)
    assert [e["type"] for e in recorded] == ["graph.started", "node.started"]
    assert recorded[0]["prev_hash"] == "0" * 64
    assert recorded[1]["prev_hash"] != recorded[0]["prev_hash"]
    for event in recorded:
        assert event["ts"]


def test_the_chain_is_the_one_wring_audit_already_checks(repo):
    """Not a lookalike — the same function, so the guarantee is the same
    guarantee rather than a second implementation of it."""
    from wringer import attest

    bundle = graph.Bundle.create(repo / graph.GRAPHS_DIRNAME)
    bundle.event("graph.started", graph_id="tiny")
    bundle.event("graph.finished", status="done")

    attest.check_chain(bundle.directory / graph.EVENTS_FILENAME, "graph")


def test_a_secret_never_reaches_a_graph_event(repo, monkeypatch):
    """The bundle owns the redactor, so a caller cannot forget."""
    secret = "notarealtoken-graph-4b1f09c7d2e4"
    monkeypatch.setenv("WRINGER_GRAPH_TOKEN", secret)
    from wringer.redact import Redactor

    bundle = graph.Bundle.create(
        repo / graph.GRAPHS_DIRNAME, redactor=Redactor.from_config({})
    )
    bundle.event("node.finished", node_id="only", detail=f"saw {secret}")

    body = (bundle.directory / graph.EVENTS_FILENAME).read_text(encoding="utf-8")
    assert secret not in body
    assert "[REDACTED]" in body


def test_the_resolved_graph_is_written_and_round_trips(repo):
    """`graph.resolved.json` is what `render`, `status` and `explain` read, so
    they describe what RAN rather than what the file says today."""
    loaded = graph.parse(MINIMAL, "graph.yaml")
    bundle = graph.Bundle.create(repo / graph.GRAPHS_DIRNAME)
    bundle.write_resolved(loaded)

    recorded = json.loads(
        (bundle.directory / graph.RESOLVED_FILENAME).read_text(encoding="utf-8")
    )
    assert recorded["schema_version"] == graph.SCHEMA_VERSION
    assert recorded["id"] == "tiny"
    assert recorded["start"] == "only"
    assert [node["id"] for node in recorded["nodes"]] == ["only"]


def test_state_is_a_snapshot_and_the_ledger_is_the_truth(repo):
    """Written for convenience, never read back as authority. The loop's
    resume ruling, applied to graphs before anything can depend on it."""
    bundle = graph.Bundle.create(repo / graph.GRAPHS_DIRNAME)
    bundle.write_state({"approved": "false"})

    recorded = json.loads(
        (bundle.directory / graph.STATE_FILENAME).read_text(encoding="utf-8")
    )
    assert recorded == {"approved": "false"}


def test_digests_are_written_last_and_cover_everything(repo):
    bundle = graph.Bundle.create(repo / graph.GRAPHS_DIRNAME)
    bundle.event("graph.started", graph_id="tiny")
    bundle.write_resolved(graph.parse(MINIMAL, "graph.yaml"))
    bundle.write_state({"approved": "false"})
    bundle.write_manifest(status="parked", reason="human approval required",
                          current="only", graph_id="tiny")
    bundle.write_digests()

    digests = json.loads(
        (bundle.directory / evidence.DIGESTS_FILENAME).read_text(encoding="utf-8")
    )
    covered = set(digests["files"])
    for name in (
        graph.EVENTS_FILENAME,
        graph.RESOLVED_FILENAME,
        graph.STATE_FILENAME,
        graph.MANIFEST_FILENAME,
    ):
        assert name in covered, f"{name} is not covered by digests.json"


def test_the_manifest_carries_the_schema_version(repo):
    bundle = graph.Bundle.create(repo / graph.GRAPHS_DIRNAME)
    bundle.write_manifest(status="done", reason="done", current=None, graph_id="tiny")

    manifest = json.loads(
        (bundle.directory / graph.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == graph.SCHEMA_VERSION
    assert manifest["result"]["status"] == "done"


def test_a_node_directory_is_named_for_its_node(repo):
    bundle = graph.Bundle.create(repo / graph.GRAPHS_DIRNAME)
    directory = bundle.node_dir("approve-plan")

    assert directory.is_dir()
    assert directory.parent.name == "nodes"
    assert directory.name == "approve-plan"


# --- the published schemas -------------------------------------------------


def test_the_graph_schemas_are_published_and_frozen():
    """A published schema outside the freeze is a format nobody promised to
    keep. New files are additive — the freeze records them, it does not
    forbid them."""
    from pathlib import Path

    schema_dir = Path(__file__).resolve().parent.parent / "schema"
    if not schema_dir.is_dir():
        pytest.skip("schema/ is not part of the distribution")

    frozen = json.loads((schema_dir / "frozen.json").read_text(encoding="utf-8"))
    for name in ("graph-event.schema.json", "graph-manifest.schema.json"):
        assert (schema_dir / name).is_file(), f"{name} is not published"
        assert name in frozen["schemas"], f"{name} is published but not frozen"
