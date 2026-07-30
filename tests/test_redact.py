"""Which values count as secrets, and how thoroughly they are erased."""

from __future__ import annotations

from cox import redact


def build(env: dict[str, str], evidence: dict | None = None) -> redact.Redactor:
    return redact.Redactor.from_config(evidence, environ=env)


def test_the_default_patterns_catch_the_usual_names():
    redactor = build(
        {
            "GITHUB_TOKEN": "tok-aaaaaa",
            "MY_SECRET_THING": "sec-bbbbbb",
            "AWS_ACCESS_KEY_ID": "key-cccccc",
            "PATH": "/usr/bin:/bin",
            "HOME": "/Users/someone",
        }
    )

    assert set(redactor.secrets) == {"tok-aaaaaa", "sec-bbbbbb", "key-cccccc"}


def test_matching_is_case_insensitive():
    redactor = build({"github_token": "tok-aaaaaa"})

    assert redactor.secrets == ("tok-aaaaaa",)


def test_config_patterns_are_added_not_substituted():
    """Losing token protection must never be one line of config away."""
    redactor = build(
        {"GITHUB_TOKEN": "tok-aaaaaa", "DATABASE_URL": "postgres://u:pw@host"},
        {"redact": {"env": ["*URL*"]}},
    )

    assert set(redactor.secrets) == {"tok-aaaaaa", "postgres://u:pw@host"}


def test_short_values_are_left_alone():
    """A two-character 'secret' would match half the log."""
    redactor = build({"A_TOKEN": "ab", "B_TOKEN": "longenough"})

    assert redactor.secrets == ("longenough",)


def test_every_occurrence_goes():
    redactor = build({"GITHUB_TOKEN": "tok-aaaaaa"})

    scrubbed = redactor.scrub("use tok-aaaaaa here and tok-aaaaaa there")

    assert "tok-aaaaaa" not in scrubbed
    assert scrubbed == f"use {redact.PLACEHOLDER} here and {redact.PLACEHOLDER} there"


def test_a_secret_containing_another_leaves_no_tail():
    """Longest first: replacing the short one first would leave the rest of
    the long one sitting in the log."""
    redactor = build({"A_TOKEN": "abc123", "B_TOKEN": "abc123def456"})

    scrubbed = redactor.scrub("value=abc123def456")

    assert "abc123def456" not in scrubbed
    assert "def456" not in scrubbed


def test_bytes_are_scrubbed_too():
    redactor = build({"GITHUB_TOKEN": "tok-aaaaaa"})

    assert redactor.scrub_bytes(b"before tok-aaaaaa after") == (
        b"before " + redact.PLACEHOLDER.encode() + b" after"
    )


def test_no_matching_variables_means_no_op():
    redactor = build({"PATH": "/usr/bin"})

    assert redactor.secrets == ()
    assert redactor.scrub("nothing to do") == "nothing to do"
