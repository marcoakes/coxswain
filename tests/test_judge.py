"""`wring judge` — the rubric judge, dry-run (SPEC_JUDGE_V0.md).

No test here opens a socket, and none needs an API key: the transport is a
single stdlib call behind one function, and faking it is the difference
between a suite that runs anywhere and one that needs an endpoint and a key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import flat

from wringer import cli, config, judge, loop, rubric

RUBRIC = """\
schema_version: wringer.rubric.v1
title: Acceptance criteria
criteria:
  - id: docstring-present
    title: Public functions carry a docstring
    guidance: Say what it does.
    required: true
  - id: no-scope-creep
    title: No unrelated changes
    required: false
"""

CONFIG = """\
version: 1
gates:
  - id: check
    run: "true"
judge:
  endpoint: http://127.0.0.1:11434/v1/chat/completions
  model: cheap-model
  rubric: rubric.yaml
"""


def reply(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def setup_repo(repo: Path, gate: str = '"true"') -> None:
    (repo / "rubric.yaml").write_text(RUBRIC, encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        CONFIG.replace('run: "true"', f"run: {gate}"), encoding="utf-8"
    )
    (repo / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )


def only_verdict(repo: Path) -> Path:
    found = sorted((repo / judge.VERDICTS_DIRNAME).iterdir())
    assert len(found) == 1, found
    return found[0]


def verdict_json(repo: Path) -> dict:
    return json.loads(
        (only_verdict(repo) / judge.VERDICT_FILENAME).read_text(encoding="utf-8")
    )


def test_a_dry_run_builds_a_request_and_sends_nothing(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["judge"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "nothing was sent" in out
    directory = only_verdict(repo)
    # the request exists on disk; the response does not, because none came
    assert (directory / judge.REQUEST_FILENAME).is_file()
    assert not (directory / judge.RESPONSE_FILENAME).exists()

    recorded = verdict_json(repo)
    assert recorded["schema_version"] == judge.SCHEMA_VERSION
    assert recorded["mode"] == "dry_run"
    # honest: a dry run judged nothing, so it claims nothing
    assert recorded["verdict"] is None
    assert recorded["criteria"] == []


def test_a_bundle_whose_gates_failed_is_refused(repo, monkeypatch, capsys):
    setup_repo(repo, gate='"false"')
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_GATE_FAILED
    capsys.readouterr()

    assert cli.main(["judge"]) == cli.EXIT_REFUSED

    err = flat(capsys.readouterr().err)
    assert "gates did not pass" in err
    # no request was built, so nothing could have been sent
    assert not (repo / judge.VERDICTS_DIRNAME).exists()


def fake_transport(monkeypatch, reply=None, fail=None):
    """Stand in for the one function that opens a socket.

    No test in this suite touches a network: the transport is a single
    stdlib call, and faking it is the difference between a suite that runs
    anywhere and one that needs an endpoint and a key.
    """
    sent = {}

    def fake_send(request, endpoint, timeout, api_key):
        sent.update(
            request=request, endpoint=endpoint, timeout=timeout, api_key=api_key
        )
        if fail is not None:
            raise judge.TransportFailed(fail)
        return reply

    monkeypatch.setattr(judge, "send", fake_send)
    return sent


def test_send_produces_a_verdict_from_the_reply(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    sent = fake_transport(
        monkeypatch,
        reply=reply(json.dumps({"criteria": [
            {"id": "docstring-present", "met": True, "reason": "present"},
            {"id": "no-scope-creep", "met": True, "reason": "tight"},
        ]})),
    )

    assert cli.main(["judge", "--send"]) == cli.EXIT_OK

    assert sent["endpoint"].endswith("/v1/chat/completions")
    recorded = verdict_json(repo)
    assert recorded["mode"] == "live"
    assert recorded["verdict"] == judge.PASS
    # the raw reply is kept beside the request, so both halves are auditable
    assert (only_verdict(repo) / judge.RESPONSE_FILENAME).is_file()


def test_a_failing_criterion_exits_one(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    fake_transport(
        monkeypatch,
        reply=reply(json.dumps({"criteria": [
            {"id": "docstring-present", "met": False, "reason": "none"},
            {"id": "no-scope-creep", "met": True, "reason": "tight"},
        ]})),
    )

    assert cli.main(["judge", "--send"]) == cli.EXIT_GATE_FAILED

    assert verdict_json(repo)["verdict"] == judge.FAIL


def test_an_unreachable_endpoint_is_needs_human_not_fail(repo, monkeypatch, capsys):
    """A transport failure is not a verdict. Exit 5, and the bundle says why."""
    setup_repo(repo)
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    fake_transport(monkeypatch, fail="connection refused")

    assert cli.main(["judge", "--send"]) == cli.EXIT_NEEDS_HUMAN

    recorded = verdict_json(repo)
    assert recorded["verdict"] == judge.NEEDS_HUMAN
    assert "connection refused" in recorded["note"]
    # nothing came back, so nothing is claimed to have
    assert not (only_verdict(repo) / judge.RESPONSE_FILENAME).exists()
    # ...but the request that would have been sent is still on disk
    assert (only_verdict(repo) / judge.REQUEST_FILENAME).is_file()


def test_the_api_key_is_passed_to_the_transport_but_not_written_down(
    repo, monkeypatch, capsys
):
    secret = "sk-hushhush12345"
    (repo / "rubric.yaml").write_text(RUBRIC, encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        CONFIG.rstrip() + "\n  api_key_env: JUDGE_KEY\n", encoding="utf-8"
    )
    monkeypatch.setenv("JUDGE_KEY", secret)
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    sent = fake_transport(
        monkeypatch,
        reply=reply(json.dumps({"criteria": [
            {"id": "docstring-present", "met": True, "reason": "ok"},
            {"id": "no-scope-creep", "met": True, "reason": "ok"},
        ]})),
    )

    assert cli.main(["judge", "--send"]) == cli.EXIT_OK

    # the transport gets the real key...
    assert sent["api_key"] == secret
    # ...and no artifact does
    for name in (judge.REQUEST_FILENAME, judge.VERDICT_FILENAME):
        assert secret not in (only_verdict(repo) / name).read_text(encoding="utf-8")


def test_a_repo_without_a_judge_section_cannot_reach_a_network(
    repo, write_config, monkeypatch, capsys
):
    write_config(repo, "version: 1\ngates:\n  - id: check\n    run: \"true\"\n")
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["judge"]) == cli.EXIT_CONFIG

    err = flat(capsys.readouterr().err)
    assert "no 'judge:' section" in err
    assert "never will be" in err


def test_print_request_writes_the_body_and_stops(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["judge", "--print-request"]) == cli.EXIT_OK

    body = json.loads(capsys.readouterr().out)
    assert body["model"] == "cheap-model"
    assert body["temperature"] == 0
    # --print-request is an inspection, so it leaves no judgment behind
    assert not (repo / judge.VERDICTS_DIRNAME).exists()


def test_no_worker_output_can_reach_the_judge(repo, monkeypatch, capsys):
    """THE isolation test. A worker shouts a sentinel; the judge must never
    see it, because it reads .wringer/runs/ and the worker's words live in
    .wringer/loops/."""
    sentinel = "XYZZY-SENTINEL-9c1e"
    (repo / "rubric.yaml").write_text(RUBRIC, encoding="utf-8")
    (repo / "calc.py").write_text("BROKEN\n", encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        f"""\
