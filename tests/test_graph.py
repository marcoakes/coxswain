"""The graph file and its validator (SPEC_GRAPH_V0.md §3).

A graph is a document before it is an execution, and every defect this
validator catches is one a person would otherwise meet halfway through a run
that had already spent a worker's time. So the rules are checked here, on the
file, with no execution anywhere in this module.

The two that matter most are not schema checks at all:

- **no `command:` anywhere** (ruling 1). The base plan let a node carry a
  shell string, which is arbitrary execution wearing a node costume. A
  stranger's graph file must be exactly as safe to validate and run as the
  same Wringer commands typed by hand.
- **dataflow** — a router that reads state nothing upstream writes is an
  authoring error the base plan could not see, and it fails at runtime as a
  route that silently never matches.
"""

from __future__ import annotations

import pytest

from wringer import cli, graph

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


def write(repo, body: str, name: str = "graph.yaml"):
    path = repo / name
    path.write_text(body, encoding="utf-8")
    return path


# --- the shape parses ------------------------------------------------------


def test_a_minimal_graph_parses(repo):
    loaded = graph.load(write(repo, MINIMAL))

    assert loaded.id == "tiny"
    assert loaded.wall_clock == 600
    assert loaded.start == "only"
    assert [node.id for node in loaded.nodes] == ["only"]


def test_the_example_graph_validates():
    """The one the docs point at. If this ever fails, the example is a lie."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    example = root / "examples/graphs/issue-to-mr.yaml"
    if not example.is_file():
        pytest.skip("examples/ is not part of the distribution")

    loaded = graph.load(example)
    assert loaded.start
    assert any(node.kind == "loop" for node in loaded.nodes)
    assert any(node.kind == "deliver" for node in loaded.nodes)


def test_validate_exits_zero_on_the_example(repo, monkeypatch, capsys):
    write(repo, MINIMAL)
    monkeypatch.chdir(repo)

    assert cli.main(["graph", "validate", "graph.yaml"]) == cli.EXIT_OK
    assert "valid" in capsys.readouterr().out


# --- ruling 1: a graph names capabilities, never commands ------------------


@pytest.mark.parametrize(
    "line",
    [
        '    command: "wring run --json"',
        '    run: "pytest -q"',
        '    shell: "echo hi"',
        '    argv: ["wring", "run"]',
    ],
)
def test_a_graph_carrying_a_command_is_refused(repo, line: str):
    """SPEC_GRAPH_V0 ruling 1. The base plan this grew from let a node say
    `command: "wring run --json"` — arbitrary shell execution wearing a node
    costume, in the same document that forbade arbitrary Python in edges.

    The refusal has to name the reason, because the author believed they were
    writing something reasonable."""
    body = MINIMAL.replace(
        '    prompt: "Look at it."', f'    prompt: "Look at it."\n{line}'
    )
    with pytest.raises(graph.GraphError) as caught:
        graph.parse(body, source="graph.yaml")

    assert "command" in str(caught.value).lower()
    assert ".wringer.yaml" in str(caught.value), (
        "the refusal must say where commands legitimately live"
    )


# --- structure -------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("version: 1\n", "version"),
        ("id: tiny\n", "id"),
        ("  wall_clock: 600\n", "wall_clock"),
    ],
)
def test_a_missing_required_key_is_refused(repo, mutation: str, expected: str):
    with pytest.raises(graph.GraphError, match=expected):
        graph.parse(MINIMAL.replace(mutation, ""), source="graph.yaml")


def test_an_unknown_node_kind_names_the_kinds_that_exist(repo):
    with pytest.raises(graph.GraphError) as caught:
        graph.parse(MINIMAL.replace("kind: human", "kind: worker"), "graph.yaml")

    message = str(caught.value)
    assert "worker" in message
    for kind in ("intent", "human", "loop", "router", "deliver"):
        assert kind in message


def test_an_unknown_key_is_an_error_like_every_other_config(repo):
    body = MINIMAL.replace(
        '    prompt: "Look at it."', '    prompt: "Look at it."\n    retries: 3'
    )
    with pytest.raises(graph.GraphError, match="retries"):
        graph.parse(body, "graph.yaml")


def test_an_edge_to_nowhere_is_refused(repo):
    with pytest.raises(graph.GraphError, match="nowhere"):
        graph.parse(MINIMAL.replace("then: done", "then: nowhere"), "graph.yaml")


def test_done_and_fail_are_sinks_not_missing_nodes(repo):
    for sink in ("done", "fail"):
        loaded = graph.parse(MINIMAL.replace("then: done", f"then: {sink}"), "g.yaml")
        assert loaded.nodes[0].then == sink


TWO_STARTS = """\
version: 1
id: two
budgets:
  wall_clock: 600
nodes:
  a:
    kind: human
    prompt: "a"
    then: done
  b:
    kind: human
    prompt: "b"
    then: done
"""


def test_more_than_one_start_node_is_refused(repo):
    with pytest.raises(graph.GraphError, match="start"):
        graph.parse(TWO_STARTS, "graph.yaml")


CYCLE = """\
version: 1
id: cycle
budgets:
  wall_clock: 600
nodes:
  a:
    kind: human
    prompt: "a"
    then: b
  b:
    kind: human
    prompt: "b"
    then: a
