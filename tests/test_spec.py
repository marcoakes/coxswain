"""`wring spec` — prose in, a spec file a human approves (SPEC_INTENT_V0.md).

No test here opens a socket. Drafting reuses `judge.send`, the one function
in Wringer that does, so faking that one function is enough to exercise the
whole command — which is also the point of routing it through the judge's
transport rather than adding a second one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from conftest import flat

from wringer import cli, spec

PRD = """\
# CSV export

Our reports page needs a CSV export. People keep asking for it because they
want to pivot the numbers in a spreadsheet.

It should cover the same rows the page is showing, respecting whatever filter
is applied.
"""

CONFIG = """\
version: 1
gates:
  - id: check
    run: "true"
judge:
  endpoint: http://127.0.0.1:11434/v1/chat/completions
  model: cheap-model
  rubric: wringer.rubric.yaml
"""

DRAFT = {
    "title": "Add CSV export to the reports page",
    "open_questions": [
        {
            "id": "date-format",
            "question": "Which date format should the export use?",
            "required": True,
        },
        {
            "id": "row-cap",
            "question": "Is there a maximum row count?",
            "required": False,
        },
    ],
    "criteria": [
        {
            "id": "export-button-exists",
            "title": "A CSV export button appears on the reports page",
            "guidance": "A test asserts the button renders.",
            "required": True,
            "human": False,
        },
        {
            "id": "respects-filters",
            "title": "The export contains exactly the filtered rows",
            "required": True,
            "human": False,
        },
        {
            "id": "reads-well",
            "title": "The column headings read the way a finance team expects",
            "required": True,
            "human": True,
        },
    ],
    "gates": [{"id": "test", "run": "pytest -q"}],
    "tasks": [
        {
            "id": "csv-export",
            "brief": "briefs/csv-export.md",
            "dir": ".",
            "objective": "Add the export endpoint and the button that calls it.",
        }
    ],
}


def reply(payload: object) -> dict:
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return {"choices": [{"message": {"content": body}}]}


def setup_repo(repo: Path, prd: str = PRD, config_text: str = CONFIG) -> None:
    (repo / "PRD.md").write_text(prd, encoding="utf-8")
    (repo / ".wringer.yaml").write_text(config_text, encoding="utf-8")


def fake_transport(monkeypatch, reply=None, fail=None):
    """Stand in for the one function in Wringer that opens a socket."""
    from wringer import judge

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


def only_draft(repo: Path) -> Path:
    found = sorted((repo / spec.SPECS_DIRNAME).iterdir())
    assert len(found) == 1, found
    return found[0]


def drafted(repo: Path) -> dict:
    return yaml.safe_load((repo / spec.SPEC_FILENAME).read_text(encoding="utf-8"))


# --- the dry run: the default, and it drafts nothing ---------------------


def test_a_dry_run_writes_the_request_and_drafts_nothing(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)

    assert cli.main(["spec", "PRD.md"]) == cli.EXIT_OK

    out = capsys.readouterr().out
    assert "nothing was sent" in out
    directory = only_draft(repo)
    assert (directory / spec.REQUEST_FILENAME).is_file()
    assert not (directory / spec.RESPONSE_FILENAME).exists()
    # a dry run drafts nothing: there is no spec file to approve by accident
    assert not (repo / spec.SPEC_FILENAME).exists()


def test_a_dry_run_needs_no_api_key(repo, monkeypatch, capsys):
    """The credential is for the socket, and a dry run does not open one."""
    setup_repo(repo, config_text=CONFIG.rstrip() + "\n  api_key_env: DRAFT_KEY\n")
    monkeypatch.delenv("DRAFT_KEY", raising=False)
    monkeypatch.chdir(repo)

    assert cli.main(["spec", "PRD.md"]) == cli.EXIT_OK

    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_CONFIG
    assert "DRAFT_KEY" in capsys.readouterr().err


def test_print_request_writes_the_body_and_stops(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)

    assert cli.main(["spec", "PRD.md", "--print-request"]) == cli.EXIT_OK

    body = json.loads(capsys.readouterr().out)
    assert body["model"] == "cheap-model"
    assert body["temperature"] == 0
    # the PRD really is what travels
    assert "pivot the numbers in a spreadsheet" in body["messages"][1]["content"]
    # an inspection leaves nothing behind
    assert not (repo / spec.SPECS_DIRNAME).exists()


def test_a_repo_without_a_judge_section_cannot_reach_a_network(
    repo, write_config, monkeypatch, capsys
):
    (repo / "PRD.md").write_text(PRD, encoding="utf-8")
    write_config(repo, 'version: 1\ngates:\n  - id: check\n    run: "true"\n')
    monkeypatch.chdir(repo)

    assert cli.main(["spec", "PRD.md"]) == cli.EXIT_CONFIG

    assert "no 'judge:' section" in capsys.readouterr().err


# --- --send, against the fake transport ----------------------------------


def test_send_drafts_a_valid_spec_from_a_real_prd(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    sent = fake_transport(monkeypatch, reply=reply(DRAFT))

    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_OK

    assert sent["endpoint"].endswith("/v1/chat/completions")
    document = drafted(repo)
    assert document["schema_version"] == spec.SCHEMA_VERSION
    assert document["title"] == DRAFT["title"]
    assert len(document["criteria"]) == 3
    assert len(document["tasks"]) == 1
    # and it loads back through the real parser
    loaded = spec.load(repo / spec.SPEC_FILENAME)
    assert loaded.title == DRAFT["title"]
    assert [q.id for q in loaded.unanswered] == ["date-format"]
    # both halves of the exchange are on disk
    assert (only_draft(repo) / spec.REQUEST_FILENAME).is_file()
    assert (only_draft(repo) / spec.RESPONSE_FILENAME).is_file()


def test_a_drafted_spec_always_arrives_unapproved(repo, monkeypatch, capsys):
    """The interlock. No reply may set it, however hard it tries."""
    setup_repo(repo)
    monkeypatch.chdir(repo)
    insistent = dict(DRAFT, approved=True)
    fake_transport(monkeypatch, reply=reply(insistent))

    # a reply carrying a key the request never asked for is refused outright
    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_CONFIG
    assert "did not ask for" in capsys.readouterr().err
    assert not (repo / spec.SPEC_FILENAME).exists()

    fake_transport(monkeypatch, reply=reply(DRAFT))
    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_OK
    capsys.readouterr()

    assert drafted(repo)["approved"] is False
    assert spec.load(repo / spec.SPEC_FILENAME).approved is False


def test_the_intent_is_the_humans_words_not_the_models(repo, monkeypatch, capsys):
    """A model paraphrasing the PRD inside the artifact the human approves is
    the confident-wrong-answer in miniature."""
    setup_repo(repo)
    monkeypatch.chdir(repo)
    fake_transport(
        monkeypatch,
        reply=reply(dict(DRAFT, intent="They want a button. Probably red.")),
    )

    # the paraphrase is refused as an unrequested key...
    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_CONFIG
    capsys.readouterr()

    # ...and what does get written is quoted from the file
    fake_transport(monkeypatch, reply=reply(DRAFT))
    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_OK
    capsys.readouterr()
    assert "pivot the numbers in a spreadsheet" in drafted(repo)["intent"]
    assert "Probably red" not in (repo / spec.SPEC_FILENAME).read_text("utf-8")


@pytest.mark.parametrize(
    "body, expected",
    [
        (reply("not json at all"), "not the JSON object"),
        (reply("[1, 2, 3]"), "not an object"),
        ({"choices": []}, "no message content"),
        ({}, "no message content"),
        (reply(dict(DRAFT, criteria=[])), "non-empty list"),
        (reply(dict(DRAFT, tasks=[])), "non-empty list"),
        (reply(dict(DRAFT, gates=[{"id": "../etc", "run": "x"}])), "letter or digit"),
        (
            reply(dict(DRAFT, tasks=[dict(DRAFT["tasks"][0], brief="../../out.md")])),
            "escape the repository",
        ),
        (
            reply(dict(DRAFT, tasks=[dict(DRAFT["tasks"][0], brief="/etc/passwd")])),
            "relative to the repository",
        ),
        (
            reply(dict(DRAFT, criteria=[dict(c, required=False)
                                        for c in DRAFT["criteria"]])),
            "at least one criterion must be required",
        ),
    ],
)
def test_a_malformed_reply_is_refused_and_writes_no_spec(
    repo, monkeypatch, capsys, body, expected
):
    """Never a half-written spec file: a half-written one gets approved."""
    setup_repo(repo)
    monkeypatch.chdir(repo)
    fake_transport(monkeypatch, reply=body)

    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_CONFIG

    assert expected in capsys.readouterr().err
    assert not (repo / spec.SPEC_FILENAME).exists()


def test_an_unreachable_endpoint_writes_no_spec(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    fake_transport(monkeypatch, fail="connection refused")

    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_CONFIG

    assert "connection refused" in capsys.readouterr().err
    assert not (repo / spec.SPEC_FILENAME).exists()
    # ...but the request that would have been sent is still auditable
    assert (only_draft(repo) / spec.REQUEST_FILENAME).is_file()


def test_an_existing_spec_is_never_overwritten(repo, monkeypatch, capsys):
    """It may already carry an approval and a page of answers."""
    setup_repo(repo)
    monkeypatch.chdir(repo)
    fake_transport(monkeypatch, reply=reply(DRAFT))
    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_OK
    capsys.readouterr()

    approved = (repo / spec.SPEC_FILENAME).read_text("utf-8").replace(
        "approved: false", "approved: true"
    )
    (repo / spec.SPEC_FILENAME).write_text(approved, encoding="utf-8")

    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_CONFIG

    assert "refusing to overwrite" in capsys.readouterr().err
    assert "approved: true" in (repo / spec.SPEC_FILENAME).read_text("utf-8")


def test_the_api_key_reaches_the_transport_but_no_artifact(
    repo, monkeypatch, capsys
):
    secret = "sk-draftdraft98765"
    setup_repo(repo, config_text=CONFIG.rstrip() + "\n  api_key_env: DRAFT_KEY\n")
    monkeypatch.setenv("DRAFT_KEY", secret)
    monkeypatch.chdir(repo)
    sent = fake_transport(monkeypatch, reply=reply(DRAFT))

    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_OK
    capsys.readouterr()

    assert sent["api_key"] == secret
    for name in (spec.REQUEST_FILENAME, spec.RESPONSE_FILENAME,
                 spec.SUMMARY_FILENAME):
        assert secret not in (only_draft(repo) / name).read_text(encoding="utf-8")


def test_json_output_is_one_object(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    fake_transport(monkeypatch, reply=reply(DRAFT))

    assert cli.main(["spec", "PRD.md", "--send", "--json"]) == cli.EXIT_OK

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "mode": "live",
        "spec": spec.SPEC_FILENAME,
        "approved": False,
        "criteria": 3,
        "gates": 1,
        "tasks": 1,
        "open_questions": 2,
        "spec_dir": payload["spec_dir"],
    }
    assert payload["spec_dir"].startswith(".wringer/specs/")


# --- the PRD itself ------------------------------------------------------


def test_a_prd_outside_the_repo_is_refused(repo, tmp_path_factory, monkeypatch,
                                           capsys):
    outside = tmp_path_factory.mktemp("elsewhere") / "secrets.md"
    outside.write_text("nothing to see", encoding="utf-8")
    setup_repo(repo)
    monkeypatch.chdir(repo)

    assert cli.main(["spec", str(outside)]) == cli.EXIT_CONFIG

    assert "outside the repository" in capsys.readouterr().err


def test_an_oversized_prd_is_refused(repo, monkeypatch, capsys):
    setup_repo(repo, prd="x" * (spec.MAX_PRD_BYTES + 1))
    monkeypatch.chdir(repo)

    assert cli.main(["spec", "PRD.md"]) == cli.EXIT_CONFIG

    assert "these bytes travel" in flat(capsys.readouterr().err)


def test_an_empty_prd_is_refused(repo, monkeypatch, capsys):
    setup_repo(repo, prd="   \n\n")
    monkeypatch.chdir(repo)

    assert cli.main(["spec", "PRD.md"]) == cli.EXIT_CONFIG

    assert "nothing to draft from" in capsys.readouterr().err


def test_a_missing_prd_is_refused(repo, monkeypatch, capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)

    assert cli.main(["spec", "nope.md"]) == cli.EXIT_CONFIG

    assert "no PRD at" in capsys.readouterr().err


# --- the rendered file ---------------------------------------------------


def test_the_rendered_file_survives_awkward_prose(repo, monkeypatch, capsys):
    """A paragraph objective, a colon in a title, an indented PRD line: all of
    them are YAML hazards, and all of them must still load."""
    awkward = dict(
        DRAFT,
        title="Export: rows, filtered",
        criteria=[
            dict(DRAFT["criteria"][0], title="It exports: everything shown"),
            DRAFT["criteria"][2],
        ],
        tasks=[
            dict(
                DRAFT["tasks"][0],
                objective="First, add the endpoint.\n\nThen wire up the button.",
            )
        ],
    )
    setup_repo(repo, prd="    indented first line\n\nnormal: line\n\ttab\n")
    monkeypatch.chdir(repo)
    fake_transport(monkeypatch, reply=reply(awkward))

    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_OK
    capsys.readouterr()

    loaded = spec.load(repo / spec.SPEC_FILENAME)
    assert loaded.title == "Export: rows, filtered"
    assert loaded.tasks[0].objective.endswith("Then wire up the button.")
    assert "indented first line" in loaded.intent


def test_the_file_says_out_loud_that_it_is_the_interlock(repo, monkeypatch,
                                                         capsys):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    fake_transport(monkeypatch, reply=reply(DRAFT))
    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_OK
    capsys.readouterr()

    text = (repo / spec.SPEC_FILENAME).read_text(encoding="utf-8")
    assert "approved: false" in text
    assert "no --yes" in text
    # the human's next move is written down beside the switch
    assert "refuses while this is false" in text


# --- the module's own edges ----------------------------------------------


def test_a_long_prd_is_quoted_and_says_so():
    quoted = spec.quote_intent("y" * (spec.MAX_INTENT_CHARS + 500))
    assert quoted.startswith("y" * 100)
    assert "read the file itself for the rest" in quoted


def test_control_characters_never_reach_the_spec_file():
    assert "\x00" not in spec.quote_intent("before\x00after")
    assert spec.quote_intent("keep\ttabs\nand newlines") == "keep\ttabs\nand newlines"


def test_a_spec_without_approved_is_not_approved_by_omission():
    document = dict(
        schema_version=spec.SCHEMA_VERSION,
        title="t",
        intent="i",
        criteria=DRAFT["criteria"],
        tasks=DRAFT["tasks"],
    )
    with pytest.raises(spec.SpecError, match="approved by omission"):
        spec.parse(document, "test")


def test_a_failed_live_draft_never_calls_itself_a_dry_run(repo, monkeypatch,
                                                          capsys):
    """The summary is an evidence artifact. A live run that produced nothing
    is not a dry run, and saying so would be the one unforgivable thing."""
    setup_repo(repo)
    monkeypatch.chdir(repo)
    fake_transport(monkeypatch, reply=reply("not json at all"))

    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_CONFIG
    capsys.readouterr()

    written = (only_draft(repo) / spec.SUMMARY_FILENAME).read_text("utf-8")
    assert "mode: **live**" in written
    assert "dry run" not in written
    assert "no spec file was written" in written


def test_an_unreachable_endpoint_summary_says_the_socket_was_opened(
    repo, monkeypatch, capsys
):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    fake_transport(monkeypatch, fail="connection refused")

    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_CONFIG
    capsys.readouterr()

    written = (only_draft(repo) / spec.SUMMARY_FILENAME).read_text("utf-8")
    assert "dry run" not in written


# --- what an adversarial review found (2026-08-01) -----------------------
#
# Each of these reproduced against the first cut of this slice. They are the
# cases where the code was confidently wrong, which is the failure mode the
# whole slice is about, so they get named tests rather than a tidy-up.


def test_the_wire_never_carries_what_the_request_file_redacts(
    repo, monkeypatch, capsys
):
    """THE audit test. Scrubbing only the artifact would leave request.json
    saying [REDACTED] beside a socket that carried the real value — a record
    that denies what happened, which is worse than no record."""
    secret = "sk-live-AAAABBBBCCCC1234"
    setup_repo(
        repo,
        prd=f"Use the staging key {secret} when testing the export.",
        config_text=CONFIG.rstrip() + "\n  api_key_env: DRAFT_KEY\n",
    )
    monkeypatch.setenv("DRAFT_KEY", secret)
    monkeypatch.chdir(repo)
    sent = fake_transport(monkeypatch, reply=reply(DRAFT))

    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_OK
    capsys.readouterr()

    on_wire = json.dumps(sent["request"])
    on_disk = (only_draft(repo) / spec.REQUEST_FILENAME).read_text("utf-8")
    # the artifact and the socket agree, because both came from one scrubbed
    # string — and neither carries the credential
    assert secret not in on_wire
    assert secret not in on_disk
    assert "[REDACTED]" in on_wire and "[REDACTED]" in on_disk
    # nor does the spec file the human is about to commit
    assert secret not in (repo / spec.SPEC_FILENAME).read_text("utf-8")


def test_print_request_is_scrubbed_too(repo, monkeypatch, capsys):
    secret = "sk-live-DDDDEEEEFFFF5678"
    setup_repo(
        repo,
        prd=f"The key is {secret}.",
        config_text=CONFIG.rstrip() + "\n  api_key_env: DRAFT_KEY\n",
    )
    monkeypatch.setenv("DRAFT_KEY", secret)
    monkeypatch.chdir(repo)

    assert cli.main(["spec", "PRD.md", "--print-request"]) == cli.EXIT_OK

    assert secret not in capsys.readouterr().out


def test_a_reply_that_answers_its_own_question_is_refused(
    repo, monkeypatch, capsys
):
    """The second interlock. An `answer` the drafter wrote is the assumption
    it was told to ask about, wearing a human's clothes — `wring plan` would
    wave it through and the brief would call it a decision someone made."""
    setup_repo(repo)
    monkeypatch.chdir(repo)
    presumptuous = dict(
        DRAFT,
        open_questions=[
            dict(DRAFT["open_questions"][0], answer="I'll assume ISO-8601."),
            DRAFT["open_questions"][1],
        ],
    )
    fake_transport(monkeypatch, reply=reply(presumptuous))

    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_CONFIG

    err = flat(capsys.readouterr().err)
    assert "answered its own open question" in err
    assert "date-format" in err
    assert not (repo / spec.SPEC_FILENAME).exists()


@pytest.mark.parametrize(
    "path",
    [".git/refs/heads/main", ".git/config", "tasks.jsonl",
     "wringer.rubric.yaml", "wringer.spec.yaml", ".wringer.yaml"],
)
def test_a_write_path_that_would_destroy_something_is_refused(repo, path):
    with pytest.raises(spec.SpecError):
        spec.check_writable(repo, path, "brief")


def test_a_control_character_in_a_path_is_refused_not_crashed(repo):
    """A NUL reaches the OS layer and raises ValueError out of stat(). A
    refusal is the answer; a traceback is not."""
    with pytest.raises(spec.SpecError, match="control character"):
        spec.check_writable(repo, "briefs/a\x00.md", "brief")


def test_every_scalar_the_file_can_hold_reads_back_exactly(repo):
    """`_scalar` used to `.strip()` the emitter's document marker, which also
    ate leading and trailing Unicode whitespace from the value — so a title
    ending in a non-breaking space was quietly written down as a different
    title. And only '\\n' forced quoting, though YAML breaks lines on
    U+2028, U+2029 and U+0085 too."""
    awkward = [
        "title\xa0", "\xa0lead", "tail　", "a b", "c d",
        "e\x85f", "cr\rhere", "multi\nline", "a: b", "yes", "null", "123",
        "  padded  ", "#hash", "- dash", 'q"and\'both', "back\\slash",
        "emoji \U0001f3af", "",
    ]
    for value in awkward:
        rendered = spec._scalar(value)
        assert "\n" not in rendered, f"{value!r} rendered across lines"
        assert yaml.safe_load(f"k: {rendered}")["k"] == value, value


def test_the_dry_run_key_check_opens_no_socket(repo, monkeypatch, capsys):
    """The --send half must be refused BEFORE the transport, not by the
    transport happening to fail. Any call here is the bug."""
    setup_repo(repo, config_text=CONFIG.rstrip() + "\n  api_key_env: DRAFT_KEY\n")
    monkeypatch.delenv("DRAFT_KEY", raising=False)
    monkeypatch.chdir(repo)

    from wringer import judge

    def forbidden(*args, **kwargs):
        raise AssertionError("a socket was opened without the declared key")

    monkeypatch.setattr(judge, "send", forbidden)

    assert cli.main(["spec", "PRD.md"]) == cli.EXIT_OK
    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_CONFIG
    assert "DRAFT_KEY" in capsys.readouterr().err


def test_the_drafter_is_shown_the_gates_the_repo_already_declares(
    repo, monkeypatch, capsys
):
    """A drafter shown nothing invents. Law 5 is why proposals are a diff a
    human applies; this is how to need that safety net less often."""
    setup_repo(repo)
    monkeypatch.chdir(repo)

    assert cli.main(["spec", "PRD.md", "--print-request"]) == cli.EXIT_OK

    body = json.loads(capsys.readouterr().out)["messages"][1]["content"]
    assert "already declares" in body
    assert "check: true" in body


def test_criteria_too_large_to_be_a_rubric_are_refused_at_draft_time(
    repo, monkeypatch, capsys
):
    """Not left for `wring plan`: a spec that reads fine, gets approved, and
    only then turns out to be unplannable spends the reading for nothing."""
    setup_repo(repo)
    monkeypatch.chdir(repo)
    bloated = dict(DRAFT, criteria=[
        {"id": f"c{n}", "title": "T", "guidance": "g" * 2000,
         "required": True, "human": False}
        for n in range(20)
    ])
    fake_transport(monkeypatch, reply=reply(bloated))

    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_CONFIG

    assert "these bytes travel" in flat(capsys.readouterr().err)
    assert not (repo / spec.SPEC_FILENAME).exists()


@pytest.mark.parametrize(
    "over, expected",
    [
        ({"tasks": [{"id": f"t{n}", "brief": f"briefs/{n}.md", "dir": ".",
                     "objective": "o"} for n in range(spec.MAX_TASKS + 1)]},
         "over the limit"),
        ({"open_questions": [{"id": f"q{n}", "question": "?", "required": False}
                             for n in range(spec.MAX_OPEN_QUESTIONS + 1)]},
         "over the limit"),
    ],
)
def test_the_model_controlled_ceilings_hold(repo, monkeypatch, capsys, over,
                                            expected):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    fake_transport(monkeypatch, reply=reply(dict(DRAFT, **over)))

    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_CONFIG

    assert expected in capsys.readouterr().err
    assert not (repo / spec.SPEC_FILENAME).exists()


@pytest.mark.parametrize(
    "duplicated",
    [
        {"tasks": [dict(DRAFT["tasks"][0]),
                   dict(DRAFT["tasks"][0], brief="briefs/other.md")]},
        {"open_questions": [DRAFT["open_questions"][0],
                            dict(DRAFT["open_questions"][0], question="again?")]},
        {"gates": [{"id": "test", "run": "a"}, {"id": "test", "run": "b"}]},
    ],
)
def test_duplicate_ids_are_refused(repo, monkeypatch, capsys, duplicated):
    setup_repo(repo)
    monkeypatch.chdir(repo)
    fake_transport(monkeypatch, reply=reply(dict(DRAFT, **duplicated)))

    assert cli.main(["spec", "PRD.md", "--send"]) == cli.EXIT_CONFIG

    assert "duplicate" in capsys.readouterr().err
    assert not (repo / spec.SPEC_FILENAME).exists()


def test_an_oversized_spec_file_is_refused_on_load(repo):
    (repo / spec.SPEC_FILENAME).write_text(
        "# " + "x" * (spec.MAX_SPEC_BYTES + 1), encoding="utf-8"
    )
    with pytest.raises(spec.SpecError, match="over the"):
        spec.load(repo / spec.SPEC_FILENAME)


@pytest.mark.parametrize("escape", ["../elsewhere", "/etc", "~/somewhere"])
def test_a_task_dir_that_leaves_the_repo_is_refused(repo, escape):
    with pytest.raises(spec.SpecError):
        spec.parse(
            {
                "schema_version": spec.SCHEMA_VERSION,
                "approved": True,
                "title": "t",
                "intent": "i",
                "criteria": DRAFT["criteria"],
                "tasks": [dict(DRAFT["tasks"][0], dir=escape)],
            },
            "test",
        )


def test_a_prd_carrying_the_agents_credential_is_scrubbed(
    repo, write_config, monkeypatch, capsys
):
    """`wring spec` scrubs the PRD on the way IN, so `request.json` and the
    wire carry the same text. It built that redactor from `judge.api_key_env`
    alone, so a credential named in `run.worker.acp.env_passthrough` — the one
    an agent is handed, and the one `wring start` writes — went through
    untouched.

    A PRD is a document a human pasted things into. That is exactly where a
    key ends up by accident.
    """
    secret = "notarealcredential-in-a-prd-4c81f0a6"
    monkeypatch.setenv("WRINGER_AGENT_CREDENTIAL", secret)
    write_config(
        repo,
        'version: 1\ngates:\n  - id: t\n    run: "true"\n'
        "run:\n  worker:\n    acp:\n      command: some-agent\n"
        "      env_passthrough: [WRINGER_AGENT_CREDENTIAL]\n"
        "judge:\n"
        "  endpoint: http://127.0.0.1:11434/v1/chat/completions\n"
        "  model: a-model\n"
        "  rubric: rubric.yaml\n",
    )
    (repo / "PRD.md").write_text(
        f"# Build it\n\nUse the key {secret} when you call the API.\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    assert cli.main(["spec", "PRD.md"]) == cli.EXIT_OK
    capsys.readouterr()

    hits = [
        path.relative_to(repo).as_posix()
        for path in (repo / ".wringer").rglob("*")
        if path.is_file()
        and secret in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert hits == [], f"the credential reached {hits}"
