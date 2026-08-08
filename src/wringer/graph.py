"""The graph of loops — the document and its validator (SPEC_GRAPH_V0.md).

A graph composes primitives Wringer already has. It adds **sequencing and
stopping, never power**: a node names a capability, and the capability does
what it has always done, with the same refusals, the same evidence, the same
laws. The one-sentence test for anything added here is *would this widen what
Wringer can execute, contact, or write?* — and the answer must be no.

Two rules in this file carry that, and both are rulings rather than taste:

- **Ruling 1 — a graph names capabilities, never commands.** There is no
  `command:` key, and a key that looks like one is a hard error naming
  `.wringer.yaml` as the only file that may put a command in Wringer's
  mouth. The base plan this grew from allowed `command: "wring run --json"`
  on a node, which is arbitrary shell execution wearing a node costume — in
  the same document that forbade arbitrary Python in edges.
- **Ruling 2 — state routes; only bundles gate.** Nothing here reads state
  as evidence. A router compares strings to decide where to go next; whether
  a change may be delivered is re-asked of the bundle, by the delivery code,
  every time.

Validation is strict in the house style — unknown keys are errors, because a
typo must not quietly change what a graph does. This module executes nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = "wringer.graph.v1"

# The node kinds v0 has. Each names a capability that already exists; adding
# one means wrapping something Wringer already does, never inventing it.
KINDS = ("intent", "human", "loop", "router", "deliver")

# Where a route may point besides a node. `done` and `fail` are outcomes, not
# nodes, so a graph never needs a terminal node whose only job is to stop.
SINKS = ("done", "fail")

# Ids name directories in the bundle, so they are slugs — `gate id` rules.
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*")
MAX_ID_LENGTH = 64

_TOP_LEVEL_KEYS = {"version", "id", "inputs", "state", "budgets", "nodes"}
_BUDGET_KEYS = {"wall_clock", "max_iterations"}
_KIND_KEYS = {
    "intent": {"kind", "input", "then", "writes"},
    "human": {"kind", "prompt", "then"},
    "loop": {"kind", "budgets", "writes", "then"},
    "router": {"kind", "routes", "default"},
    "deliver": {"kind", "then"},
}

# Keys that would let a graph file put a command into Wringer's mouth.
# Refused by NAME rather than by what they contain, because the danger is the
# capability, not the string: `argv: [...]` is no safer than `command: "..."`.
_COMMAND_LIKE = ("command", "run", "shell", "argv", "exec", "script", "cmd")

# The three comparison forms, parsed by grammar. There is deliberately no
# expression engine and no `eval`: a graph file is a document a stranger may
# hand you, and the only thing it may do is choose between named nodes.
_EQUALITY = re.compile(
    r"^state\.(?P<path>[a-z0-9][a-z0-9-]*)\s*(?P<op>==|!=)\s*'(?P<value>[^']*)'$"
)
_MEMBERSHIP = re.compile(
    r"^state\.(?P<path>[a-z0-9][a-z0-9-]*)\s+in\s+\[(?P<values>[^\]]*)\]$"
)
_QUOTED = re.compile(r"'([^']*)'")

_FORMS = (
    "state.<name> == 'value'",
    "state.<name> != 'value'",
    "state.<name> in ['a', 'b']",
)


class GraphError(Exception):
    """An invalid graph file (CLI exit code 2)."""


@dataclass(frozen=True)
class Route:
    """One router branch: a parsed comparison and where it goes."""

    to: str
    path: str
    op: str  # "==", "!=", "in"
    values: tuple[str, ...]
    source: str  # the `when:` text, for messages and rendering

    def matches(self, state: dict[str, str]) -> bool:
        """Missing state matches nothing — never a crash, never a guess."""
        if self.path not in state:
            return False
        actual = state[self.path]
        if self.op == "==":
            return actual == self.values[0]
        if self.op == "!=":
            return actual != self.values[0]
        return actual in self.values


@dataclass(frozen=True)
class Budgets:
    """A node's ceilings. Clamped to the graph's remainder before use —
    supervision invariant 8: budgets nest and are hard."""

    wall_clock: int | None = None
    max_iterations: int | None = None


@dataclass(frozen=True)
class Node:
    id: str
    kind: str
    then: str | None = None
    # intent
    input: str | None = None
    # human
    prompt: str | None = None
    # loop
    budgets: Budgets = field(default_factory=Budgets)
    # loop / intent — {name: state path}, the only way a node writes state
    writes: tuple[tuple[str, str], ...] = ()
    # router
    routes: tuple[Route, ...] = ()
    default: str | None = None

    @property
    def targets(self) -> tuple[str, ...]:
        """Every node or sink this one can hand control to."""
        if self.kind == "router":
            return tuple(route.to for route in self.routes) + (
                (self.default,) if self.default else ()
            )
        return (self.then,) if self.then else ()

    @property
    def state_written(self) -> tuple[str, ...]:
        return tuple(path for _, path in self.writes)

    @property
    def state_read(self) -> tuple[str, ...]:
        return tuple(route.path for route in self.routes)


@dataclass(frozen=True)
class Graph:
    id: str
    wall_clock: int
    nodes: tuple[Node, ...]
    start: str
    inputs: dict[str, str] = field(default_factory=dict)
    state: dict[str, str] = field(default_factory=dict)

    def node(self, node_id: str) -> Node:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise GraphError(f"no node '{node_id}' in this graph")

    def as_dict(self) -> dict[str, Any]:
        """The resolved graph, for `graph.resolved.json`.

        Written into the bundle so `render`, `status` and `explain` describe
        what RAN rather than what the file on disk says today — the same
        reason a run bundle records the gates it used.
        """
        return {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "start": self.start,
            "wall_clock": self.wall_clock,
            "inputs": dict(self.inputs),
            "state": dict(self.state),
            "nodes": [
                {
                    "id": node.id,
                    "kind": node.kind,
                    **({"then": node.then} if node.then else {}),
                    **({"input": node.input} if node.input else {}),
                    **({"prompt": node.prompt} if node.prompt else {}),
                    **(
                        {"writes": {name: path for name, path in node.writes}}
                        if node.writes
                        else {}
                    ),
                    **(
                        {
                            "routes": [
                                {"when": route.source, "to": route.to}
                                for route in node.routes
                            ],
                            "default": node.default,
                        }
                        if node.kind == "router"
                        else {}
                    ),
                    **(
                        {
                            "budgets": {
                                key: value
                                for key, value in (
                                    ("wall_clock", node.budgets.wall_clock),
                                    ("max_iterations", node.budgets.max_iterations),
                                )
                                if value is not None
                            }
                        }
                        if node.budgets != Budgets()
                        else {}
                    ),
                }
                for node in self.nodes
            ],
        }


def load(path: Path) -> Graph:
    if not path.is_file():
        raise GraphError(f"no graph file at {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GraphError(f"{path} could not be read: {exc}") from exc
    return parse(text, source=path.name)


def parse(text: str, source: str = "graph.yaml") -> Graph:
    """Parse and fully validate. Every problem is reported, not just the
    first — fixing a graph one error per run is a guessing game."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise GraphError(f"{source} is not valid YAML: {exc}") from exc

    problems: list[str] = []
    graph = _build(raw, source, problems)
    if problems:
        raise GraphError(_render_problems(source, problems))
    assert graph is not None
    return graph