"""


def test_a_cycle_is_refused_because_v0_is_a_dag(repo):
    """The loop node IS the cycle, and it is bounded four ways. A cycle
    between ordinary nodes has no bound at all."""
    with pytest.raises(graph.GraphError, match="cycle"):
        graph.parse(CYCLE, "graph.yaml")


UNREACHABLE = """\
version: 1
id: orphan
budgets:
  wall_clock: 600
nodes:
  a:
    kind: human
    prompt: "a"
    then: done
  stranded:
    kind: human
    prompt: "nobody points here"
    then: done
"""


def test_an_unreachable_node_is_refused(repo):
    """Caught as two starts first — but the message must name the real
    problem, because "two start nodes" is baffling when you wrote one."""
    with pytest.raises(graph.GraphError) as caught:
        graph.parse(UNREACHABLE, "graph.yaml")
    assert "stranded" in str(caught.value)


# --- routers ---------------------------------------------------------------

ROUTED = """\
version: 1
id: routed
budgets:
  wall_clock: 600
state:
  build-status: "unknown"
nodes:
  route:
    kind: router
    routes:
      - when: "state.build-status == 'converged'"
        to: done
    default: fail
"""


def test_a_router_parses_its_three_forms(repo):
    for when in (
        "state.build-status == 'converged'",
        "state.build-status != 'converged'",
        "state.build-status in ['failed', 'no_progress']",
    ):
        loaded = graph.parse(
            ROUTED.replace("state.build-status == 'converged'", when), "g.yaml"
        )
        # Stored WITHOUT the `state.` prefix: it is a key into the state
        # mapping, and carrying the prefix around would mean stripping it
        # at every read.
        assert loaded.nodes[0].routes[0].path == "build-status"


@pytest.mark.parametrize(
    "when",
    [
        "state.x == y",                       # unquoted right side
        "__import__('os').system('rm -rf /')",  # the reason there is no eval
        "state.x > 3",                        # no numeric comparison in v0
        "state.x == 'a' and state.y == 'b'",  # no boolean composition
    ],
)
def test_an_expression_outside_the_three_forms_is_refused(repo, when: str):
    """There is no expression engine and no eval. Anything else is a
    validation error that names the forms that exist."""
    with pytest.raises(graph.GraphError) as caught:
        graph.parse(ROUTED.replace("state.build-status == 'converged'", when), "g.yaml")
    assert "==" in str(caught.value)


def test_a_router_without_a_default_is_refused(repo):
    with pytest.raises(graph.GraphError, match="default"):
        graph.parse(ROUTED.replace("    default: fail\n", ""), "g.yaml")


# --- dataflow: the check the base plan could not make ----------------------


def test_a_router_reading_state_nobody_writes_is_refused(repo):
    """The authoring error that fails as a route which silently never
    matches. Nothing upstream declares `build-status`, so the comparison can
    only ever fall through to `default` — the graph looks fine and quietly
    does one thing forever."""
    body = ROUTED.replace('state:\n  build-status: "unknown"\n', "")
    with pytest.raises(graph.GraphError) as caught:
        graph.parse(body, "g.yaml")

    message = str(caught.value)
    assert "build-status" in message
    assert "writes" in message or "state" in message


def test_state_written_by_an_upstream_node_satisfies_the_check(repo):
    """The positive half: a loop node's `writes` is a legitimate source."""
    body = """\
version: 1
id: flows
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
      - when: "state.build-status == 'converged'"
        to: done
    default: fail
"""
    loaded = graph.parse(body, "g.yaml")
    assert loaded.start == "build"


def test_a_downstream_writer_does_not_satisfy_an_upstream_reader(repo):
    """`writes` only counts if it happens BEFORE the router runs. A writer
    that sits after the reader is the same silent fall-through."""
    body = """\
version: 1
id: backwards
budgets:
  wall_clock: 600
nodes:
  route:
    kind: router
    routes:
      - when: "state.build-status == 'converged'"
        to: build
    default: fail
  build:
    kind: loop
    writes:
      status: state.build-status
    then: done
"""
    with pytest.raises(graph.GraphError, match="build-status"):
        graph.parse(body, "g.yaml")


# --- the CLI ---------------------------------------------------------------


def test_validate_reports_every_problem_not_only_the_first(repo, monkeypatch, capsys):
    """A validator that stops at the first error makes fixing a graph a
    guessing game played one round at a time."""
    # Two separate nodes, because a node whose KIND did not parse is
    # dropped — validating the keys of a node we cannot identify would
    # invent errors rather than report them.
    body = """\
version: 1
id: several
budgets:
  wall_clock: 600
nodes:
  first:
    kind: worker
    then: second
  second:
    kind: human
    prompt: "hi"
    then: nowhere
"""
    write(repo, body)
    monkeypatch.chdir(repo)

    assert cli.main(["graph", "validate", "graph.yaml"]) == cli.EXIT_CONFIG
    err = capsys.readouterr().err
    assert "worker" in err and "nowhere" in err


def test_validate_on_a_missing_file_is_a_config_error(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    assert cli.main(["graph", "validate", "nope.yaml"]) == cli.EXIT_CONFIG
    assert "nope.yaml" in capsys.readouterr().err
