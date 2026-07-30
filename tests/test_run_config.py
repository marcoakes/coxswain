"""The `run:` section — what `wring run` is allowed to be told."""

from __future__ import annotations

import pytest

from wringer import config


def parse(run=None, **extra):
    raw = {"version": 1, "gates": [{"id": "test", "run": "make test"}], **extra}
    if run is not None:
        raw["run"] = run
    return config.parse(raw)


def test_a_config_without_run_is_still_valid():
    """Verify-only repos never opted into the loop and must not be broken
    by its arrival."""
    assert parse().run is None


def test_a_minimal_run_section_takes_the_defaults():
    run = parse({"worker": "claude -p '{brief}'"}).run

    assert run.worker == "claude -p '{brief}'"
    assert run.max_iterations == config.DEFAULT_MAX_ITERATIONS
    assert run.worker_timeout == config.DEFAULT_WORKER_TIMEOUT_SECONDS


def test_every_field_can_be_set():
    run = parse(
        {"worker": "agent fix", "max_iterations": 7, "worker_timeout": 60}
    ).run

    assert (run.worker, run.max_iterations, run.worker_timeout) == (
        "agent fix",
        7,
        60,
    )


@pytest.mark.parametrize(
    "run, match",
    [
        ({}, "run.worker"),
        ({"worker": ""}, "run.worker"),
        ({"worker": "   "}, "run.worker"),
        ({"worker": 5}, "run.worker"),
        ({"worker": "a", "max_iterations": 0}, "run.max_iterations"),
        ({"worker": "a", "max_iterations": -1}, "run.max_iterations"),
        ({"worker": "a", "max_iterations": "lots"}, "run.max_iterations"),
        ({"worker": "a", "max_iterations": True}, "run.max_iterations"),
        ({"worker": "a", "worker_timeout": 0}, "run.worker_timeout"),
        ({"worker": "a", "worker_timeout": 1.5}, "run.worker_timeout"),
        ({"worker": "a", "retries": 2}, "unknown keys under 'run'"),
        ("claude -p", "'run' must be a mapping"),
    ],
)
def test_invalid_run_sections_raise(run, match):
    with pytest.raises(config.ConfigError, match=match):
        parse(run)


def test_an_unknown_placeholder_is_a_parse_error_naming_the_real_ones():
    with pytest.raises(config.ConfigError) as caught:
        parse({"worker": "agent --file {bref}"})

    message = str(caught.value)
    assert "{bref}" in message
    for known in config.WORKER_PLACEHOLDERS:
        assert "{" + known + "}" in message


def test_every_declared_placeholder_is_accepted():
    worker = "agent {brief} {evidence_dir} {iteration}"

    assert parse({"worker": worker}).run.worker == worker


def test_shell_variables_are_not_placeholders():
    """`${VAR}` belongs to the shell. Wringer must not read it as its own
    and must not reject it."""
    worker = 'claude -p "$(cat {brief})" --home ${HOME} --x $UNBRACED'

    assert parse({"worker": worker}).run.worker == worker


def test_substitute_fills_only_the_declared_names():
    filled = config.substitute(
        "agent {brief} {iteration} ${HOME} {evidence_dir}",
        brief="/tmp/b.md",
        iteration=2,
        evidence_dir=".wringer/runs/x",
    )

    assert filled == "agent /tmp/b.md 2 ${HOME} .wringer/runs/x"


def test_substitute_leaves_unknown_braces_alone():
    # unreachable through a parsed config, but substitute() must not crash
    assert config.substitute("agent {mystery}") == "agent {mystery}"


def test_a_run_section_survives_a_round_trip_through_yaml(tmp_path, write_config):
    path = write_config(
        tmp_path,
        """\
version: 1
gates:
  - id: test
    run: make test
run:
  worker: claude -p "$(cat {brief})"
  max_iterations: 5
""",
    )

    cfg = config.load(path)

    assert cfg.run.worker == 'claude -p "$(cat {brief})"'
    assert cfg.run.max_iterations == 5
    assert cfg.run.worker_timeout == config.DEFAULT_WORKER_TIMEOUT_SECONDS
