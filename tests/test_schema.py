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

from wringer import cli, evidence, gates, loop, spec

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


# --- the spec and the rubric (SPEC_INTENT_V0.md) ---
#
# These two are not evidence — they are source, committed and hand-edited —
# but the same rule applies: a published schema that stops describing what the
# code writes is worse than no schema, because someone targeted it.

SPEC_CONFIG = """\
version: 1
gates:
  - id: check
    run: "true"
judge:
  endpoint: http://127.0.0.1:11434/v1/chat/completions
  model: cheap-model
  rubric: wringer.rubric.yaml
"""


def draft_and_plan(repo: Path, monkeypatch) -> None:
    """Run the real commands: `wring spec --send` then `wring plan`."""
    from test_spec import DRAFT, PRD, reply

    from wringer import judge

    (repo / "PRD.md").write_text(PRD, encoding="utf-8")
    (repo / ".wringer.yaml").write_text(SPEC_CONFIG, encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        judge, "send", lambda *args, **kwargs: reply(DRAFT)
    )
    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_OK
    # approval is a file edit, here as everywhere
    path = repo / spec.SPEC_FILENAME
    path.write_text(
        path.read_text(encoding="utf-8").replace("approved: false", "approved: true"),
        encoding="utf-8",
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "answer: ''", "answer: ISO-8601.", 1
        ),
        encoding="utf-8",
    )
    assert cli.main(["plan"]) == cli.EXIT_OK


def test_a_drafted_spec_and_its_rubric_match_the_published_schemas(
    repo, monkeypatch, capsys
):
    import yaml

    draft_and_plan(repo, monkeypatch)
    capsys.readouterr()

    check(
        yaml.safe_load((repo / spec.SPEC_FILENAME).read_text(encoding="utf-8")),
        load("spec.schema.json"),
        spec.SPEC_FILENAME,
    )
    check(
        yaml.safe_load((repo / spec.RUBRIC_FILENAME).read_text(encoding="utf-8")),
        load("rubric.schema.json"),
        spec.RUBRIC_FILENAME,
    )


def test_a_real_spec_validates_against_the_real_engine(repo, monkeypatch, capsys):
    import yaml

    built = validators()
    draft_and_plan(repo, monkeypatch)
    capsys.readouterr()

    errors: list[str] = []
    for name, filename in (
        ("spec.schema.json", spec.SPEC_FILENAME),
        ("rubric.schema.json", spec.RUBRIC_FILENAME),
    ):
        document = yaml.safe_load((repo / filename).read_text(encoding="utf-8"))
        for error in built[name].iter_errors(document):
            errors.append(f"{filename}: {error.json_path} {error.message}")

    assert not errors, "\n".join(errors)
    # the drafted spec really exercised the optional blocks, or this test
    # proves less than it looks like it does
    document = yaml.safe_load((repo / spec.SPEC_FILENAME).read_text("utf-8"))
    assert document["open_questions"] and document["gates"]
    assert any(c["human"] for c in document["criteria"])


def test_the_two_schemas_describe_one_criterion(monkeypatch):
    """The spec's criteria block IS a rubric's. Inlined in both files so
    neither needs a network fetch to resolve, so a test has to hold them
    together."""
    in_rubric = load("rubric.schema.json")["properties"]["criteria"]["items"]
    in_spec = load("spec.schema.json")["properties"]["criteria"]["items"]

    assert in_rubric == in_spec


# --- delivery and acquisition (SPEC_GET_V0.md) ---
#
# The delivery manifest is the only bundle in Wringer that describes writes to
# git. It exists because the amended law 6 buys that power with receipts, so a
# schema that quietly stopped describing it would matter more here than
# anywhere else in the program.


