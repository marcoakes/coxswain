"""The loop node and the router (SPEC_GRAPH_V0.md §3c, §3d).

The loop node **wraps** `loop.run` in process. It is not a subprocess and it
is not a second repair loop: `verify.py`'s founding rule is that shelling out
to yourself means parsing your own output, and in process is the only way the
loop's supervision machinery — pgid files, reaping, the breaker,
`wants_prove` — comes along intact.

Every loop outcome is a **routing fact, never a graph failure**. The node
completes and writes its status into state; the router decides what that
means. A graph that treated `max_iterations` as a crash could not express
"escalate to a human", which is the whole point of having a router.
"""

from __future__ import annotations

import json

from conftest import flat

from wringer import cli, graph, loop

CONFIG = """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
run:
  worker: "sh ./fix.sh"
  max_iterations: 3
"""

SPINE = """\
version: 1
id: spine
budgets:
  wall_clock: 600
nodes:
  build:
    kind: loop
    budgets:
      max_iterations: 2
      wall_clock: 300
    writes:
      status: state.build-status
    then: route
  route:
    kind: router
    routes:
      - when: "state.build-status == 'converged'"
        to: done
    default: fail
"""


def only_graph(repo):
    found = sorted((repo / graph.GRAPHS_DIRNAME).iterdir())
    assert len(found) == 1, found
    return found[0]


def events(directory) -> list[dict]:
    text = (directory / graph.EVENTS_FILENAME).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def setup(repo, *, worker_fixes: bool, body: str = SPINE) -> None:
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    fix = "echo FIXED > calc.py\n" if worker_fixes else "true\n"
    (repo / "fix.sh").write_text(fix, encoding="utf-8")
    (repo / ".wringer.yaml").write_text(CONFIG, encoding="utf-8")
    (repo / "graph.yaml").write_text(body, encoding="utf-8")


# --- the spine, end to end -------------------------------------------------


def test_a_loop_node_converges_and_the_router_sends_it_to_done(
    repo, monkeypatch, capsys
):
    """The whole point, with a real worker really fixing a real gate."""
    setup(repo, worker_fixes=True)
    monkeypatch.chdir(repo)

    assert cli.main(["graph", "run", "graph.yaml"]) == cli.EXIT_OK
    capsys.readouterr()

    directory = only_graph(repo)
    recorded = events(directory)
    assert recorded[-1]["type"] == "graph.finished"
    assert recorded[-1]["status"] == "done"

    selected = next(e for e in recorded if e["type"] == "route.selected")
    assert selected["to"] == "done"
    assert (repo / "calc.py").read_text(encoding="utf-8") == "FIXED\n"


