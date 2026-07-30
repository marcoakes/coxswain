"""What `wring init` finds, and what it refuses to guess."""

from __future__ import annotations

import json
from pathlib import Path

from wringer import config, detect


def ids(root: Path) -> list[str]:
    return [candidate.id for candidate in detect.detect(root).candidates]


def runs(root: Path) -> dict[str, str]:
    return {c.id: c.run for c in detect.detect(root).candidates}


def write(root: Path, name: str, text: str) -> None:
    (root / name).write_text(text, encoding="utf-8")


def test_a_python_project_declaring_ruff_and_pytest(tmp_path: Path):
    write(
        tmp_path,
        "pyproject.toml",
        """\
[project]
name = "thing"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.6"]
""",
    )

    assert ids(tmp_path) == ["lint", "test"]
    assert runs(tmp_path) == {"lint": "ruff check .", "test": "pytest -q"}


def test_tool_sections_count_as_declarations(tmp_path: Path):
    write(
        tmp_path,
        "pyproject.toml",
        "[tool.ruff]\nline-length = 88\n\n[tool.mypy]\nstrict = true\n",
    )

    assert ids(tmp_path) == ["lint", "typecheck"]


def test_python_test_files_are_enough_for_a_test_gate(tmp_path: Path):
    """No pyproject, but real Python tests — that is somebody writing pytest
    down, even if they never said so in a manifest."""
    (tmp_path / "tests").mkdir()
    write(tmp_path, "tests/test_thing.py", "def test_it():\n    assert True\n")

    assert ids(tmp_path) == ["test"]


def test_a_test_file_at_the_root_counts_too(tmp_path: Path):
    write(tmp_path, "test_thing.py", "def test_it():\n    assert True\n")

    assert ids(tmp_path) == ["test"]


def test_a_bare_tests_directory_is_not_a_python_project(tmp_path: Path):
    """A `tests/` directory is somewhere to put tests, not a declaration that
    they are Python ones."""
    (tmp_path / "tests").mkdir()

    assert ids(tmp_path) == []


def test_a_make_project_with_shell_tests_gets_no_pytest_gate(tmp_path: Path):
    """The regression this guards: a shell project with `tests/run.sh` was
    handed an invented `pytest -q` gate, which then failed `wring verify`
    with "no tests ran" on a healthy repo — and pushed the real `make test`
    gate out to the id `test-2`."""
    (tmp_path / "tests").mkdir()
    write(tmp_path, "tests/run.sh", "#!/bin/sh\necho ok\n")
    write(tmp_path, "Makefile", "lint:\n\tsh -n src/*.sh\n\ntest:\n\tsh tests/run.sh\n")

    assert runs(tmp_path) == {"lint": "make lint", "test": "make test"}


def test_npm_scripts_become_gates(tmp_path: Path):
    write(
        tmp_path,
        "package.json",
        json.dumps({"scripts": {"test": "vitest", "lint": "eslint .", "dev": "vite"}}),
    )

    detected = runs(tmp_path)
    assert detected == {"lint": "npm run lint", "test": "npm test"}
    # `dev` is not a gate — it proves nothing


def test_makefile_targets_become_gates(tmp_path: Path):
    write(
        tmp_path,
        "Makefile",
        "lint:\n\truff check .\n\ntest:\n\tpytest\n\ndeploy:\n\t./ship.sh\n",
    )

    detected = runs(tmp_path)
    assert detected == {"lint": "make lint", "test": "make test"}
    # `deploy` is not a gate — verifying must never ship anything


def test_variable_assignments_are_not_targets(tmp_path: Path):
    write(tmp_path, "Makefile", "lint := ruff\ntest:\n\tpytest\n")

    assert ids(tmp_path) == ["test"]


def test_gates_come_out_cheapest_first(tmp_path: Path):
    write(
        tmp_path,
        "Makefile",
        "test:\n\tpytest\n\nbuild:\n\tmake all\n\nlint:\n\truff check .\n"
        "\nformat-check:\n\tblack --check .\n",
    )

    assert ids(tmp_path) == ["format", "lint", "build", "test"]


def test_two_ecosystems_keep_their_ids_unique(tmp_path: Path):
    write(tmp_path, "pyproject.toml", "[tool.ruff]\n")
    write(tmp_path, "package.json", json.dumps({"scripts": {"lint": "eslint ."}}))

    detected = ids(tmp_path)
    # ids name directories in the bundle, so a collision is not allowed
    assert len(detected) == len(set(detected))
    assert detected == ["lint", "lint-2"]


def test_nothing_detectable_means_no_guesses(tmp_path: Path):
    (tmp_path / "README.md").write_text("hi\n", encoding="utf-8")

    detection = detect.detect(tmp_path)
    assert detection.found is False
    assert detection.candidates == ()


def test_malformed_manifests_are_survived_not_crashed(tmp_path: Path):
    write(tmp_path, "pyproject.toml", "this is not [ valid toml")
    write(tmp_path, "package.json", "{not json")

    assert detect.detect(tmp_path).candidates == ()


def test_the_detected_template_parses_with_our_own_strict_loader(tmp_path: Path):
    write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "x"\n\n[project.optional-dependencies]\n'
        'dev = ["pytest", "ruff", "mypy"]\n',
    )

    rendered = detect.template(detect.detect(tmp_path))
    written = tmp_path / config.CONFIG_FILENAME
    written.write_text(rendered, encoding="utf-8")

    cfg = config.load(written)
    assert [gate.id for gate in cfg.gates] == ["lint", "typecheck", "test"]
    assert cfg.gates[0].run == "ruff check ."
    assert cfg.gates[2].timeout == 300


def test_the_blank_template_also_parses(tmp_path: Path):
    written = tmp_path / config.CONFIG_FILENAME
    written.write_text(detect.template(None), encoding="utf-8")

    cfg = config.load(written)
    assert [gate.id for gate in cfg.gates] == ["format", "lint", "test"]
    assert cfg.gates[0].optional is True
