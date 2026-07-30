"""Load and validate `.wringer.yaml`.

The config surface is deliberately tiny (SPEC_VERIFY_V0.md §Config
design). Validation is strict: unknown keys are errors, because a typo
in a gate definition must not silently change what "verified" means.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILENAME = ".wringer.yaml"
DEFAULT_TIMEOUT_SECONDS = 120

# A gate id becomes a directory name in the bundle (`gates/NNN_<id>/`), so it
# is a slug rather than free text: no path separators, no spaces, no unicode
# lookalikes. A config typo must never write outside the run directory.
GATE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
MAX_GATE_ID_LENGTH = 64

_TOP_LEVEL_KEYS = {"version", "gates", "evidence"}
_GATE_KEYS = {"id", "run", "timeout", "optional", "required"}
_EVIDENCE_KEYS = {"include", "redact"}
_REDACT_KEYS = {"env"}


class ConfigError(Exception):
    """Invalid, missing, or unreadable configuration (CLI exit code 2)."""


@dataclass(frozen=True)
class Gate:
    id: str
    run: str
    timeout: int = DEFAULT_TIMEOUT_SECONDS
    optional: bool = False


@dataclass(frozen=True)
class Config:
    version: int
    gates: tuple[Gate, ...]
    # The `evidence:` section (include lists, redaction patterns) is
    # parsed for shape only until the Day-3/Day-4 bolts consume it.
    evidence: dict[str, Any] = field(default_factory=dict)


def load(path: Path) -> Config:
    if not path.is_file():
        raise ConfigError(
            f"no {path.name} in {path.parent} — run 'wring init' to create one"
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} is not valid YAML: {exc}") from exc
    return parse(raw, source=path.name)


def parse(raw: Any, source: str = CONFIG_FILENAME) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: top level must be a mapping")

    unknown = sorted(set(raw) - _TOP_LEVEL_KEYS)
    if unknown:
        raise ConfigError(f"{source}: unknown top-level keys: {', '.join(unknown)}")

    version = raw.get("version")
    if not _is_int(version) or version != 1:
        raise ConfigError(f"{source}: 'version: 1' is required (got {version!r})")

    gates_raw = raw.get("gates")
    if not isinstance(gates_raw, list) or not gates_raw:
        raise ConfigError(f"{source}: 'gates' must be a non-empty list")
    gates = tuple(
        _parse_gate(entry, index, source) for index, entry in enumerate(gates_raw)
    )

    seen: set[str] = set()
    for gate in gates:
        if gate.id in seen:
            raise ConfigError(f"{source}: duplicate gate id '{gate.id}'")
        seen.add(gate.id)

    evidence = raw.get("evidence")
    if evidence is None:
        evidence = {}
    if not isinstance(evidence, dict):
        raise ConfigError(f"{source}: 'evidence' must be a mapping")
    _validate_evidence(evidence, source)

    return Config(version=version, gates=gates, evidence=evidence)


def _validate_evidence(evidence: dict[str, Any], source: str) -> None:
    """Shape-check the `evidence:` section.

    `redact` is consumed now (Day 4), so a typo in it must be an error rather
    than silently switching redaction off — the one failure mode where a
    quiet default is dangerous. `include` is still parsed for shape only.
    """
    unknown = sorted(set(evidence) - _EVIDENCE_KEYS)
    if unknown:
        raise ConfigError(
            f"{source}: unknown keys under 'evidence': {', '.join(unknown)}"
        )

    redact = evidence.get("redact")
    if redact is None:
        return
    if not isinstance(redact, dict):
        raise ConfigError(f"{source}: 'evidence.redact' must be a mapping")

    unknown = sorted(set(redact) - _REDACT_KEYS)
    if unknown:
        raise ConfigError(
            f"{source}: unknown keys under 'evidence.redact': {', '.join(unknown)}"
        )

    patterns = redact.get("env")
    if patterns is None:
        return
    if not isinstance(patterns, list) or not all(
        isinstance(pattern, str) and pattern for pattern in patterns
    ):
        raise ConfigError(
            f"{source}: 'evidence.redact.env' must be a list of non-empty "
            "environment-variable name patterns, e.g. '*TOKEN*'"
        )


def _parse_gate(raw: Any, index: int, source: str) -> Gate:
    where = f"{source}: gates[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a mapping")

    unknown = sorted(set(raw) - _GATE_KEYS)
    if unknown:
        raise ConfigError(f"{where}: unknown keys: {', '.join(unknown)}")

    gate_id = raw.get("id")
    if not isinstance(gate_id, str) or not gate_id:
        raise ConfigError(f"{where}: 'id' must be a non-empty string")
    if len(gate_id) > MAX_GATE_ID_LENGTH:
        raise ConfigError(
            f"{where} ('{gate_id}'): 'id' must be at most "
            f"{MAX_GATE_ID_LENGTH} characters"
        )
    if not GATE_ID_PATTERN.fullmatch(gate_id):
        raise ConfigError(
            f"{where} ('{gate_id}'): 'id' must start with a letter or digit and "
            "use only letters, digits, '-' and '_' — it becomes a directory "
            "name in the evidence bundle"
        )

    run = raw.get("run")
    if not isinstance(run, str) or not run.strip():
        raise ConfigError(f"{where} ('{gate_id}'): 'run' must be a non-empty string")

    timeout = raw.get("timeout", DEFAULT_TIMEOUT_SECONDS)
    if not _is_int(timeout) or timeout <= 0:
        raise ConfigError(
            f"{where} ('{gate_id}'): 'timeout' must be a positive integer "
            f"of seconds (got {timeout!r})"
        )

    # The spec spells this both ways (`optional: true` in the init
    # template, `required: true` in the config section). Canonical field
    # is `optional`; `required` is accepted as its negation.
    if "optional" in raw and "required" in raw:
        raise ConfigError(
            f"{where} ('{gate_id}'): use either 'optional' or 'required', not both"
        )
    if "optional" in raw:
        optional = raw["optional"]
        if not isinstance(optional, bool):
            raise ConfigError(f"{where} ('{gate_id}'): 'optional' must be a boolean")
    elif "required" in raw:
        required = raw["required"]
        if not isinstance(required, bool):
            raise ConfigError(f"{where} ('{gate_id}'): 'required' must be a boolean")
        optional = not required
    else:
        optional = False

    return Gate(id=gate_id, run=run, timeout=timeout, optional=optional)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
