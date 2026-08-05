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
    assert [gate.id for gate in cfg.gates] == [detect.PLACEHOLDER_GATE_ID]
    assert cfg.gates[0].run == detect.PLACEHOLDER_GATE_RUN
    assert cfg.gates[0].optional is False


# --- the blank template must describe the repo it was written into --------
#
# A field run pointed `wring init` at a real Python project — pyproject.toml,
# uv.lock, a .venv — and got back "no pyproject.toml" (field report
# 2026-08-05, R2-07). The refusal to invent gates was RIGHT: that project
# declares no ruff, mypy or pytest anywhere, so there is nothing to gate, and
# guessing `pytest -q` is the cleverness detect.py exists not to do. The
# sentence was what was wrong, and it turned a correct refusal into what
# looked like a broken detector.
#
# These two cases are the fix's whole contract, and they are worth a test
# rather than a proofread because the old message was a module-level
# constant: nothing about it could be true of a repository it had never seen.


def test_the_blank_template_names_what_it_found(tmp_path: Path):
    """A pyproject with nothing gateable in it. Detection still declines —
    and now says why, in terms of the file the reader is looking at."""
    write(tmp_path, "pyproject.toml", '[project]\nname = "x"\n')

    detection = detect.detect(tmp_path)
    assert detection.found is False
    assert detection.seen == ("pyproject.toml",)

    rendered = detect.template(detection)
    assert "Found pyproject.toml" in rendered
    assert "No pyproject.toml" not in rendered


def test_the_blank_template_still_reports_a_genuinely_empty_directory(
    tmp_path: Path,
):
    detection = detect.detect(tmp_path)
    assert detection.seen == ()

    rendered = detect.template(detection)
    assert "No pyproject.toml" in rendered
    assert "Found pyproject.toml" not in rendered


def test_a_makefile_is_named_once_not_twice(tmp_path: Path):
    """macOS's filesystem is case-insensitive by default, so both spellings
    stat the same file. "Found Makefile, makefile" reads like a bug."""
    write(tmp_path, "Makefile", "help:\n\techo hi\n")

    seen = detect.detect(tmp_path).seen
    assert len(seen) == 1
    assert seen[0].lower() == "makefile"


# --- recognising the untouched template -----------------------------------


def test_the_shipped_placeholder_is_recognised_as_untouched(tmp_path: Path):
    written = tmp_path / config.CONFIG_FILENAME
    written.write_text(detect.template(None), encoding="utf-8")

    assert detect.is_untouched_template(config.load(written).gates) is True


def test_a_real_gate_is_never_mistaken_for_the_placeholder(tmp_path: Path):
    written = tmp_path / config.CONFIG_FILENAME
    written.write_text(
        'version: 1\ngates:\n  - id: lint\n    run: "ruff check ."\n',
        encoding="utf-8",
    )

    assert detect.is_untouched_template(config.load(written).gates) is False


def test_a_lone_optional_placeholder_is_still_untouched(tmp_path: Path):
    """Marking the placeholder optional leaves a config with NO required
    gates. `wring verify` exits 0 there having proven even less than the
    placeholder proved, so it must not be the way to silence the warning."""
    written = tmp_path / config.CONFIG_FILENAME
    written.write_text(
        "version: 1\ngates:\n"
        f"  - id: {detect.PLACEHOLDER_GATE_ID}\n"
        f'    run: "{detect.PLACEHOLDER_GATE_RUN}"\n'
        "    optional: true\n",
        encoding="utf-8",
    )

    assert detect.is_untouched_template(config.load(written).gates) is True


def test_the_placeholder_left_behind_as_optional_is_not_untouched(
    tmp_path: Path,
):
    """Someone who added real gates and kept the placeholder as an optional
    curiosity has configured this repo. Only the required gates decide."""
    written = tmp_path / config.CONFIG_FILENAME
    written.write_text(
        "version: 1\ngates:\n"
        f'  - id: {detect.PLACEHOLDER_GATE_ID}\n'
        f'    run: "{detect.PLACEHOLDER_GATE_RUN}"\n'
        "    optional: true\n"
        '  - id: lint\n    run: "ruff check ."\n',
        encoding="utf-8",
    )

    assert detect.is_untouched_template(config.load(written).gates) is False
