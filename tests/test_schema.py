"""The published schemas must describe what the code actually writes.

`schema/` is a contract other tools target, so the failure that matters is
drift: someone adds a field to an event and the schema quietly stops being
true. These tests run real verifications and check every object the run
produced against the schema that claims to describe it — no JSON Schema
engine, and so no dependency, because the only rule being enforced is
"declared properties and what got written are the same set".
"""

from __future__ import annotations

import json
from pathlib import Path

from wringer import cli, evidence, gates, loop

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"

FAILING = """\
version: 1
gates:
  - id: noisy
    run: "yes wringer | head -c 1200000; exit 0"
  - id: broken
    run: "echo boom >&2; exit 3"
  - id: never
    run: "echo unreached"
"""

TWO_GATES = """\
version: 1
gates:
  - id: quick
    run: "true"
  - id: slow
    run: "true"
"""


def load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def check(obj: dict, schema: dict, where: str) -> None:
    """Every key written is declared, and every declared requirement is met."""
    allowed = set(schema["properties"])
    written = set(obj)
    assert written <= allowed, f"{where}: undeclared keys {sorted(written - allowed)}"
    missing = set(schema.get("required", ())) - written
    assert not missing, f"{where}: missing required {sorted(missing)}"


def branch(event_type: str, schema: str = "evidence-event.schema.json") -> dict:
    """The event-schema branch describing one `type`."""
    for option in load(schema)["oneOf"]:
        if option["properties"]["type"]["const"] == event_type:
            return option
    raise AssertionError(f"no schema branch for {event_type!r} in {schema}")


def only_bundle(root: Path) -> Path:
    runs = sorted((root / evidence.RUNS_DIRNAME).iterdir())
    assert len(runs) == 1, runs
    return runs[0]


def test_the_schemas_are_valid_json_and_agree_on_the_version():
    manifest = load("manifest.schema.json")
    assert manifest["properties"]["schema_version"]["const"] == evidence.SCHEMA_VERSION
    for name in (
        "manifest.schema.json",
        "gate-result.schema.json",
        "evidence-event.schema.json",
    ):
        schema = load(name)
        assert schema["$schema"].startswith("https://json-schema.org/")
        assert schema["title"]


def test_a_failing_run_matches_the_published_schemas(
    repo, write_config, monkeypatch, capsys
):
    """Covers the shapes only a failure produces: `log` and `truncated` on
    gate.finished, `failed_gate` on run.finished, and `untracked` on
    git.status."""
    write_config(repo, FAILING)
    (repo / "loose-file.txt").write_text("untracked\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()
    bundle = only_bundle(repo)

    check(
        json.loads((bundle / evidence.MANIFEST_FILENAME).read_text(encoding="utf-8")),
        load("manifest.schema.json"),
        "manifest.json",
    )

    seen = set()
    for line in (bundle / evidence.EVIDENCE_FILENAME).read_text("utf-8").splitlines():
        event = json.loads(line)
        check(event, branch(event["type"]), f"event {event['type']}")
        seen.add(event["type"])
    assert seen == {
        "run.started",
        "git.status",
        "gate.started",
        "gate.finished",
        "run.finished",
    }

    for result in sorted((bundle / evidence.GATES_DIRNAME).glob("*/result.json")):
        check(
            json.loads(result.read_text(encoding="utf-8")),
            load("gate-result.schema.json"),
            result.parent.name,
        )

    # the optional keys really were exercised, or this test proves less than
    # it looks like it does
    events = [
        json.loads(line)
        for line in (bundle / evidence.EVIDENCE_FILENAME)
        .read_text("utf-8")
        .splitlines()
    ]
    finished = [e for e in events if e["type"] == "gate.finished"]
    assert any(e.get("truncated") for e in finished)
    assert any("log" in e for e in finished)
    assert any("untracked" in e for e in events if e["type"] == "git.status")
    assert any("failed_gate" in e for e in events if e["type"] == "run.finished")


def test_a_loop_matches_the_published_loop_schemas(repo, monkeypatch, capsys):
    """Two loops, so every event type and both optional keys are exercised:
    one that converges, one whose worker overruns its timeout."""
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
run:
  worker: "echo FIXED > calc.py"
  max_iterations: 3
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)
    assert cli.main(["run"]) == cli.EXIT_OK

    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
run:
  worker: "sleep 30"
  max_iterations: 2
  worker_timeout: 1