def _render_problems(source: str, problems: list[str]) -> str:
    if len(problems) == 1:
        return f"{source}: {problems[0]}"
    listed = "\n".join(f"  - {problem}" for problem in problems)
    return f"{source}: {len(problems)} problems\n{listed}"


def _build(raw: Any, source: str, problems: list[str]) -> Graph | None:
    if not isinstance(raw, dict):
        problems.append("top level must be a mapping")
        return None

    unknown = sorted(set(raw) - _TOP_LEVEL_KEYS)
    if unknown:
        problems.append(f"unknown top-level keys: {', '.join(unknown)}")

    if raw.get("version") != 1:
        problems.append(f"'version: 1' is required (got {raw.get('version')!r})")

    graph_id = raw.get("id")
    if not isinstance(graph_id, str) or not _is_slug(graph_id):
        problems.append(
            f"'id' must be a slug — lowercase letters, digits and '-' "
            f"(got {graph_id!r}); it names directories in the bundle"
        )
        graph_id = "invalid"

    budgets = raw.get("budgets")
    wall_clock = None
    if not isinstance(budgets, dict) or budgets.get("wall_clock") is None:
        problems.append(
            "'budgets.wall_clock' is required — a graph without a wall clock "
            "is exactly the thing that runs all night (supervision "
            "invariant 3: every wait has a deadline)"
        )
    else:
        wall_clock = _positive_int(budgets.get("wall_clock"), "budgets.wall_clock",
                                   problems)

    inputs = _string_map(raw.get("inputs"), "inputs", problems)
    state = _string_map(raw.get("state"), "state", problems)

    raw_nodes = raw.get("nodes")
    if not isinstance(raw_nodes, dict) or not raw_nodes:
        problems.append("'nodes' must be a non-empty mapping")
        return None

    nodes = tuple(
        node
        for node_id, body in raw_nodes.items()
        if (node := _node(node_id, body, problems)) is not None
    )
    if not nodes:
        return None

    start = _check_structure(nodes, state, problems)

    if problems:
        return None
    return Graph(
        id=graph_id,
        wall_clock=wall_clock or 0,
        nodes=nodes,
        start=start or nodes[0].id,
        inputs=inputs,
        state=state,
    )


