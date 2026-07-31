"""Load and validate a rubric — `wringer.rubric.v1` (SPEC_JUDGE_V0.md §4).

A rubric is its own file rather than a section of `.wringer.yaml`, for one
reason: **its bytes get sent over a wire.** That earns it its own size and
shape limits, and keeps the config tiny.

It is *source*, not evidence, so it does not live under `.wringer/` — that
directory is gitignored, and a rubric is something a repo commits and
reviews.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from wringer.config import GATE_ID_PATTERN, MAX_GATE_ID_LENGTH

SCHEMA_VERSION = "wringer.rubric.v1"

# Caps, because these bytes travel. A rubric is a page of criteria, not a
# specification document; twenty criteria is already more than a judge can
# weigh usefully in one pass.
MAX_RUBRIC_BYTES = 32 * 1024
MAX_CRITERIA = 20

_TOP_LEVEL_KEYS = {"schema_version", "title", "criteria"}
_CRITERION_KEYS = {"id", "title", "guidance", "required", "human"}


class RubricError(Exception):
    """An unusable rubric (CLI exit code 2)."""


@dataclass(frozen=True)
class Criterion:
    id: str
    title: str
    guidance: str = ""
    required: bool = True
    # A criterion no judge can decide — "the copy reads well", "this is the
    # right trade-off". It is never sent, and it comes back unscored, because
    # a model guessing at it would be exactly the confident-wrong-answer the
    # rubric exists to prevent (SPEC_INTENT_V0.md §1, defence 3).
    human: bool = False


@dataclass(frozen=True)
class Rubric:
    title: str
    criteria: tuple[Criterion, ...]
    path: str
    sha256: str

    @property
    def required_ids(self) -> tuple[str, ...]:
        return tuple(c.id for c in self.criteria if c.required)

    @property
    def machine_criteria(self) -> tuple[Criterion, ...]:
        """The ones a judge may be asked about. Everything else waits for a
        human, and asking a model anyway would be inventing a verdict."""
        return tuple(c for c in self.criteria if not c.human)


def load(path: Path, root: Path) -> Rubric:
    """Read and validate a rubric, refusing anything outside the repo.

    `root` bounds it: a rubric path that escapes the repo — by `..`, by an
    absolute path, or through a symlink — is refused, because a config must
    not be able to point Wringer at an arbitrary file and have its contents
    posted to an endpoint.
    """
    import hashlib

    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        inside = resolved.is_relative_to(root.resolve())
    except AttributeError:  # pragma: no cover - Python < 3.9
        inside = str(resolved).startswith(str(root.resolve()))
    if not inside:
        raise RubricError(
            f"rubric {path} resolves outside the repository ({resolved}) — its "
            "contents would be sent to an endpoint, so it must be a file the "
            "repo itself commits"
        )

    if not resolved.is_file():
        raise RubricError(f"no rubric at {path}")

    raw_bytes = resolved.read_bytes()
    if len(raw_bytes) > MAX_RUBRIC_BYTES:
        raise RubricError(
            f"rubric {path} is {len(raw_bytes)} bytes, over the "
            f"{MAX_RUBRIC_BYTES}-byte limit — these bytes travel"
        )

    try:
        data = yaml.safe_load(raw_bytes.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise RubricError(f"rubric {path} is not valid YAML: {exc}") from exc

    rubric = parse_document(data, str(path))
    return Rubric(
        title=rubric[0],
        criteria=rubric[1],
        path=str(path),
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


def parse_document(data: Any, where: str) -> tuple[str, tuple[Criterion, ...]]:
    """Validate an already-loaded rubric mapping.

    Public because `wring spec` builds a rubric in memory and must prove it is
    one *before* writing it. Running the real parser is what makes
    "the criteria block is a `wringer.rubric.v1` document by construction"
    (SPEC_INTENT_V0.md §3) structural rather than aspirational.
    """
    if not isinstance(data, dict):
        raise RubricError(f"rubric {where}: top level must be a mapping")

    unknown = sorted(set(data) - _TOP_LEVEL_KEYS)
    if unknown:
        raise RubricError(f"rubric {where}: unknown keys: {', '.join(unknown)}")

    declared = data.get("schema_version")
    if declared != SCHEMA_VERSION:
        raise RubricError(
            f"rubric {where}: 'schema_version: {SCHEMA_VERSION}' is required "
            f"(got {declared!r})"
        )

    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise RubricError(f"rubric {where}: 'title' must be a non-empty string")

    entries = data.get("criteria")
    if not isinstance(entries, list) or not entries:
        raise RubricError(f"rubric {where}: 'criteria' must be a non-empty list")
    if len(entries) > MAX_CRITERIA:
        raise RubricError(
            f"rubric {where}: {len(entries)} criteria, over the limit of "
            f"{MAX_CRITERIA} — a judge cannot weigh more than that in one pass"
        )

    criteria = tuple(
        _parse_criterion(entry, index, where) for index, entry in enumerate(entries)
    )

    seen: set[str] = set()
    for criterion in criteria:
        if criterion.id in seen:
            raise RubricError(f"rubric {where}: duplicate criterion id "
                              f"'{criterion.id}'")
        seen.add(criterion.id)

    if not any(c.required for c in criteria):
        raise RubricError(
            f"rubric {where}: at least one criterion must be required, or a "
            "verdict could never be anything but 'pass'"
        )
    return title, criteria


def _parse_criterion(raw: Any, index: int, where: str) -> Criterion:
    at = f"rubric {where}: criteria[{index}]"
    if not isinstance(raw, dict):
        raise RubricError(f"{at} must be a mapping")

    unknown = sorted(set(raw) - _CRITERION_KEYS)
    if unknown:
        raise RubricError(f"{at}: unknown keys: {', '.join(unknown)}")

    criterion_id = raw.get("id")
    if not isinstance(criterion_id, str) or not criterion_id:
        raise RubricError(f"{at}: 'id' must be a non-empty string")
    # Same slug rule as a gate id: ids appear in verdicts and are matched
    # against a model's reply, so they must be unambiguous.
    if len(criterion_id) > MAX_GATE_ID_LENGTH or not GATE_ID_PATTERN.fullmatch(
        criterion_id
    ):
        raise RubricError(
            f"{at} ('{criterion_id}'): 'id' must be a slug — letters, digits, "
            "'-' and '_', starting with a letter or digit"
        )

    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise RubricError(f"{at} ('{criterion_id}'): 'title' must be a non-empty "
                          "string")

    guidance = raw.get("guidance", "")
    if not isinstance(guidance, str):
        raise RubricError(f"{at} ('{criterion_id}'): 'guidance' must be a string")

    required = raw.get("required", True)
    if not isinstance(required, bool):
        raise RubricError(f"{at} ('{criterion_id}'): 'required' must be a boolean")

    human = raw.get("human", False)
    if not isinstance(human, bool):
        raise RubricError(f"{at} ('{criterion_id}'): 'human' must be a boolean")

    return Criterion(
        id=criterion_id,
        title=title,
        guidance=guidance,
        required=required,
        human=human,
    )