version: 1
gates:
  - id: check
    run: "grep -q FIXED calc.py"
run:
  worker: "echo {sentinel}; echo FIXED > calc.py"
judge:
  endpoint: http://127.0.0.1:11434/v1/chat/completions
  model: cheap-model
  rubric: rubric.yaml
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["run"]) == cli.EXIT_OK
    capsys.readouterr()
    # the sentinel really was captured somewhere, or this proves nothing
    worker_log = (
        sorted((repo / loop.LOOPS_DIRNAME).iterdir())[0]
        / loop.ITERATIONS_DIRNAME
        / "001"
        / "worker.stdout.log"
    )
    assert sentinel in worker_log.read_text(encoding="utf-8")

    assert cli.main(["judge"]) == cli.EXIT_OK

    request = (only_verdict(repo) / judge.REQUEST_FILENAME).read_text("utf-8")
    assert sentinel not in request


def test_the_packet_has_no_field_that_could_carry_a_worker(repo):
    """Isolation is a type signature, not a promise: there is nowhere in the
    closed list to put a loop, a brief, or a worker log."""
    fields = set(judge.Packet.__dataclass_fields__)
    assert fields == {
        "rubric_title",
        "criteria",
        "diff",
        "diff_truncated",
        "gates",
        "head_sha",
        "branch",
        "dirty",
    }
    for forbidden in ("worker", "brief", "loop", "iteration", "stdout"):
        assert not any(forbidden in name for name in fields)


