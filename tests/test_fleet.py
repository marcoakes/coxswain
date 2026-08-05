"""`wring fleet` — hundreds of tasks, bounded blast radius.

SPEC_SUPERVISION_V0.md §S3. Every worker here is a shell one-liner and every
child is an ordinary `wring run`, so the fleet's own logic is what is under
test rather than anybody's intelligence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wringer import cli, config, fleet

CHILD_CONFIG = """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED work.txt"
run:
  worker: {worker}
  max_iterations: 2
  worker_timeout: 30
"""

FLEET_CONFIG = """\
version: 1
gates:
  - id: noop
    run: "true"
fleet:
  concurrency: {concurrency}
  deadline: 300
  progress_window: 60
  retries: {retries}
"""


def make_task(repo: Path, task_id: str, worker: str, fixed: bool = False) -> dict:
    """A task directory: its own git repo, its own gates, its own worker."""
    import subprocess

    workdir = repo / "tasks" / task_id
    (workdir).mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=workdir, check=True)
    for key, value in (("user.email", "t@e.invalid"), ("user.name", "t"),
                       ("commit.gpgsign", "false")):
        subprocess.run(["git", "config", key, value], cwd=workdir, check=True)
    (workdir / "work.txt").write_text(
        "FIXED\n" if fixed else "BROKEN\n", encoding="utf-8"
    )
    (workdir / ".gitignore").write_text(".wringer/\n", encoding="utf-8")
    (workdir / ".wringer.yaml").write_text(
        CHILD_CONFIG.format(worker=json.dumps(worker)), encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=workdir, check=True)

    brief = repo / "briefs" / f"{task_id}.md"
    brief.parent.mkdir(exist_ok=True)
    brief.write_text(f"# {task_id}\nMake the gate pass.\n", encoding="utf-8")
    return {
        "id": task_id,
        "brief": str(brief.relative_to(repo)),
        "dir": str(workdir.relative_to(repo)),
    }


def write_fleet(repo: Path, tasks: list[dict], concurrency: int = 4,
                retries: int = 1) -> Path:
    (repo / ".wringer.yaml").write_text(
        FLEET_CONFIG.format(concurrency=concurrency, retries=retries),
        encoding="utf-8",
    )
    path = repo / "tasks.jsonl"
    path.write_text(
        "\n".join(json.dumps(t) for t in tasks) + "\n", encoding="utf-8"
    )
    return path


def manifest(repo: Path) -> dict:
    found = sorted((repo / fleet.FLEETS_DIRNAME).iterdir())
    assert len(found) == 1, found
    return json.loads(
        (found[0] / fleet.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )


# --- the task file: references, never blobs ---


def test_tasks_are_references_not_payloads(tmp_path):
    path = tmp_path / "tasks.jsonl"
    path.write_text(
        json.dumps({"id": "a", "brief": "b.md", "dir": "d"}) + "\n", encoding="utf-8"
    )

    tasks = fleet.load_tasks(path)

    assert tasks == [fleet.Task(id="a", brief="b.md", dir="d")]


@pytest.mark.parametrize(
    "line, match",
    [
        ('{"id": "a", "brief": "b"}', "'dir'"),
        ('{"id": "", "brief": "b", "dir": "d"}', "'id'"),
        ('{"id": "../escape", "brief": "b", "dir": "d"}', "slug"),
        ('{"id": "a", "brief": "b", "dir": "d", "payload": "x"}', "unknown keys"),
        ("not json", "not valid JSON"),
        ('["a"]', "JSON object"),
    ],
)
def test_a_malformed_task_file_is_refused(tmp_path, line, match):
    path = tmp_path / "tasks.jsonl"
    path.write_text(line + "\n", encoding="utf-8")

    with pytest.raises(fleet.FleetError, match=match):
        fleet.load_tasks(path)


def test_duplicate_task_ids_are_refused(tmp_path):
    path = tmp_path / "tasks.jsonl"
    path.write_text(
        json.dumps({"id": "a", "brief": "b", "dir": "d"}) + "\n"
        + json.dumps({"id": "a", "brief": "b", "dir": "e"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(fleet.FleetError, match="duplicate"):
        fleet.load_tasks(path)


# --- config ---


def test_a_fleet_without_a_deadline_is_refused():
    with pytest.raises(config.ConfigError, match="deadline"):
        config.parse(
            {
                "version": 1,
                "gates": [{"id": "t", "run": "true"}],
                "fleet": {"concurrency": 2},
            }
        )


@pytest.mark.parametrize(
    "overrides, match",
    [
        ({"join": "most"}, "fleet.join"),
        ({"join": "quorum:2"}, "fleet.join"),
        ({"on_exhausted": "explode"}, "on_exhausted"),
        ({"retries": -1}, "fleet.retries"),
        ({"concurrency": 0}, "fleet.concurrency"),
        ({"worker_fallbacks": "one"}, "worker_fallbacks"),
        ({"nonsense": 1}, "unknown keys under 'fleet'"),
    ],
)
def test_invalid_fleet_sections_raise(overrides, match):
    section = {"deadline": 60}
    section.update(overrides)
    with pytest.raises(config.ConfigError, match=match):
        config.parse(
            {"version": 1, "gates": [{"id": "t", "run": "true"}], "fleet": section}
        )


@pytest.mark.parametrize("join", ["all", "first_pass", "quorum:0.8", "quorum:1"])
def test_valid_joins_are_accepted(join):
    cfg = config.parse(
        {
            "version": 1,
            "gates": [{"id": "t", "run": "true"}],
            "fleet": {"deadline": 60, "join": join},
        }
    )
    assert cfg.fleet.join == join


# --- the counts, at scale ---


def test_a_fifty_task_fleet_reports_honest_counts(repo, monkeypatch, capsys):
    """The headline claim: hundreds queued, a bounded few at a time, and
    `{succeeded, failed, parked}` that add up."""
    tasks = []
    for n in range(50):
        # 40 fix themselves; 10 never will
        worker = "echo FIXED > work.txt" if n % 5 else "true"
        tasks.append(make_task(repo, f"task-{n:02d}", worker))
    write_fleet(repo, tasks, concurrency=4, retries=0)
    monkeypatch.chdir(repo)

    exit_code = cli.main(["fleet", "tasks.jsonl"])
    capsys.readouterr()

    result = manifest(repo)["result"]
    assert result["succeeded"] == 40
    assert result["succeeded"] + result["failed"] + result["parked"] == 50
    # join: all — 10 never converged, so the fleet honestly says no
    assert result["join_satisfied"] is False
    assert exit_code == cli.EXIT_GATE_FAILED
    # partial success is a first-class outcome: the 40 are not thrown away
    assert len(manifest(repo)["tasks"]) == 50


def test_concurrency_bounds_what_runs_at_once(repo, monkeypatch, capsys):
    """Queue depth is hundreds; concurrency is the blast radius."""
    tasks = [make_task(repo, f"t-{n}", "echo FIXED > work.txt") for n in range(6)]
    write_fleet(repo, tasks, concurrency=2)
    monkeypatch.chdir(repo)

    assert cli.main(["fleet", "tasks.jsonl"]) == cli.EXIT_OK
    capsys.readouterr()

    started = [
        e for e in _events(repo) if e["type"] == "task.started"
    ]
    assert len(started) == 6
    assert manifest(repo)["result"]["succeeded"] == 6


def _events(repo: Path) -> list[dict]:
    found = sorted((repo / fleet.FLEETS_DIRNAME).iterdir())[0]
    return [
        json.loads(line)
        for line in (found / fleet.EVENTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def test_a_deterministic_failure_parks_after_one_attempt(repo, monkeypatch, capsys):
    """Invariant 2, and the single rule that would have saved the incident's
    twenty wasted agents: the same failure twice is not transient."""
    tasks = [make_task(repo, "hopeless", "true")]
    write_fleet(repo, tasks, retries=3)
    monkeypatch.chdir(repo)

    cli.main(["fleet", "tasks.jsonl"])
    capsys.readouterr()

    task = manifest(repo)["tasks"][0]
    assert task["status"] == "parked"
    # retries: 3 was allowed, but a repeated failure shape stops it far short
    assert task["attempts"] <= 2, task
    parked = [e for e in _events(repo) if e["type"] == "task.parked"]
    assert parked and parked[0]["why"] in ("deterministic", "exhausted")


def test_a_task_whose_directory_is_missing_is_parked_not_crashed(
    repo, monkeypatch, capsys
):
    write_fleet(repo, [{"id": "ghost", "brief": "b.md", "dir": "nowhere"}])
    monkeypatch.chdir(repo)

    cli.main(["fleet", "tasks.jsonl"])
    capsys.readouterr()

    task = manifest(repo)["tasks"][0]
    assert task["status"] == "parked"
    assert "no such directory" in task["reason"]


def test_join_first_pass_is_satisfied_by_one_success(repo, monkeypatch, capsys):
    tasks = [
        make_task(repo, "good", "echo FIXED > work.txt"),
        make_task(repo, "bad", "true"),
    ]
    (repo / ".wringer.yaml").write_text(
        FLEET_CONFIG.format(concurrency=2, retries=0).rstrip()
        + "\n  join: first_pass\n",
        encoding="utf-8",
    )
    (repo / "tasks.jsonl").write_text(
        "\n".join(json.dumps(t) for t in tasks) + "\n", encoding="utf-8"
    )
    monkeypatch.chdir(repo)

    assert cli.main(["fleet", "tasks.jsonl"]) == cli.EXIT_OK
    capsys.readouterr()

    assert manifest(repo)["result"]["join_satisfied"] is True


def test_the_fleet_ledger_records_every_task(repo, monkeypatch, capsys):
    tasks = [make_task(repo, f"t-{n}", "echo FIXED > work.txt") for n in range(3)]
    write_fleet(repo, tasks)
    monkeypatch.chdir(repo)

    assert cli.main(["fleet", "tasks.jsonl"]) == cli.EXIT_OK
    capsys.readouterr()

    kinds = [e["type"] for e in _events(repo)]
    assert kinds[0] == "fleet.started"
    assert kinds[-1] == "fleet.finished"
    assert kinds.count("task.started") == 3
    assert kinds.count("task.finished") == 3


def test_json_reports_the_counts(repo, monkeypatch, capfd):
    tasks = [make_task(repo, "solo", "echo FIXED > work.txt")]
    write_fleet(repo, tasks)
    monkeypatch.chdir(repo)

    cli.main(["fleet", "tasks.jsonl", "--json"])

    payload = json.loads(capfd.readouterr().out)
    assert set(payload) == {
        "succeeded", "failed", "parked", "join_satisfied", "fleet_dir"
    }
    assert payload["succeeded"] == 1
    assert payload["join_satisfied"] is True


def test_a_repo_without_a_fleet_section_is_refused(repo, write_config, monkeypatch,
                                                   capsys):
    write_config(repo, 'version: 1\ngates:\n  - id: t\n    run: "true"\n')
    (repo / "tasks.jsonl").write_text(
        json.dumps({"id": "a", "brief": "b", "dir": "d"}) + "\n", encoding="utf-8"
    )
    monkeypatch.chdir(repo)

    assert cli.main(["fleet", "tasks.jsonl"]) == cli.EXIT_CONFIG

    assert "no 'fleet:' section" in capsys.readouterr().err


# --- worktree mode: the one git write Wringer makes, and it is metadata ---


def worktree_fleet(repo: Path, tasks: list[dict]) -> None:
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: noop
    run: "true"
fleet:
  concurrency: 2
  deadline: 300
  retries: 0
  worktree: true
""",
        encoding="utf-8",
    )
    (repo / "tasks.jsonl").write_text(
        "\n".join(json.dumps(t) for t in tasks) + "\n", encoding="utf-8"
    )


