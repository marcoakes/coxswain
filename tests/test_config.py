"""Config loading and validation."""

import pytest

from cox import config


def parse(raw):
    return config.parse(raw)


def gate(**overrides):
    entry = {"id": "test", "run": "make test"}
    entry.update(overrides)
    return entry


def test_valid_config_parses_with_defaults():
    cfg = parse({"version": 1, "gates": [gate()]})
    assert cfg.version == 1
    assert len(cfg.gates) == 1
    assert cfg.gates[0].id == "test"
    assert cfg.gates[0].run == "make test"
    assert cfg.gates[0].timeout == config.DEFAULT_TIMEOUT_SECONDS
    assert cfg.gates[0].optional is False
    assert cfg.evidence == {}


def test_explicit_fields_parse():
    cfg = parse(
        {
            "version": 1,
            "gates": [gate(timeout=300, optional=True)],
            "evidence": {"include": ["git.diff"]},
        }
    )
    assert cfg.gates[0].timeout == 300
    assert cfg.gates[0].optional is True
    assert cfg.evidence == {"include": ["git.diff"]}


def test_required_is_accepted_as_negated_optional():
    cfg = parse(
        {"version": 1, "gates": [gate(required=True), gate(id="x", required=False)]}
    )
    assert cfg.gates[0].optional is False
    assert cfg.gates[1].optional is True


def test_optional_and_required_together_is_an_error():
    with pytest.raises(config.ConfigError, match="not both"):
        parse({"version": 1, "gates": [gate(optional=True, required=True)]})


@pytest.mark.parametrize(
    "raw, match",
    [
        (None, "top level"),
        ([], "top level"),
        ({"gates": [{"id": "t", "run": "make t"}]}, "version"),
        ({"version": 2, "gates": [{"id": "t", "run": "make t"}]}, "version"),
        ({"version": True, "gates": [{"id": "t", "run": "make t"}]}, "version"),
        ({"version": 1}, "gates"),
        ({"version": 1, "gates": []}, "gates"),
        ({"version": 1, "gates": "make test"}, "gates"),
        (
            {"version": 1, "gates": [{"id": "t", "run": "make t"}], "extra": 1},
            "unknown top-level",
        ),
        (
            {"version": 1, "gates": [{"id": "t", "run": "make t"}], "evidence": []},
            "evidence",
        ),
    ],
)
def test_invalid_top_level_shapes_raise(raw, match):
    with pytest.raises(config.ConfigError, match=match):
        parse(raw)


@pytest.mark.parametrize(
    "entry, match",
    [
        ("make test", "mapping"),
        ({"run": "make test"}, "'id'"),
        ({"id": "", "run": "make test"}, "'id'"),
        ({"id": "t"}, "'run'"),
        ({"id": "t", "run": True}, "'run'"),
        ({"id": "t", "run": "make t", "timeout": 0}, "timeout"),
        ({"id": "t", "run": "make t", "timeout": "fast"}, "timeout"),
        ({"id": "t", "run": "make t", "timeout": True}, "timeout"),
        ({"id": "t", "run": "make t", "optional": "yes"}, "optional"),
        ({"id": "t", "run": "make t", "required": "yes"}, "required"),
        ({"id": "t", "run": "make t", "retries": 3}, "unknown keys"),
    ],
)
def test_invalid_gate_entries_raise(entry, match):
    with pytest.raises(config.ConfigError, match=match):
        parse({"version": 1, "gates": [entry]})


def test_duplicate_gate_ids_raise():
    with pytest.raises(config.ConfigError, match="duplicate"):
        parse({"version": 1, "gates": [gate(), gate()]})


@pytest.mark.parametrize(
    "gate_id",
    [
        "../../escape",  # would write outside the bundle
        "..",
        "sub/dir",
        "back\\slash",
        "with space",
        "trailing.",
        "dots.in.id",
        "-leading-dash",
        "_leading_underscore",
        "héllo",  # unicode lookalike
        "tab\there",
        "new\nline",
        "a" * 65,
    ],
)
def test_gate_ids_that_are_not_slugs_are_rejected(gate_id):
    """A gate id names a directory, so a bad one must fail loudly at parse
    time rather than quietly writing somewhere unexpected."""
    with pytest.raises(config.ConfigError, match="'id'"):
        parse({"version": 1, "gates": [gate(id=gate_id)]})


@pytest.mark.parametrize(
    "gate_id", ["t", "test", "Test", "lint-2", "unit_tests", "3rd", "a" * 64]
)
def test_slug_gate_ids_are_accepted(gate_id):
    cfg = parse({"version": 1, "gates": [gate(id=gate_id)]})
    assert cfg.gates[0].id == gate_id


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(config.ConfigError, match="cox init"):
        config.load(tmp_path / config.CONFIG_FILENAME)


def test_load_invalid_yaml_raises(tmp_path):
    path = tmp_path / config.CONFIG_FILENAME
    path.write_text("version: [unclosed", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="not valid YAML"):
        config.load(path)


def test_load_round_trips_a_real_file(tmp_path):
    path = tmp_path / config.CONFIG_FILENAME
    path.write_text(
        'version: 1\ngates:\n  - id: check\n    run: "true"\n',
        encoding="utf-8",
    )
    cfg = config.load(path)
    assert [g.id for g in cfg.gates] == ["check"]