# --- the reply parser: every misunderstanding is needs_human, never fail ---


def loaded_rubric(tmp_path: Path) -> rubric.Rubric:
    (tmp_path / "rubric.yaml").write_text(RUBRIC, encoding="utf-8")
    return rubric.load(Path("rubric.yaml"), tmp_path)


def test_a_clean_reply_passes(tmp_path):
    verdict = judge.parse_response(
        reply(json.dumps({"criteria": [
            {"id": "docstring-present", "met": True, "reason": "it has one"},
            {"id": "no-scope-creep", "met": True, "reason": "tight"},
        ]})),
        loaded_rubric(tmp_path),
    )
    assert verdict.verdict == judge.PASS


def test_an_unmet_required_criterion_fails(tmp_path):
    verdict = judge.parse_response(
        reply(json.dumps({"criteria": [
            {"id": "docstring-present", "met": False, "reason": "none"},
            {"id": "no-scope-creep", "met": True, "reason": "tight"},
        ]})),
        loaded_rubric(tmp_path),
    )
    assert verdict.verdict == judge.FAIL


def test_an_unmet_optional_criterion_does_not_fail(tmp_path):
    verdict = judge.parse_response(
        reply(json.dumps({"criteria": [
            {"id": "docstring-present", "met": True, "reason": "yes"},
            {"id": "no-scope-creep", "met": False, "reason": "sprawls"},
        ]})),
        loaded_rubric(tmp_path),
    )
    assert verdict.verdict == judge.PASS


@pytest.mark.parametrize(
    "body",
    [
        reply("not json at all"),
        reply(json.dumps({"wrong": "shape"})),
        {"choices": []},
        {},
        reply(json.dumps({"criteria": [
            {"id": "docstring-present", "met": True, "reason": "ok"},
        ]})),  # a criterion the model declined to score
    ],
)
def test_anything_unparseable_is_needs_human_never_fail(tmp_path, body):
    verdict = judge.parse_response(body, loaded_rubric(tmp_path))

    assert verdict.verdict == judge.NEEDS_HUMAN
    assert verdict.verdict != judge.FAIL


def test_a_fenced_reply_is_still_understood(tmp_path):
    fenced = "```json\n" + json.dumps({"criteria": [
        {"id": "docstring-present", "met": True, "reason": "yes"},
        {"id": "no-scope-creep", "met": True, "reason": "yes"},
    ]}) + "\n```"

    assert judge.parse_response(reply(fenced), loaded_rubric(tmp_path)).verdict == (
        judge.PASS
    )


# --- endpoint safety, at parse time ---


def judge_config(**overrides):
    section = {
        "endpoint": "https://api.example.com/v1/chat/completions",
        "model": "m",
        "rubric": "rubric.yaml",
    }
    section.update(overrides)
    return {
        "version": 1,
        "gates": [{"id": "t", "run": "true"}],
        "judge": section,
    }


@pytest.mark.parametrize(
    "endpoint, match",
    [
        ("http://api.example.com/v1", "loopback"),
        ("ftp://example.com/v1", "http:// or https://"),
        ("https://u:p@example.com/v1", "credentials"),
        ("https://example.com/v1?key=abc", "query string"),
        ("not-a-url", "http:// or https://"),
    ],
)
def test_unsafe_endpoints_are_rejected_at_parse_time(endpoint, match):
    with pytest.raises(config.ConfigError, match=match):
        config.parse(judge_config(endpoint=endpoint))


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:11434/v1/chat/completions",
        "http://localhost:11434/v1",
        "https://api.example.com/v1/chat/completions",
    ],
)
def test_safe_endpoints_are_accepted(endpoint):
    assert config.parse(judge_config(endpoint=endpoint)).judge.endpoint == endpoint