def test_worktree_mode_gives_each_task_its_own_checkout(repo, monkeypatch, capsys):
    """Parallel children cannot share one working tree. With worktree: true
    the fleet makes each task a detached checkout of HEAD."""
    import subprocess

    (repo / "work.txt").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".wringer/\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED work.txt"
run:
  worker: "echo FIXED > work.txt"
  max_iterations: 2
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.invalid", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", "commit", "-qm", "base"],
        cwd=repo, check=True,
    )
    tasks = [
        {"id": f"t-{n}", "brief": "work.txt", "dir": "."} for n in range(3)
    ]
    worktree_fleet(repo, tasks)
    monkeypatch.chdir(repo)

    assert cli.main(["fleet", "tasks.jsonl"]) == cli.EXIT_OK
    capsys.readouterr()

    result = manifest(repo)["result"]
    assert result["succeeded"] == 3
    # each task got its own tree, recorded on the ledger
    made = [e for e in _events(repo) if e["type"] == "task.worktree"]
    assert len(made) == 3
    # ...and the fleet tidied up after itself
    listed = subprocess.run(
        ["git", "worktree", "list"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "wringer/worktrees" not in listed, listed


def test_worktree_mode_never_writes_history(repo, monkeypatch, capsys):
    """`worktree add` is metadata. The law that Wringer never commits,
    branches or pushes is untouched — this test is the guard on it."""
    import subprocess

    (repo / "work.txt").write_text("FIXED\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".wringer/\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        """\
version: 1
gates:
  - id: test
    run: "grep -q FIXED work.txt"
run:
  worker: "true"
  max_iterations: 1
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.invalid", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", "commit", "-qm", "base"],
        cwd=repo, check=True,
    )
    before = subprocess.run(
        ["git", "log", "--oneline", "--all"], cwd=repo,
        capture_output=True, text=True,
    ).stdout
    worktree_fleet(repo, [{"id": "solo", "brief": "work.txt", "dir": "."}])
    monkeypatch.chdir(repo)

    cli.main(["fleet", "tasks.jsonl"])
    capsys.readouterr()

    after = subprocess.run(
        ["git", "log", "--oneline", "--all"], cwd=repo,
        capture_output=True, text=True,
    ).stdout
    assert before == after, "the fleet wrote git history"


def test_worktree_must_be_a_boolean():
    with pytest.raises(config.ConfigError, match="worktree"):
        config.parse(
            {
                "version": 1,
                "gates": [{"id": "t", "run": "true"}],
                "fleet": {"deadline": 60, "worktree": "yes"},
            }
        )

def test_the_fleets_child_budgets_reach_the_child(repo, monkeypatch):
    """Invariant 8: budgets NEST.

    `fleet.child.worker_timeout` and `fleet.child.wall_clock` were validated
    by the config parser and then silently discarded, so a child could
    outlive the fleet that spawned it. The fleet's own deadline is no
    substitute — it kills the supervisor, not the worker burning the budget.
    """
    from wringer import config, fleet

    parsed = config.parse({
        "version": 1,
        "gates": [{"id": "t", "run": "true"}],
        "fleet": {
            "deadline": 600,
            "child": {"max_iterations": 2, "worker_timeout": 7,
                      "wall_clock": 33},
        },
    })
    assert parsed.fleet is not None
    # carried, not dropped
    assert parsed.fleet.child_max_iterations == 2
    assert parsed.fleet.child_worker_timeout == 7
    assert parsed.fleet.child_wall_clock == 33

    # and handed to the child process
    spawned: list[list[str]] = []

    class FakeProc:
        pid = 4242
        returncode = 0

        def poll(self):
            return 0

    def fake_popen(argv, **kwargs):
        spawned.append(argv)
        return FakeProc()

    monkeypatch.setattr(fleet.subprocess, "Popen", fake_popen)
    bundle = fleet.Bundle.create(repo / fleet.FLEETS_DIRNAME)
    state = fleet.TaskState(task=fleet.Task(id="t1", brief="b.md", dir="."))
    fleet._spawn(repo, bundle, state, parsed.fleet)

    argv = spawned[0]

    def flag(name: str) -> str:
        assert name in argv, f"{name} never reached the child: {argv}"
        return argv[argv.index(name) + 1]

    assert flag("--max-iterations") == "2"
    assert flag("--worker-timeout") == "7"
    assert flag("--wall-clock") == "33"


def test_a_child_budget_overrides_the_repos_own(repo, monkeypatch, capsys):
    """The outer budget is the one that was reasoned about, so it wins."""
    from wringer import cli

    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        'version: 1\ngates:\n  - id: test\n    run: "grep -q FIXED calc.py"\n'
        'run:\n  worker: "sleep 30"\n  max_iterations: 2\n  worker_timeout: 300\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    # the repo says 300s; the flag says 1s, and the flag is the fleet's voice
    assert cli.main(["run", "--worker-timeout", "1"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    from wringer import loop as loop_mod

    written = sorted((repo / loop_mod.LOOPS_DIRNAME).iterdir())[0]
    events = [
        json.loads(line)
        for line in (written / loop_mod.EVENTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(e.get("timed_out") for e in events if e["type"] == "worker.finished")


# --- the shapes no test produced -------------------------------------------
#
# Publishing `wringer.fleet.v1` means a drift test validates real artifacts
# against the schema. Three event shapes had no fixture producing them, so a
# schema declaring them would have been checked against nothing — the suite's
# own standard: "the optional keys really were exercised, or this test proves
# less than it looks like it does" (tests/test_schema.py).

FALLBACK_CONFIG = """\
version: 1
gates:
  - id: noop
    run: "true"
fleet:
  concurrency: 1
  deadline: 300
  progress_window: 60
  retries: 2
  worker_fallbacks:
    - "sh -c 'printf FIXED > work.txt'"
"""

EXHAUSTED_FAIL_CONFIG = """\
version: 1
gates:
  - id: noop
    run: "true"
fleet:
  concurrency: 1
  deadline: 300
  progress_window: 60
  retries: 0
  on_exhausted: fail
"""


def test_a_retry_records_which_fallback_worker_it_used(repo, monkeypatch, capsys):
    """`fallback` appears on `task.started` only from attempt 2, and only
    when a `worker_fallbacks` rung exists for it."""
    task = make_task(repo, "t1", "sh -c 'exit 1'")
    (repo / ".wringer.yaml").write_text(FALLBACK_CONFIG, encoding="utf-8")
    (repo / "tasks.jsonl").write_text(json.dumps(task) + "\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    cli.main(["fleet", "tasks.jsonl"])
    capsys.readouterr()

    started = [e for e in _events(repo) if e["type"] == "task.started"]
    assert any("fallback" in e for e in started), started
    assert not any("fallback" in e for e in started if e["attempt"] == 1)


def test_on_exhausted_fail_records_the_third_task_finished_shape(
    repo, monkeypatch, capsys
):
    """`task.finished` has three disjoint key sets. This is the one no other
    test reaches: `{task, why: "exhausted"}` with no status, reason or loop."""
    task = make_task(repo, "t1", "sh -c 'exit 1'")
    (repo / ".wringer.yaml").write_text(EXHAUSTED_FAIL_CONFIG, encoding="utf-8")
    (repo / "tasks.jsonl").write_text(json.dumps(task) + "\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    cli.main(["fleet", "tasks.jsonl"])
    capsys.readouterr()

    finished = [e for e in _events(repo) if e["type"] == "task.finished"]
    exhausted = [e for e in finished if e.get("why") == "exhausted"]
    assert exhausted, finished
    assert "status" not in exhausted[0]
    assert "reason" not in exhausted[0]
