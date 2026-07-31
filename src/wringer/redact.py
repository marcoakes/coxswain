"""Keep secrets out of the evidence.

A bundle captures whatever a gate printed, so a tool that echoes
`$GITHUB_TOKEN` on failure would otherwise write a live credential to disk —
and `.wringer/` is one `git add -f` away from being public.

Redaction happens **before** the write, never as a cleanup pass: the raw
value must not reach the file at all (SPEC_VERIFY_V0.md §Config design,
rule 5). That is why gate output is captured through a pipe rather than
handed straight to a file descriptor.

What counts as a secret: the *value* of any environment variable whose
*name* matches a redaction pattern. Defaults are `*TOKEN*`, `*SECRET*` and
`*KEY*`; a repo's `.wringer.yaml` can add more, but cannot remove the defaults —
losing token protection should never be one line of config away.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_ENV_PATTERNS = ("*TOKEN*", "*SECRET*", "*KEY*")
PLACEHOLDER = "[REDACTED]"

# Values shorter than this are left alone. A two-character "secret" would
# match half the log and destroy the evidence it was meant to protect —
# and real credentials are not two characters long.
MIN_SECRET_LENGTH = 6


@dataclass(frozen=True)
class Redactor:
    """The secret values to erase, longest first."""

    secrets: tuple[str, ...] = ()

    @classmethod
    def from_config(
        cls,
        evidence: Mapping[str, object] | None = None,
        environ: Mapping[str, str] | None = None,
        extra_names: tuple[str, ...] = (),
    ) -> Redactor:
        """Build the redactor for a run.

        `extra_names` are exact variable names to protect regardless of the
        patterns — `judge.api_key_env` names one, and folding its value in
        here is what stops a credential reaching a request body or a bundle
        even if something echoes it.
        """
        patterns = [pattern.upper() for pattern in _configured_patterns(evidence)]
        patterns += [name.upper() for name in extra_names]
        env = os.environ if environ is None else environ

        values = {
            value
            for name, value in env.items()
            if len(value) >= MIN_SECRET_LENGTH
            and any(fnmatch.fnmatchcase(name.upper(), p) for p in patterns)
        }
        # Longest first: if one secret contains another, replacing the short
        # one first would leave a recognisable tail of the long one behind.
        return cls(tuple(sorted(values, key=len, reverse=True)))

    def scrub(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, PLACEHOLDER)
        return text

    def scrub_bytes(self, data: bytes) -> bytes:
        placeholder = PLACEHOLDER.encode()
        for secret in self.secrets:
            data = data.replace(secret.encode("utf-8", "surrogateescape"), placeholder)
        return data


def _configured_patterns(evidence: Mapping[str, object] | None) -> list[str]:
    """Defaults plus whatever the repo added — never fewer than the defaults."""
    patterns = list(DEFAULT_ENV_PATTERNS)
    if not evidence:
        return patterns
    redact = evidence.get("redact")
    if not isinstance(redact, Mapping):
        return patterns
    extra = redact.get("env")
    if isinstance(extra, list):
        patterns.extend(str(pattern) for pattern in extra)
    return patterns