@pytest.mark.parametrize(
    "overrides, match",
    [
        ({"endpoint": ""}, "judge.endpoint"),
        ({"model": ""}, "judge.model"),
        ({"rubric": ""}, "judge.rubric"),
        ({"api_key_env": ""}, "api_key_env"),
        ({"timeout": 0}, "judge.timeout"),
        ({"max_output_tokens": -1}, "judge.max_output_tokens"),
        ({"nonsense": 1}, "unknown keys under 'judge'"),
    ],
)
def test_invalid_judge_sections_raise(overrides, match):
    with pytest.raises(config.ConfigError, match=match):
        config.parse(judge_config(**overrides))


def test_a_config_without_judge_is_still_valid():
    assert config.parse(
        {"version": 1, "gates": [{"id": "t", "run": "true"}]}
    ).judge is None


def test_an_unset_api_key_env_is_caught_before_anything_is_built(
    repo, monkeypatch, capsys
):
    (repo / "rubric.yaml").write_text(RUBRIC, encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        CONFIG.rstrip() + "\n  api_key_env: NOT_SET_ANYWHERE\n", encoding="utf-8"
    )
    monkeypatch.delenv("NOT_SET_ANYWHERE", raising=False)
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["judge"]) == cli.EXIT_CONFIG

    assert "NOT_SET_ANYWHERE" in capsys.readouterr().err
    assert not (repo / judge.VERDICTS_DIRNAME).exists()


def test_the_api_key_value_is_redacted_out_of_the_request(repo, monkeypatch, capsys):
    """`api_key_env` names a variable whose value folds into the redactor, so
    a credential cannot reach an artifact even if something echoes it."""
    secret = "sk-hushhush12345"
    (repo / "rubric.yaml").write_text(RUBRIC, encoding="utf-8")
    (repo / ".wringer.yaml").write_text(
        CONFIG.replace('run: "true"', f'run: "echo {secret}"').rstrip()
        + "\n  api_key_env: JUDGE_KEY\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JUDGE_KEY", secret)
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["judge"]) == cli.EXIT_OK

    request = (only_verdict(repo) / judge.REQUEST_FILENAME).read_text("utf-8")
    assert secret not in request


def test_verify_and_run_can_never_return_needs_human(repo, monkeypatch, capsys):
    """5 belongs to `wring judge` alone."""
    setup_repo(repo, gate='"false"')
    (repo / ".wringer.yaml").write_text(
        (repo / ".wringer.yaml").read_text(encoding="utf-8")
        + 'run:\n  worker: "true"\n  max_iterations: 1\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["verify"]) != cli.EXIT_NEEDS_HUMAN
    assert cli.main(["run"]) != cli.EXIT_NEEDS_HUMAN
    capsys.readouterr()


# --- criteria only a human can score (SPEC_INTENT_V0.md §1, defence 3) ---
#
# `human: true` is a wringer.rubric.v1 amendment made for `wring spec`, but it
# has to mean something here or it is decoration. A criterion nobody could
# check is exactly the "rubric full of vibes" the spec warns about, and a
# model asked to score one would be guessing with a straight face.

HUMAN_RUBRIC = """\
schema_version: wringer.rubric.v1
title: Acceptance criteria
criteria:
  - id: docstring-present
    title: Public functions carry a docstring
    required: true
    human: false
  - id: reads-well
    title: The copy reads the way our users speak
    required: true
    human: true
"""


def test_a_human_criterion_is_never_in_the_request(repo, monkeypatch, capsys):
    setup_repo(repo)
    (repo / "rubric.yaml").write_text(HUMAN_RUBRIC, encoding="utf-8")
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["judge", "--print-request"]) == cli.EXIT_OK

    body = json.loads(capsys.readouterr().out)["messages"][1]["content"]
    assert "docstring-present" in body
    # not in the criteria list, and not in the set of ids it may answer with
    assert "reads-well" not in body


def test_a_human_criterion_comes_back_unscored_and_needs_a_human(
    repo, monkeypatch, capsys
):
    setup_repo(repo)
    (repo / "rubric.yaml").write_text(HUMAN_RUBRIC, encoding="utf-8")
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    fake_transport(
        monkeypatch,
        reply=reply(json.dumps({"criteria": [
            {"id": "docstring-present", "met": True, "reason": "present"},
            # the model volunteers a score for the one it was never asked about
            {"id": "reads-well", "met": True, "reason": "sounds fine to me"},
        ]})),
    )

    assert cli.main(["judge", "--send"]) == cli.EXIT_NEEDS_HUMAN

    recorded = verdict_json(repo)
    assert recorded["verdict"] == judge.NEEDS_HUMAN
    rows = {row["id"]: row for row in recorded["criteria"]}
    assert rows["docstring-present"]["met"] is True
    # the volunteered answer is not read: there was no question to answer
    assert rows["reads-well"]["met"] is None
    assert "needs a human" in rows["reads-well"]["reason"]
    assert "sounds fine to me" not in json.dumps(recorded)


