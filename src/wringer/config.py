"""Load and validate `.wringer.yaml`.

The config surface is deliberately tiny (SPEC_VERIFY_V0.md §Config
design). Validation is strict: unknown keys are errors, because a typo
in a gate definition must not silently change what "verified" means.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILENAME = ".wringer.yaml"
DEFAULT_TIMEOUT_SECONDS = 120

# `wring run` defaults (SPEC_RUN_V0.md §Config). Three laps is enough to show
# whether a worker is converging without spending an afternoon proving it is
# not; fifteen minutes is a generous single turn for a coding agent.
DEFAULT_MAX_ITERATIONS = 3
DEFAULT_WORKER_TIMEOUT_SECONDS = 900

# What a worker command may ask Wringer to substitute. Anything else in
# braces is a typo, and a typo that reached the shell would be a command
# nobody wrote.
WORKER_PLACEHOLDERS = ("brief", "evidence_dir", "iteration")

# `{name}` not preceded by `$`, so `${SHELL_VAR}` is the shell's business and
# passes through untouched.
_PLACEHOLDER_PATTERN = re.compile(r"(?<!\$)\{([a-z_]+)\}")

# A gate id becomes a directory name in the bundle (`gates/NNN_<id>/`), so it
# is a slug rather than free text: no path separators, no spaces, no unicode
# lookalikes. A config typo must never write outside the run directory.
GATE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
MAX_GATE_ID_LENGTH = 64

_TOP_LEVEL_KEYS = {"version", "gates", "evidence", "run", "judge", "fleet"}
_GATE_KEYS = {"id", "run", "timeout", "optional", "required"}
_EVIDENCE_KEYS = {"include", "redact"}
_REDACT_KEYS = {"env"}
_RUN_KEYS = {"worker", "max_iterations", "worker_timeout", "wall_clock"}
_FLEET_KEYS = {
    "concurrency",
    "deadline",
    "progress_window",
    "retries",
    "on_exhausted",
    "join",
    "child",
    "worker_fallbacks",
    "worktree",
}
_CHILD_KEYS = {"max_iterations", "worker_timeout", "wall_clock"}
_ACP_KEYS = {"command", "args", "env_passthrough"}

_JUDGE_KEYS = {
    "endpoint",
    "model",
    "rubric",
    "api_key_env",
    "timeout",
    "max_output_tokens",
}

# `wring judge` defaults (SPEC_JUDGE_V0.md §3). endpoint, model and rubric
# have no defaults and never will: Wringer contacts the endpoint you wrote
# down, never one it guessed.
DEFAULT_JUDGE_TIMEOUT_SECONDS = 120
DEFAULT_MAX_OUTPUT_TOKENS = 1024

# Hosts a cleartext endpoint may name. Anywhere else must be https, because
# a rubric and a diff are not things to put on the wire in the clear.
_LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]"}


class ConfigError(Exception):
    """Invalid, missing, or unreadable configuration (CLI exit code 2)."""


@dataclass(frozen=True)
class Gate:
    id: str
    run: str
    timeout: int = DEFAULT_TIMEOUT_SECONDS
    optional: bool = False


@dataclass(frozen=True)
class Run:
    """The `run:` section — what `wring run` drives (SPEC_RUN_V0.md).

    `worker` has no default and never will. Wringer runs the command a repo
    wrote down; inventing one would be the same sin as inventing a gate.
    """

    # Either a shell command (the original form, supported forever) or an
    # AcpWorker. Both run under the same supervision invariants; the loop
    # does not know or care which it got, and that is deliberate.
    worker: str | AcpWorker
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    worker_timeout: int = DEFAULT_WORKER_TIMEOUT_SECONDS
    # Optional, no default: the loop is already structurally bounded by
    # iterations x worker_timeout, so a wall clock is a second opinion the
    # repo asks for rather than one Wringer imposes.
    wall_clock: int | None = None


@dataclass(frozen=True)
class AcpWorker:
    """`run.worker.acp` — an agent spoken to over the Agent Client Protocol.

    The second worker form. A shell string says "run this and see what
    changed"; this says "hold a session with an agent that speaks a
    standard". Wringer is the ACP *client* and never the agent — that
    distinction is the whole neutrality position (SPEC_ACP_V0.md).
    """

    command: str
    args: tuple[str, ...] = ()
    # NAMES of variables to pass through, never values. Everything not named
    # is withheld: an agent gets a minimal environment, not the operator's
    # whole shell. Each named variable's value is folded into the redactor.
    env_passthrough: tuple[str, ...] = ()


@dataclass(frozen=True)
class Judge:
    """The `judge:` section — what `wring judge` may contact (SPEC_JUDGE_V0).

    `endpoint`, `model` and `rubric` have no defaults and never will. A repo
    with no `judge:` section leaves no reachable code path in the program
    that opens a socket, which is the whole network story in one rule.
    """

    endpoint: str
    model: str
    rubric: str
    api_key_env: str | None = None
    timeout: int = DEFAULT_JUDGE_TIMEOUT_SECONDS
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS


@dataclass(frozen=True)
class Fleet:
    """The `fleet:` section (SPEC_SUPERVISION_V0.md §S3).

    `deadline` is required and has no default: an unbounded fleet is the
    thing this whole slice exists to make impossible.
    """

    deadline: int
    concurrency: int = 4
    progress_window: int = 1200
    retries: int = 1
    on_exhausted: str = "park"
    join: str = "all"
    child_max_iterations: int | None = None
    worker_fallbacks: tuple[str, ...] = ()
    # Off by default. When on, the fleet gives each task its own git
    # worktree so parallel children cannot fight over one working tree.
    # This is the ONLY git write Wringer ever makes, and it is metadata:
    # add and remove. No commit, no branch move, no push — that law holds.
    worktree: bool = False


@dataclass(frozen=True)
class Config:
    version: int
    gates: tuple[Gate, ...]
    # The `evidence:` section (include lists, redaction patterns) is
    # parsed for shape only until the Day-3/Day-4 bolts consume it.
    evidence: dict[str, Any] = field(default_factory=dict)
    # None when the repo has not opted into the loop. `wring verify` neither
    # needs nor reads this; `wring run` refuses without it.
    run: Run | None = None
    # None when the repo has not opted into the judge. Its absence is what
    # makes a network call unreachable rather than merely unlikely.
    judge: Judge | None = None
    # None when the repo has not opted into fleets.
    fleet: Fleet | None = None


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

    return Config(
        version=version,
        gates=gates,
        evidence=evidence,
        run=_parse_run(raw.get("run"), source),
        judge=_parse_judge(raw.get("judge"), source),
        fleet=_parse_fleet(raw.get("fleet"), source),
    )


def _parse_fleet(raw: Any, source: str) -> Fleet | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: 'fleet' must be a mapping")

    unknown = sorted(set(raw) - _FLEET_KEYS)
    if unknown:
        raise ConfigError(f"{source}: unknown keys under 'fleet': {', '.join(unknown)}")

    if raw.get("deadline") is None:
        raise ConfigError(
            f"{source}: 'fleet.deadline' is required — a fleet without a "
            "wall clock is exactly the thing that runs all night"
        )

    on_exhausted = raw.get("on_exhausted", "park")
    if on_exhausted not in ("park", "fail"):
        raise ConfigError(
            f"{source}: 'fleet.on_exhausted' must be 'park' or 'fail' "
            f"(got {on_exhausted!r})"
        )

    join = raw.get("join", "all")
    if not isinstance(join, str) or not _valid_join(join):
        raise ConfigError(
            f"{source}: 'fleet.join' must be 'all', 'first_pass', or "
            f"'quorum:<0-1>' (got {join!r})"
        )

    fallbacks = raw.get("worker_fallbacks", [])
    if not isinstance(fallbacks, list) or not all(
        isinstance(f, str) and f.strip() for f in fallbacks
    ):
        raise ConfigError(
            f"{source}: 'fleet.worker_fallbacks' must be a list of non-empty "
            "strings — a declared ladder, never one improvised at runtime"
        )

    child = raw.get("child", {})
    if not isinstance(child, dict):
        raise ConfigError(f"{source}: 'fleet.child' must be a mapping")
    unknown = sorted(set(child) - _CHILD_KEYS)
    if unknown:
        raise ConfigError(
            f"{source}: unknown keys under 'fleet.child': {', '.join(unknown)}"
        )

    retries = raw.get("retries", 1)
    if not _is_int(retries) or retries < 0:
        raise ConfigError(
            f"{source}: 'fleet.retries' must be an integer of at least 0 "
            f"(got {retries!r})"
        )

    worktree = raw.get("worktree", False)
    if not isinstance(worktree, bool):
        raise ConfigError(f"{source}: 'fleet.worktree' must be a boolean")

    return Fleet(
        worktree=worktree,
        deadline=_positive_int(raw, "deadline", 1, source, section="fleet"),
        concurrency=_positive_int(raw, "concurrency", 4, source, section="fleet"),
        progress_window=_positive_int(
            raw, "progress_window", 1200, source, section="fleet"
        ),
        retries=retries,
        on_exhausted=on_exhausted,
        join=join,
        child_max_iterations=(
            None
            if child.get("max_iterations") is None
            else _positive_int(
                child, "max_iterations", 1, source, section="fleet.child"
            )
        ),
        worker_fallbacks=tuple(fallbacks),
    )


def _valid_join(join: str) -> bool:
    if join in ("all", "first_pass"):
        return True
    if join.startswith("quorum:"):
        try:
            fraction = float(join.split(":", 1)[1])
        except ValueError:
            return False
        return 0 < fraction <= 1
    return False


def _parse_judge(raw: Any, source: str) -> Judge | None:
    """The `judge:` section, or None when the repo has not opted in."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: 'judge' must be a mapping")

    unknown = sorted(set(raw) - _JUDGE_KEYS)
    if unknown:
        raise ConfigError(f"{source}: unknown keys under 'judge': {', '.join(unknown)}")

    for key in ("endpoint", "model", "rubric"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(
                f"{source}: 'judge.{key}' must be a non-empty string — there is "
                "no default, because Wringer contacts the endpoint you wrote "
                "down and never one it guessed"
            )

    endpoint = raw["endpoint"].strip()
    _validate_endpoint(endpoint, source)

    api_key_env = raw.get("api_key_env")
    if api_key_env is not None and (
        not isinstance(api_key_env, str) or not api_key_env.strip()
    ):
        raise ConfigError(
            f"{source}: 'judge.api_key_env' must be the NAME of an environment "
            "variable, not a key — Wringer will not read a credential out of a "
            "config file"
        )

    return Judge(
        endpoint=endpoint,
        model=raw["model"].strip(),
        rubric=raw["rubric"].strip(),
        api_key_env=api_key_env,
        timeout=_positive_int(raw, "timeout", DEFAULT_JUDGE_TIMEOUT_SECONDS, source,
                              section="judge"),
        max_output_tokens=_positive_int(
            raw, "max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS, source,
            section="judge",
        ),
    )


def _validate_endpoint(endpoint: str, source: str) -> None:
    """Checked at parse time, so an unsafe endpoint can never reach a socket.

    https anywhere; http only to loopback. No userinfo, because credentials
    do not travel in URLs — and this URL is recorded in the bundle. No query
    string, for the same reason.
    """
    parsed = urllib.parse.urlsplit(endpoint)

    if parsed.scheme not in ("http", "https"):
        raise ConfigError(
            f"{source}: 'judge.endpoint' must be http:// or https:// "
            f"(got {parsed.scheme or 'no scheme'!r})"
        )
    if not parsed.hostname:
        raise ConfigError(f"{source}: 'judge.endpoint' has no host")
    if parsed.username or parsed.password:
        raise ConfigError(
            f"{source}: 'judge.endpoint' must not carry credentials — the "
            "endpoint is recorded in the verdict bundle. Use 'api_key_env'"
        )
    if parsed.query:
        raise ConfigError(
            f"{source}: 'judge.endpoint' must not carry a query string — it is "
            "recorded in the verdict bundle"
        )
    if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK:
        raise ConfigError(
            f"{source}: 'judge.endpoint' may only use plain http:// to "
            f"loopback (got host {parsed.hostname!r}) — a rubric and a diff "
            "are not things to send in the clear"
        )


def _parse_run(raw: Any, source: str) -> Run | None:
    """The `run:` section, or None when the repo has not opted into the loop."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: 'run' must be a mapping")

    unknown = sorted(set(raw) - _RUN_KEYS)
    if unknown:
        raise ConfigError(f"{source}: unknown keys under 'run': {', '.join(unknown)}")

    worker = _parse_worker(raw.get("worker"), source)

    return Run(
        worker=worker,
        max_iterations=_positive_int(
            raw, "max_iterations", DEFAULT_MAX_ITERATIONS, source
        ),
        worker_timeout=_positive_int(
            raw, "worker_timeout", DEFAULT_WORKER_TIMEOUT_SECONDS, source
        ),
        wall_clock=(
            None
            if raw.get("wall_clock") is None
            else _positive_int(raw, "wall_clock", 1, source)
        ),
    )


def _parse_worker(raw: Any, source: str) -> str | AcpWorker:
    """A shell string, or an `acp:` mapping. Never both, never neither."""
    if isinstance(raw, str):
        if not raw.strip():
            raise ConfigError(f"{source}: 'run.worker' must be a non-empty string")
        unknown = sorted(
            set(_PLACEHOLDER_PATTERN.findall(raw)) - set(WORKER_PLACEHOLDERS)
        )
        if unknown:
            raise ConfigError(
                f"{source}: 'run.worker' uses unknown placeholder(s) "
                f"{', '.join('{' + name + '}' for name in unknown)} — "
                f"available: {', '.join('{' + p + '}' for p in WORKER_PLACEHOLDERS)}"
            )
        return raw

    if isinstance(raw, dict):
        extra = sorted(set(raw) - {"acp"})
        if extra or "acp" not in raw:
            raise ConfigError(
                f"{source}: 'run.worker' as a mapping takes exactly one key, "
                f"'acp' (got {sorted(raw) or 'nothing'})"
            )
        return _parse_acp(raw["acp"], source)

    raise ConfigError(
        f"{source}: 'run.worker' must be a shell command string, or a mapping "
        "with an 'acp' key. There is no default: Wringer runs the worker you "
        "wrote down, never one it guessed"
    )


def _parse_acp(raw: Any, source: str) -> AcpWorker:
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: 'run.worker.acp' must be a mapping")

    unknown = sorted(set(raw) - _ACP_KEYS)
    if unknown:
        raise ConfigError(
            f"{source}: unknown keys under 'run.worker.acp': {', '.join(unknown)}"
        )

    command = raw.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ConfigError(
            f"{source}: 'run.worker.acp.command' must be a non-empty string — "
            "the agent binary that speaks ACP. Wringer never bundles or "
            "installs one"
        )

    args = raw.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ConfigError(f"{source}: 'run.worker.acp.args' must be a list of strings")

    names = raw.get("env_passthrough", [])
    if not isinstance(names, list) or not all(
        isinstance(n, str) and n.strip() for n in names
    ):
        raise ConfigError(
            f"{source}: 'run.worker.acp.env_passthrough' must be a list of "
            "environment variable NAMES — never values; Wringer will not read "
            "a credential out of a config file"
        )

    return AcpWorker(
        command=command.strip(),
        args=tuple(args),
        env_passthrough=tuple(names),
    )


def _positive_int(
    raw: dict, key: str, default: int, source: str, section: str = "run"
) -> int:
    value = raw.get(key, default)
    if not _is_int(value) or value < 1:
        raise ConfigError(
            f"{source}: '{section}.{key}' must be an integer of at least 1 "
            f"(got {value!r})"
        )
    return value


def substitute(command: str, **values: Any) -> str:
    """Fill a worker command's placeholders.

    Only the declared names, and only `{name}` — `${VAR}` is the shell's, and
    an unknown placeholder was already rejected at parse time.
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return str(values[name]) if name in values else match.group(0)

    return _PLACEHOLDER_PATTERN.sub(replace, command)


def _validate_evidence(evidence: dict[str, Any], source: str) -> None:
    """Shape-check the `evidence:` section.

    `redact` is consumed now (Day 4), so a typo in it must be an error rather
    than silently switching redaction off — the one failure mode where a
    quiet default is dangerous. `include` is not consumed yet, but its shape
    is still checked: "unknown keys are errors" and "a malformed known key is
    fine" cannot both be the rule.
    """
    unknown = sorted(set(evidence) - _EVIDENCE_KEYS)
    if unknown:
        raise ConfigError(
            f"{source}: unknown keys under 'evidence': {', '.join(unknown)}"
        )

    include = evidence.get("include")
    if include is not None and (
        not isinstance(include, list)
        or not all(isinstance(item, str) and item for item in include)
    ):
        raise ConfigError(
            f"{source}: 'evidence.include' must be a list of non-empty "
            "strings, e.g. 'git.diff' — v0.1 captures what it can regardless, "
            "but a typo here must not look like valid configuration"
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