def _node(node_id: Any, body: Any, problems: list[str]) -> Node | None:
    if not isinstance(node_id, str) or not _is_slug(node_id):
        problems.append(f"node id {node_id!r} must be a slug")
        return None
    where = f"node '{node_id}'"
    if not isinstance(body, dict):
        problems.append(f"{where} must be a mapping")
        return None

    # Ruling 1, checked before anything else: the danger is the capability,
    # so it is refused by key NAME rather than by inspecting a value.
    for key in sorted(set(body) & set(_COMMAND_LIKE)):
        problems.append(
            f"{where} carries '{key}:'. A graph names capabilities, never "
            "commands — there is no key here that puts a command into "
            "Wringer's mouth, and the only file that may is .wringer.yaml, "
            "whose gates are already reviewed as code (SPEC_GRAPH_V0 "
            "ruling 1)"
        )

    kind = body.get("kind")
    if kind not in KINDS:
        problems.append(
            f"{where} has unknown kind {kind!r} — the kinds are: "
            f"{', '.join(KINDS)}"
        )
        return None

    unknown = sorted(set(body) - _KIND_KEYS[kind] - set(_COMMAND_LIKE))
    if unknown:
        problems.append(
            f"{where} ({kind}): unknown keys: {', '.join(unknown)}"
        )

    then = body.get("then")
    if then is not None and not isinstance(then, str):
        problems.append(f"{where}: 'then' must name a node or a sink")
        then = None

    if kind == "human" and not _non_empty(body.get("prompt")):
        problems.append(
            f"{where}: a human node needs a 'prompt' — it is what the person "
            "who finds the graph parked is being asked"
        )
    if kind == "intent" and not _non_empty(body.get("input")):
        problems.append(f"{where}: an intent node needs an 'input'")

    routes, default = (), None
    if kind == "router":
        routes, default = _router(body, where, problems)

    return Node(
        id=node_id,
        kind=kind,
        then=then,
        input=body.get("input") if isinstance(body.get("input"), str) else None,
        prompt=body.get("prompt") if isinstance(body.get("prompt"), str) else None,
        budgets=_budgets(body.get("budgets"), where, problems),
        writes=_writes(body.get("writes"), where, problems),
        routes=routes,
        default=default,
    )