""",
        encoding="utf-8",
    )
    assert cli.main(["run"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    seen: set[str] = set()
    optional: set[str] = set()
    loops = sorted((repo / loop.LOOPS_DIRNAME).iterdir())
    assert len(loops) == 2

    for loop_dir in loops:
        check(
            json.loads((loop_dir / loop.MANIFEST_FILENAME).read_text("utf-8")),
            load("loop-manifest.schema.json"),
            f"{loop_dir.name}/manifest.json",
        )
        for line in (loop_dir / loop.EVENTS_FILENAME).read_text("utf-8").splitlines():
            event = json.loads(line)
            check(
                event,
                branch(event["type"], "loop-event.schema.json"),
                f"{loop_dir.name} event {event['type']}",
            )
            seen.add(event["type"])
            optional |= {k for k in ("failed_gate", "timed_out") if k in event}

    assert seen == {
        "loop.started",
        "iteration.started",
        "verify.finished",
        "worker.started",
        "worker.finished",
        "loop.finished",
    }
    # the keys that appear only in the case they describe really appeared
    assert optional == {"failed_gate", "timed_out"}


def test_an_interrupted_run_matches_the_published_schemas(
    repo, write_config, monkeypatch, capsys
):
    write_config(repo, TWO_GATES)
    monkeypatch.chdir(repo)

    real = gates.run
    calls = []

    def stop_on_the_second(*args, **kwargs):
        calls.append(None)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return real(*args, **kwargs)

    monkeypatch.setattr(gates, "run", stop_on_the_second)

    assert cli.main(["verify"]) == cli.EXIT_INTERRUPTED
    capsys.readouterr()
    bundle = only_bundle(repo)

    manifest = json.loads(
        (bundle / evidence.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    check(manifest, load("manifest.schema.json"), "manifest.json")
    assert manifest["result"]["status"] == "interrupted"

    for line in (bundle / evidence.EVIDENCE_FILENAME).read_text("utf-8").splitlines():
        event = json.loads(line)
        check(event, branch(event["type"]), f"event {event['type']}")


# --- the real engine, now that jsonschema is a dev dependency ---
#
# The dependency-free checks above catch DRIFT: a key the code writes that
# the schema does not declare. They cannot catch a schema that is itself
# malformed, or a value that violates a pattern or enum. This does — and it
# runs in CI, which is the point of adding the dependency.


def validators():
    from jsonschema import Draft202012Validator

    built = {}
    for path in SCHEMA_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)  # the schema itself is legal
        built[path.name] = Draft202012Validator(schema)
    return built


def test_every_published_schema_is_a_legal_json_schema():
    built = validators()

    assert len(built) >= 5, sorted(built)


def test_a_real_bundle_validates_against_the_real_engine(
    repo, write_config, monkeypatch, capsys
):
    """End to end with a genuine draft-2020-12 validator: every event, the
    manifest, and every gate result from an actual failing run."""
    built = validators()
    write_config(repo, FAILING)
    (repo / "loose.txt").write_text("untracked\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()
    bundle = only_bundle(repo)

    errors: list[str] = []

    def collect(validator_name: str, instance: object, where: str) -> None:
        for error in built[validator_name].iter_errors(instance):
            errors.append(f"{where}: {error.json_path} {error.message}")

    collect(
        "manifest.schema.json",
        json.loads((bundle / evidence.MANIFEST_FILENAME).read_text("utf-8")),
        "manifest.json",
    )
    for line in (bundle / evidence.EVIDENCE_FILENAME).read_text("utf-8").splitlines():
        event = json.loads(line)
        collect("evidence-event.schema.json", event, f"event {event['type']}")
    for result in sorted((bundle / evidence.GATES_DIRNAME).glob("*/result.json")):
        collect(
            "gate-result.schema.json",
            json.loads(result.read_text("utf-8")),
            result.parent.name,
        )

    assert not errors, "\n".join(errors)


def test_a_real_loop_bundle_validates_against_the_real_engine(
    repo, monkeypatch, capsys
):
    built = validators()
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED calc.py"
run:
  worker: "echo FIXED > calc.py"
  max_iterations: 3
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)
    assert cli.main(["run"]) == cli.EXIT_OK
    capsys.readouterr()
    loop_dir = sorted((repo / loop.LOOPS_DIRNAME).iterdir())[0]

    errors: list[str] = []
    for error in built["loop-manifest.schema.json"].iter_errors(
        json.loads((loop_dir / loop.MANIFEST_FILENAME).read_text("utf-8"))
    ):
        errors.append(f"loop manifest: {error.message}")
    for line in (loop_dir / loop.EVENTS_FILENAME).read_text("utf-8").splitlines():
        event = json.loads(line)
        for error in built["loop-event.schema.json"].iter_errors(event):
            errors.append(f"{event['type']}: {error.message}")

    assert not errors, "\n".join(errors)