def test_a_loop_that_does_not_converge_routes_to_fail_rather_than_crashing(
    repo, monkeypatch, capsys
):
    """`no_progress` is a routing fact. A graph that treated it as a crash
    could not express "escalate to a human", which is what routers are for."""
    setup(repo, worker_fixes=False)
    monkeypatch.chdir(repo)

    assert cli.main(["graph", "run", "graph.yaml"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    recorded = events(only_graph(repo))
    # The node COMPLETED — it did its job, which was to run the loop.
    assert any(
        e["type"] == "node.finished" and e["node_id"] == "build" for e in recorded
    )
    assert not any(e["type"] == "node.failed" for e in recorded)
    selected = next(e for e in recorded if e["type"] == "route.selected")
    assert selected["to"] == "fail"
    assert selected["when"] == "default"


def test_the_loops_own_bundle_is_referenced_never_nested(repo, monkeypatch, capsys):
    """One run, one bundle, one place — the ruling the loop already made
    about verify bundles, applied one level up."""
    setup(repo, worker_fixes=True)
    monkeypatch.chdir(repo)
    cli.main(["graph", "run", "graph.yaml"])
    capsys.readouterr()

    directory = only_graph(repo)
    reference = json.loads(
        (directory / graph.NODES_DIRNAME / "build" / "loop.ref.json").read_text("utf-8")
    )
    assert reference["loop_dir"].startswith(".wringer/loops/")
    assert (repo / reference["loop_dir"]).is_dir()
    # The loop's own bundle is NOT copied inside the graph's.
    assert not (directory / graph.NODES_DIRNAME / "build" / "loop.jsonl").exists()

    finished = next(
        e for e in events(directory)
        if e["type"] == "node.finished" and e["node_id"] == "build"
    )
    assert finished["ref"] == reference["loop_dir"]


def test_the_loop_status_reaches_state_under_its_declared_name(
    repo, monkeypatch, capsys
):
    setup(repo, worker_fixes=True)
    monkeypatch.chdir(repo)
    cli.main(["graph", "run", "graph.yaml"])
    capsys.readouterr()

    directory = only_graph(repo)
    updates = [e for e in events(directory) if e["type"] == "state.updated"]
    assert any(
        e["path"] == "build-status" and e["value"] == "converged" for e in updates
    )
    recorded = json.loads(
        (directory / graph.STATE_FILENAME).read_text(encoding="utf-8")
    )
    assert recorded["build-status"] == "converged"


# --- invariant 8: budgets nest and are hard --------------------------------


def test_a_node_budget_is_clamped_to_the_graphs_remainder(repo, monkeypatch, capsys):
    """Supervision invariant 8, verbatim: a child's budget is clamped to its
    parent's remainder. Asserted on what `loop.run` is actually HANDED, not on
    a number in a file — a clamp that is computed and then not passed is not a
    clamp."""
    body = SPINE.replace("  wall_clock: 600", "  wall_clock: 60")
    setup(repo, worker_fixes=True, body=body)
    monkeypatch.chdir(repo)

    seen: dict[str, object] = {}
    real = loop.run

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(loop, "run", spy)
    cli.main(["graph", "run", "graph.yaml"])
    capsys.readouterr()

    # The node asked for 300; the graph has 60 in total, so 60 is the ceiling.
    assert seen["wall_clock"] <= 60, (
        f"the node's wall_clock reached the loop unclamped: {seen['wall_clock']}"
    )
    assert seen["max_iterations"] == 2


def test_a_graph_out_of_budget_stops_rather_than_starting_a_loop(
    repo, monkeypatch, capsys
):
    """Exhaustion is an outcome, not an error (invariant 8) — and the loop
    must not be started at all, because a budget that only stops things
    afterwards has not bounded anything."""
    body = SPINE.replace("  wall_clock: 600", "  wall_clock: 1")
    setup(repo, worker_fixes=True, body=body)
    monkeypatch.chdir(repo)

    started: list[str] = []
    monkeypatch.setattr(
        loop, "run", lambda *a, **k: started.append("ran") or (_ for _ in ()).throw(
            AssertionError("the loop ran with no budget left")
        )
    )
    # Burn the graph's whole budget before the loop node is reached.
    monkeypatch.setattr(graph, "_elapsed", lambda started_at: 999.0)

    code = cli.main(["graph", "run", "graph.yaml"])
    printed = capsys.readouterr()

    assert code == cli.EXIT_GATE_FAILED
    assert not started
    recorded = events(only_graph(repo))
    assert any(e["type"] == "budget.exhausted" for e in recorded)
    assert "budget" in flat(printed.out).lower()


# --- the router ------------------------------------------------------------


def test_every_loop_reason_is_a_string_a_router_can_match(repo):
    """Taken from `loop.py` rather than from memory: a router comparing
    against a reason the loop never emits is a route that silently never
    fires, which is the failure the dataflow check exists to prevent."""
    body = """\
version: 1
id: reasons
budgets:
  wall_clock: 600
nodes:
  build:
    kind: loop
    writes:
      status: state.build-status
    then: route
  route:
    kind: router
    routes:
      - when: "state.build-status in ['converged', 'max_iterations', \
'no_progress', 'oscillating', 'budget_exhausted', 'interrupted']"
        to: done
    default: fail
"""
    parsed = graph.parse(body, "g.yaml")
    matched = set(parsed.node("route").routes[0].values)
    assert graph.LOOP_REASONS <= matched, (
        f"these loop reasons no router in the example set matches: "
        f"{sorted(graph.LOOP_REASONS - matched)}"
    )


def test_a_router_falls_through_to_default_when_nothing_matches(repo):
    node = graph.parse(SPINE, "g.yaml").node("route")
    assert node.routes[0].matches({"build-status": "converged"})
    assert not node.routes[0].matches({"build-status": "no_progress"})
    assert not node.routes[0].matches({}), "missing state must match nothing"


def test_each_node_finishes_exactly_once_in_the_ledger(repo, monkeypatch, capsys):
    """An append-only ledger with a duplicated event is a ledger that
    disagrees with itself about what happened — and `Replay` counts these to
    decide what must not be re-run."""
    setup(repo, worker_fixes=True)
    monkeypatch.chdir(repo)
    cli.main(["graph", "run", "graph.yaml"])
    capsys.readouterr()

    finished = [
        e["node_id"] for e in events(only_graph(repo)) if e["type"] == "node.finished"
    ]
    assert len(finished) == len(set(finished)), (
        f"a node finished more than once: {finished}"
    )