def deliver_for_real(repo, monkeypatch, tag):
    """Run a real verify + `wring deliver --send` against a file:// remote."""
    from test_deliver import CONFIG, MR_REPLY, fake_forge, git

    upstream = repo.parent / f"{repo.name}-{tag}.git"
    git(repo, "init", "--bare", str(upstream))
    git(repo, "remote", "add", "origin", f"file://{upstream}")
    (repo / ".wringer.yaml").write_text(CONFIG, encoding="utf-8")
    (repo / ".gitignore").write_text(".wringer/\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "config")
    git(repo, "push", "-u", "origin", "main")
    (repo / "feature.py").write_text("x = 1\n", encoding="utf-8")

    monkeypatch.chdir(repo)
    monkeypatch.setenv("FORGE_TOKEN", "t1234567")
    assert cli.main(["verify"]) == cli.EXIT_OK
    fake_forge(monkeypatch, reply=MR_REPLY)
    assert cli.main(["deliver", "--send"]) == cli.EXIT_OK
    return upstream


def test_a_real_delivery_and_acquisition_match_the_published_schemas(
    repo, monkeypatch, capsys
):
    from wringer import acquire, deliver

    upstream = deliver_for_real(repo, monkeypatch, "schema")
    assert cli.main(["get", f"file://{upstream}", "--into", "clone"]) == cli.EXIT_OK
    capsys.readouterr()

    built = validators()
    errors: list[str] = []

    written = sorted((repo / deliver.DELIVERIES_DIRNAME).iterdir())[0]
    manifest = json.loads(
        (written / deliver.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    check(manifest, load("delivery-manifest.schema.json"), "delivery manifest")
    for error in built["delivery-manifest.schema.json"].iter_errors(manifest):
        errors.append(f"delivery: {error.json_path} {error.message}")
    # the live branch really was exercised, or this test proves less than it
    # looks like it does
    assert manifest["mode"] == "live" and manifest["result"]["pushed"] is True
    assert manifest["result"]["merge_request"]["number"] == 7

    acquired = sorted((repo / acquire.ACQUIRED_DIRNAME).glob("*/manifest.json"))[0]
    record = json.loads(acquired.read_text(encoding="utf-8"))
    check(record, load("acquired-manifest.schema.json"), "acquired manifest")
    for error in built["acquired-manifest.schema.json"].iter_errors(record):
        errors.append(f"acquired: {error.json_path} {error.message}")

    assert not errors, "\n".join(errors)


def test_a_dry_run_delivery_also_matches_the_schema(repo, monkeypatch, capsys):
    """The dry run's manifest has nulls where the live one has values — the
    branch that was planned but not created, most of all."""
    from test_deliver import CONFIG, git

    from wringer import deliver

    upstream = repo.parent / f"{repo.name}-dry.git"
    git(repo, "init", "--bare", str(upstream))
    git(repo, "remote", "add", "origin", f"file://{upstream}")
    (repo / ".wringer.yaml").write_text(CONFIG, encoding="utf-8")
    (repo / ".gitignore").write_text(".wringer/\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "config")
    git(repo, "push", "-u", "origin", "main")
    (repo / "feature.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    assert cli.main(["deliver"]) == cli.EXIT_OK
    capsys.readouterr()

    written = sorted((repo / deliver.DELIVERIES_DIRNAME).iterdir())[0]
    manifest = json.loads(
        (written / deliver.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    check(manifest, load("delivery-manifest.schema.json"), "dry delivery")
    for error in validators()["delivery-manifest.schema.json"].iter_errors(
        manifest
    ):
        raise AssertionError(f"dry delivery: {error.json_path} {error.message}")
    assert manifest["mode"] == "dry_run"
    assert manifest["result"] == {
        "branch": None, "commit": None, "pushed": False, "merge_request": None
    }
    # ...but the branch it WOULD create is named, because a dry run that said
    # nothing was planned would be reporting the wrong thing
    assert manifest["branch"].startswith("wringer/")


def test_every_delivery_event_carries_the_chain(repo, monkeypatch, capsys):
    """The ledger is the receipt half of law 6's amendment, so its shape gets
    checked the way every other ledger's does."""
    from wringer import deliver

    deliver_for_real(repo, monkeypatch, "chain")
    capsys.readouterr()

    written = sorted((repo / deliver.DELIVERIES_DIRNAME).iterdir())[0]
    events = [
        json.loads(line)
        for line in (written / deliver.EVENTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert events, "a live delivery wrote no ledger"
    for event in events:
        assert {"type", "ts", "prev_hash"} <= set(event), event
    # planned before done, for every pair — condition 5
    kinds = [e["type"] for e in events]
    for planned, done in (
        ("branch.planned", "branch.created"),
        ("commit.planned", "commit.written"),
        ("push.planned", "push.done"),
        ("mr.planned", "mr.opened"),
    ):
        assert kinds.index(planned) < kinds.index(done), (planned, done)


# --- the committed demo bundle (WRINGER_RELEASE_PLAN.md R1) --------------
#
# `.wringer.example/` is the receipt the README points at as the answer to
# "how do I know?". It was produced by v0.1.0, before `prev_hash` existed.
#
# P0 added `prev_hash` to every event AND made it `required` in the published
# schema, with the version string still `wringer.evidence.v1`. Two
# incompatible formats then claimed one version, and the repo's own showcase
# bundle failed the schema the repo publishes. Nobody noticed because every
# other schema test validates a bundle produced by the current code.
#
# The fix was not a version bump: it was to stop requiring, in v1, a field
# that v1 never had. These tests are what would have caught it.

EXAMPLE_DIR = Path(__file__).resolve().parent.parent / ".wringer.example" / "runs"


def example_bundle() -> Path:
    found = sorted(p for p in EXAMPLE_DIR.iterdir() if p.is_dir())
    assert found, f"no committed demo bundle under {EXAMPLE_DIR}"
    return found[0]


def test_the_committed_demo_bundle_matches_the_published_schemas():
    """The repo's own receipt must validate against the repo's own schemas.

    If this fails, either the bundle is stale or a released schema grew a
    requirement it cannot have. Both are the same bug: a version string that
    stopped meaning one thing.
    """
    bundle = example_bundle()

    check(
        json.loads((bundle / evidence.MANIFEST_FILENAME).read_text("utf-8")),
        load("manifest.schema.json"),
        "example manifest.json",
    )
    for line in (bundle / evidence.EVIDENCE_FILENAME).read_text("utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        check(event, branch(event["type"]), f"example event {event['type']}")
    for result in sorted((bundle / evidence.GATES_DIRNAME).glob("*/result.json")):
        check(
            json.loads(result.read_text("utf-8")),
            load("gate-result.schema.json"),
            f"example {result.parent.name}",
        )


def test_the_committed_demo_bundle_validates_against_the_real_engine():
    built = validators()
    bundle = example_bundle()
    errors: list[str] = []

    for error in built["manifest.schema.json"].iter_errors(
        json.loads((bundle / evidence.MANIFEST_FILENAME).read_text("utf-8"))
    ):
        errors.append(f"manifest: {error.json_path} {error.message}")
    for line in (bundle / evidence.EVIDENCE_FILENAME).read_text("utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        for error in built["evidence-event.schema.json"].iter_errors(event):
            errors.append(f"{event['type']}: {error.json_path} {error.message}")

    assert not errors, "\n".join(errors)


def test_a_pre_chain_bundle_is_still_a_valid_v1_bundle():
    """The point of R1, stated as a property rather than a file.

    `wringer.evidence.v1` shipped without `prev_hash`. A reader of v1 must
    accept a v1 bundle. Wringer still WRITES the chain — tamper-evidence is
    unaffected going forward — and `wring attest` may one day refuse to
    attest a bundle that has none. That is an honest refusal; calling the
    bundle schema-invalid was not.
    """
    built = validators()
    event = {
        "type": "run.started",
        "ts": "2026-07-30T23:16:45.123+01:00",
        "run_id": "20260730-231645-a57c",
        "wringer_version": "0.1.0",
        "repo": "wringer",
        "sha": "a" * 40,
    }
    assert "prev_hash" not in event
    assert not list(built["evidence-event.schema.json"].iter_errors(event))

    # and the chained form is equally valid — both are v1
    chained = dict(event, prev_hash="b" * 64)
    assert not list(built["evidence-event.schema.json"].iter_errors(chained))