def _router(
    body: dict, where: str, problems: list[str]
) -> tuple[tuple[Route, ...], str | None]:
    default = body.get("default")
    if not _non_empty(default):
        problems.append(
            f"{where}: a router needs a 'default' — a graph that can reach a "
            "router and match nothing has nowhere to go"
        )
        default = None

    raw_routes = body.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        problems.append(f"{where}: 'routes' must be a non-empty list")
        return (), default

    routes = []
    for index, entry in enumerate(raw_routes):
        if not isinstance(entry, dict) or set(entry) - {"when", "to"}:
            problems.append(f"{where}: routes[{index}] takes 'when' and 'to'")
            continue
        if not _non_empty(entry.get("to")):
            problems.append(f"{where}: routes[{index}] needs a 'to'")
            continue
        parsed = _expression(entry.get("when"), f"{where}: routes[{index}]", problems)
        if parsed is not None:
            path, op, values = parsed
            routes.append(
                Route(
                    to=entry["to"],
                    path=path,
                    op=op,
                    values=values,
                    source=str(entry.get("when")),
                )
            )
    return tuple(routes), default


def _expression(
    when: Any, where: str, problems: list[str]
) -> tuple[str, str, tuple[str, ...]] | None:
    """Parse one comparison, by grammar.

    Deliberately three forms and no more. A graph file may arrive from
    anywhere, and the widest thing it is allowed to do is choose between
    nodes its author named — so there is nothing here to evaluate, and
    nothing an attacker can reach.
    """
    if not isinstance(when, str):
        problems.append(f"{where}: 'when' must be a string")
        return None

    text = when.strip()
    if (match := _EQUALITY.match(text)) is not None:
        return match["path"], match["op"], (match["value"],)
    if (match := _MEMBERSHIP.match(text)) is not None:
        values = tuple(_QUOTED.findall(match["values"]))
        if not values:
            problems.append(f"{where}: the list in {text!r} has no quoted values")
            return None
        return match["path"], "in", values

    problems.append(
        f"{where}: {text!r} is not one of the three forms a router "
        f"understands — {', '.join(_FORMS)}. There is deliberately no "
        "expression engine here"
    )
    return None


def _budgets(raw: Any, where: str, problems: list[str]) -> Budgets:
    if raw is None:
        return Budgets()
    if not isinstance(raw, dict):
        problems.append(f"{where}: 'budgets' must be a mapping")
        return Budgets()
    unknown = sorted(set(raw) - _BUDGET_KEYS)
    if unknown:
        problems.append(f"{where}: unknown budget keys: {', '.join(unknown)}")
    return Budgets(
        wall_clock=(
            _positive_int(raw["wall_clock"], f"{where}: wall_clock", problems)
            if raw.get("wall_clock") is not None
            else None
        ),
        max_iterations=(
            _positive_int(raw["max_iterations"], f"{where}: max_iterations", problems)
            if raw.get("max_iterations") is not None
            else None
        ),
    )


