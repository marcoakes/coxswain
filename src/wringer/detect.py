"""What `wring init` writes, and how it guesses.

The spec's ruling is the design: *if detection is uncertain, generate
comments rather than being clever*. So detection here is deliberately
literal. It reports commands the repository has already written down —
a `pyproject.toml` that configures ruff, a `package.json` with a `test`
script, a `Makefile` with a `lint` target — and never invents one. When it
finds nothing it says so and hands over a commented template, because a
wrong gate is worse than an absent one: it would make `wring verify` prove
something nobody asked for.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILENAME = ".wringer.yaml"

# Gates are declared cheapest first (spec §Config design, rule 1), so the
# feedback a developer waits for arrives in the order they can act on.
_ORDER = ["format", "lint", "typecheck", "build", "test"]

# Makefile targets worth turning into gates, and the id each becomes.
_MAKE_TARGETS = {
    "format-check": "format",
    "fmt-check": "format",
    "lint": "lint",
    "typecheck": "typecheck",
    "types": "typecheck",
    "build": "build",
    "test": "test",
}

# package.json scripts, likewise.
_NPM_SCRIPTS = {
    "format:check": "format",
    "format-check": "format",
    "lint": "lint",
    "typecheck": "typecheck",
    "type-check": "typecheck",
    "build": "build",
    "test": "test",
}

_MAKE_TARGET_LINE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?!=)")

_SLOW = {"test", "build", "typecheck"}


@dataclass(frozen=True)
class Candidate:
    id: str
    run: str
    timeout: int = 120
    optional: bool = False


@dataclass(frozen=True)
class Detection:
    candidates: tuple[Candidate, ...] = ()
    sources: tuple[str, ...] = ()

    @property
    def found(self) -> bool:
        return bool(self.candidates)


def detect(root: Path) -> Detection:
    """Look for commands this repository already declares."""
    found: list[Candidate] = []
    sources: list[str] = []

    for probe in (_detect_python, _detect_npm, _detect_make):
        candidates, source = probe(root)
        if candidates:
            found.extend(candidates)
            sources.append(source)

    return Detection(
        candidates=tuple(_ordered(_deduplicated(found))), sources=tuple(sources)
    )


def template(detection: Detection | None = None) -> str:
    """Render the `.wringer.yaml` to write."""
    if detection is None or not detection.found:
        return BLANK_TEMPLATE

    lines = [
        f"# {CONFIG_FILENAME} — the gates Wringer runs to prove a change is"
        " mergeable.",
        f"# Detected from: {', '.join(detection.sources)}.",
        "#",
        "# These are commands this repository already declares. Check they are",
        "# the ones you want proven, and edit freely — they run in the repo",
        "# root, in this order, cheapest first. A failing required gate fails",
        "# the run (exit 1); `optional: true` records a failure without",
        "# failing the run.",
        "version: 1",
        "",
        "gates:",
    ]
    for candidate in detection.candidates:
        lines.append(f"  - id: {candidate.id}")
        lines.append(f"    run: {candidate.run}")
        lines.append(f"    timeout: {candidate.timeout}")
        if candidate.optional:
            lines.append("    optional: true")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _timeout_for(gate_id: str) -> int:
    return 300 if gate_id in _SLOW else 120


def _deduplicated(candidates: list[Candidate]) -> list[Candidate]:
    """Two ecosystems can both offer a `lint`, but ids name directories, so
    they have to stay unique."""
    seen: set[str] = set()
    unique: list[Candidate] = []
    for candidate in candidates:
        if candidate.id not in seen:
            seen.add(candidate.id)
            unique.append(candidate)
            continue
        suffix = 2
        while f"{candidate.id}-{suffix}" in seen:
            suffix += 1
        renamed = f"{candidate.id}-{suffix}"
        seen.add(renamed)
        unique.append(
            Candidate(
                id=renamed,
                run=candidate.run,
                timeout=candidate.timeout,
                optional=candidate.optional,
            )
        )
    return unique


def _ordered(candidates: list[Candidate]) -> list[Candidate]:
    def rank(candidate: Candidate) -> tuple[int, str]:
        base = candidate.id.split("-")[0]
        return (_ORDER.index(base) if base in _ORDER else len(_ORDER), candidate.id)

    return sorted(candidates, key=rank)


def _detect_python(root: Path) -> tuple[list[Candidate], str]:
    pyproject = root / "pyproject.toml"
    data: dict = {}
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
            data = {}

    declared = _python_dependency_names(data)
    tool = data.get("tool")
    tools = tool if isinstance(tool, dict) else {}
    candidates: list[Candidate] = []

    if "ruff" in tools or (root / ".ruff.toml").is_file() or "ruff" in declared:
        candidates.append(Candidate("lint", "ruff check .", _timeout_for("lint")))
    if "mypy" in tools or (root / "mypy.ini").is_file() or "mypy" in declared:
        candidates.append(Candidate("typecheck", "mypy .", _timeout_for("typecheck")))
    has_tests = (root / "tests").is_dir() or any(root.glob("test_*.py"))
    if "pytest" in tools or "pytest" in declared or has_tests:
        candidates.append(Candidate("test", "pytest -q", _timeout_for("test")))

    if not candidates:
        return [], ""
    return candidates, "pyproject.toml" if pyproject.is_file() else "a Python layout"


def _python_dependency_names(data: dict) -> set[str]:
    """Every requirement a pyproject mentions, reduced to bare names."""
    project = data.get("project")
    if not isinstance(project, dict):
        return set()
    requirements: list[str] = []
    if isinstance(project.get("dependencies"), list):
        requirements += [str(item) for item in project["dependencies"]]
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        for group in optional.values():
            if isinstance(group, list):
                requirements += [str(item) for item in group]
    return {
        re.split(r"[^A-Za-z0-9_.-]", item, maxsplit=1)[0].lower()
        for item in requirements
    }


def _detect_npm(root: Path) -> tuple[list[Candidate], str]:
    package = root / "package.json"
    if not package.is_file():
        return [], ""
    try:
        data = json.loads(package.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return [], ""

    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return [], ""

    candidates = [
        Candidate(
            _NPM_SCRIPTS[name],
            "npm test" if name == "test" else f"npm run {name}",
            _timeout_for(_NPM_SCRIPTS[name]),
        )
        for name in scripts
        if name in _NPM_SCRIPTS
    ]
    return candidates, "package.json" if candidates else ""


def _detect_make(root: Path) -> tuple[list[Candidate], str]:
    makefile = next(
        (root / name for name in ("Makefile", "makefile") if (root / name).is_file()),
        None,
    )
    if makefile is None:
        return [], ""
    try:
        text = makefile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], ""

    targets = {
        match.group(1)
        for line in text.splitlines()
        if (match := _MAKE_TARGET_LINE.match(line))
    }
    candidates = [
        Candidate(
            _MAKE_TARGETS[target],
            f"make {target}",
            _timeout_for(_MAKE_TARGETS[target]),
        )
        for target in sorted(targets)
        if target in _MAKE_TARGETS
    ]
    return candidates, "Makefile" if candidates else ""


BLANK_TEMPLATE = f"""\
# {CONFIG_FILENAME} — the gates Wringer runs to prove a change is mergeable.
# Spec: https://github.com/marcoakes/wringer/blob/main/SPEC_VERIFY_V0.md
#
# Nothing was detected here — no pyproject.toml, package.json or Makefile
# declaring commands — so this is a template, not a guess. Replace the
# examples with the commands that prove YOUR change is mergeable, then run:
# wring verify
#
# Rules: gates run in order, cheapest first. A failing required gate fails
# the run (exit 1). Mark a gate `optional: true` to record its failure
# without failing the run.
version: 1

gates:
  - id: format
    run: make format-check
    optional: true

  - id: lint
    run: make lint

  - id: test
    run: make test

evidence:
  include:
    - git.diff
    - git.status
    - env
    - logs
"""