def test_a_failing_machine_criterion_still_fails_outright(repo, monkeypatch,
                                                          capsys):
    """A definite no outranks a pending look: the change is rejected either
    way, and 'fail' is the more actionable of the two."""
    setup_repo(repo)
    (repo / "rubric.yaml").write_text(HUMAN_RUBRIC, encoding="utf-8")
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    fake_transport(
        monkeypatch,
        reply=reply(json.dumps({"criteria": [
            {"id": "docstring-present", "met": False, "reason": "none"},
        ]})),
    )

    assert cli.main(["judge", "--send"]) == cli.EXIT_GATE_FAILED

    assert verdict_json(repo)["verdict"] == judge.FAIL


def test_an_optional_human_criterion_does_not_block_a_pass(repo, monkeypatch,
                                                            capsys):
    setup_repo(repo)
    (repo / "rubric.yaml").write_text(
        HUMAN_RUBRIC.replace(
            "    required: true\n    human: true", "    required: false\n"
            "    human: true"
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    fake_transport(
        monkeypatch,
        reply=reply(json.dumps({"criteria": [
            {"id": "docstring-present", "met": True, "reason": "present"},
        ]})),
    )

    assert cli.main(["judge", "--send"]) == cli.EXIT_OK

    assert verdict_json(repo)["verdict"] == judge.PASS


def test_an_all_human_rubric_opens_no_socket(repo, monkeypatch, capsys):
    """--send is permission to ask, not an instruction to. With nothing to
    ask, there is no request to make."""
    setup_repo(repo)
    (repo / "rubric.yaml").write_text(
        HUMAN_RUBRIC.replace("    human: false", "    human: true"),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    sent = fake_transport(monkeypatch, reply=reply("{}"))

    assert cli.main(["judge", "--send"]) == cli.EXIT_NEEDS_HUMAN

    assert sent == {}, "a socket was opened to ask nothing"
    recorded = verdict_json(repo)
    assert recorded["verdict"] == judge.NEEDS_HUMAN
    assert "nothing was sent" in recorded["note"]
    assert not (only_verdict(repo) / judge.RESPONSE_FILENAME).exists()


def test_human_defaults_to_false_so_existing_rubrics_are_unchanged(tmp_path):
    loaded = loaded_rubric(tmp_path)

    assert [c.human for c in loaded.criteria] == [False, False]
    assert loaded.machine_criteria == loaded.criteria


def test_human_must_be_a_boolean(tmp_path):
    (tmp_path / "rubric.yaml").write_text(
        RUBRIC.replace(
            "    required: false\n", "    required: false\n    human: yes please\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(rubric.RubricError, match="'human' must be a boolean"):
        rubric.load(Path("rubric.yaml"), tmp_path)


def test_a_live_judgment_that_scored_nothing_is_not_called_a_dry_run(
    repo, monkeypatch, capsys
):
    """summary.md is an evidence artifact. An unreachable endpoint leaves a
    verdict with no scored criteria, and the old wording called that a dry
    run — on a run that really did open a socket."""
    setup_repo(repo)
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()
    fake_transport(monkeypatch, fail="connection refused")

    assert cli.main(["judge", "--send"]) == cli.EXIT_NEEDS_HUMAN
    capsys.readouterr()

    written = (only_verdict(repo) / judge.SUMMARY_FILENAME).read_text("utf-8")
    assert "mode: **live**" in written
    assert "this was a dry run" not in written
    assert "not** a dry run" in written
    assert "connection refused" in written


def test_a_real_dry_run_still_says_so(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    assert cli.main(["verify"]) == cli.EXIT_OK
    capsys.readouterr()

    assert cli.main(["judge"]) == cli.EXIT_OK
    capsys.readouterr()

    written = (only_verdict(repo) / judge.SUMMARY_FILENAME).read_text("utf-8")
    assert "this was a dry run" in written