def _writes(raw: Any, where: str, problems: list[str]) -> tuple[tuple[str, str], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        problems.append(f"{where}: 'writes' must be a mapping of name to state path")
        return ()
    written = []
    for name, path in raw.items():
        if not isinstance(path, str) or not path.startswith("state."):
            problems.append(
                f"{where}: writes.{name} must name a state path like "
                f"'state.build-status' (got {path!r})"
            )
            continue
        written.append((str(name), path[len("state."):]))
    return tuple(written)


def _check_structure(
    nodes: tuple[Node, ...], state: dict[str, str], problems: list[str]
) -> str | None:
    """Reachability, the single start, the DAG rule, and dataflow."""
    known = {node.id for node in nodes}
    targeted: set[str] = set()

    for node in nodes:
        for target in node.targets:
            if target in SINKS:
                continue
            if target not in known:
                problems.append(
                    f"node '{node.id}' points at '{target}', which is not a "
                    f"node and is not a sink ({' or '.join(SINKS)})"
                )
                continue
            targeted.add(target)

    starts = [node.id for node in nodes if node.id not in targeted]
    if len(starts) > 1:
        problems.append(
            f"{len(starts)} nodes are unreachable — nothing points at "
            f"{', '.join(sorted(starts)[1:])}. A graph has exactly one start "
            f"node, and here that would be '{sorted(starts)[0]}'"
        )
    elif not starts:
        problems.append("every node is targeted, so there is no start node")

    _check_acyclic(nodes, problems)
    _check_dataflow(nodes, state, starts[0] if starts else None, problems)
    return starts[0] if len(starts) == 1 else None


def _check_acyclic(nodes: tuple[Node, ...], problems: list[str]) -> None:
    """v0 is a DAG. The loop node IS the cycle, and it is bounded four ways
    (iterations, worker timeout, wall clock, the plateau breaker); a cycle
    between ordinary nodes has no bound at all."""
    edges = {node.id: [t for t in node.targets if t not in SINKS] for node in nodes}
    colour: dict[str, int] = {}

    def visit(node_id: str, trail: list[str]) -> None:
        colour[node_id] = 1  # grey: on the stack
        for target in edges.get(node_id, []):
            if colour.get(target) == 1:
                cycle = " → ".join(trail[trail.index(target):] + [target])
                problems.append(
                    f"a cycle: {cycle}. v0 graphs are acyclic — the loop node "
                    "is the only cycle, and it is bounded; a cycle between "
                    "ordinary nodes is not"
                )
                return
            if colour.get(target) is None:
                visit(target, trail + [target])
        colour[node_id] = 2  # black: finished

    for node in nodes:
        if colour.get(node.id) is None:
            visit(node.id, [node.id])


def _check_dataflow(
    nodes: tuple[Node, ...],
    state: dict[str, str],
    start: str | None,
    problems: list[str],
) -> None:
    """Every state path a router reads must be written before it runs.

    The authoring error nothing else catches: a router comparing a value
    nobody sets can only ever fall through to `default`, so the graph looks
    correct and quietly does one thing forever. Checked by walking forward
    from the start and accumulating what has been written — a writer placed
    AFTER the reader does not count, which is the half a naive
    "is it written anywhere" check would miss.
    """
    if start is None:
        return
    by_id = {node.id: node for node in nodes}
    reachable_with: dict[str, set[str]] = {}

    def walk(node_id: str, available: set[str], trail: tuple[str, ...]) -> None:
        if node_id in SINKS or node_id not in by_id or node_id in trail:
            return
        node = by_id[node_id]
        seen_before = reachable_with.get(node_id)
        if seen_before is not None and available >= seen_before:
            return
        reachable_with[node_id] = (
            available if seen_before is None else available & seen_before
        )
        for path in node.state_read:
            if path not in reachable_with[node_id]:
                problems.append(
                    f"node '{node.id}' routes on 'state.{path}', which "
                    f"nothing writes before it runs. Declare it in the "
                    f"graph's 'state:' block, or have an upstream node write "
                    f"it with 'writes:'"
                )
        onward = reachable_with[node_id] | set(node.state_written)
        for target in node.targets:
            walk(target, onward, trail + (node_id,))

    walk(start, set(state), ())


def _string_map(raw: Any, where: str, problems: list[str]) -> dict[str, str]:
    """Strings only in v0 — a router compares strings, so storing anything
    else would be storing something no route can read."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        problems.append(f"'{where}' must be a mapping")
        return {}
    out = {}
    for key, value in raw.items():
        if not isinstance(value, str):
            problems.append(
                f"{where}.{key} must be a string — v0 state is strings, "
                f"because that is what a router can compare (got {value!r})"
            )
            continue
        out[str(key)] = value
    return out


def _positive_int(value: Any, where: str, problems: list[str]) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        problems.append(f"'{where}' must be an integer of at least 1 (got {value!r})")
        return None
    return value


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_slug(value: str) -> bool:
    return bool(ID_PATTERN.fullmatch(value)) and len(value) <= MAX_ID_LENGTH


def render_mermaid(graph: Graph) -> str:
    """A Mermaid flowchart, derived from the graph — never hand-maintained.

    Four hand-maintained lists went stale in one release this month. A
    diagram is the easiest of all to let rot, so this one is generated from
    the same object the executor walks.
    """
    lines = ["flowchart TD"]
    for node in graph.nodes:
        lines.append(f'  {node.id}["{node.id}<br/><i>{node.kind}</i>"]')
    for node in graph.nodes:
        if node.kind == "router":
            for route in node.routes:
                lines.append(f"  {node.id} -->|{route.source}| {route.to}")
            if node.default:
                lines.append(f"  {node.id} -->|default| {node.default}")
        elif node.then:
            lines.append(f"  {node.id} --> {node.then}")
    return "\n".join(lines) + "\n"
