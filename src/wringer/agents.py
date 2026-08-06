"""The ACP agents `wring start` knows how to name — and **the only place in
`src/` a coding-agent vendor string appears**.

AGENTS.md rule 5, and `forge.py`'s precedent exactly: that module holds every
forge vendor string so `cli.py` can say "the forge" and never "GitHub". This
module is its sibling, so the wizard can say "the agent" and never a product
name. Swapping which agents Wringer offers is then a table edit rather than a
grep, and `tests/test_start.py` fails if a name escapes.

**Nothing here runs.** The install command is *data the human is shown*, never
an argv — SPEC_START_V0.md §3c-i, confirmed by Marc on 2026-08-06, against two
documents that said `wring start` would install with consent. Three reasons,
the first decisive: the program already promises the opposite in shipped
strings a user can read (`config.py`'s "Wringer never bundles or installs one",
`acp.py`'s "Wringer never installs an agent"). Falsifying two live error
messages to save one paste is the wrong trade. This module deliberately
imports nothing that can start a process, so the guarantee is structural
rather than a promise not to; a test asserts that.

**On the values below.** `command` is the binary detection looks for on
`PATH`; `package` is what installs it; `key_env` is the variable that agent
expects its credential in. They are pinned, in one table, for the reason rule 5
exists: an agent that changes its invocation makes this a one-line diff. The
`claude-code` entry's binary is the one `SPEC_ACP_V0.md`'s own config example
already names.

`args` is empty for both entries and that is a deliberate refusal, not an
omission. Wringer runs the agent you wrote down, never one it guessed, and a
launch that wrote a flag the agent did not want would produce a `.wringer.yaml`
that parses and does not work — the worst failure shape this wizard has. The
stanza is printed before it is written, so an agent needing a flag is one the
human adds to a file they have already been shown.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from wringer import config


@dataclass(frozen=True)
class Agent:
    """One agent Wringer can propose as an ACP worker."""

    id: str
    command: str
    package: str
    key_env: str
    args: tuple[str, ...] = ()

    @property
    def install(self) -> str:
        """The exact command a human runs to get this agent.

        Printed, never executed. Running someone's package manager is a
        larger, less reversible power than anything else in this slice, and
        `SETUP.md` already makes installing a runtime a stop condition for the
        agent doing setup — it would be strange for the tool to take a power
        its own runbook denies.
        """
        return f"npm install -g {self.package}"


# Two entries, both of which speak ACP natively or through a published bridge.
# The list is short on purpose: an agent Wringer names is one it is claiming
# can be detected and driven, and a table padded with unverified entries would
# be a guess wearing a mapping layer.
AGENTS: tuple[Agent, ...] = (
    Agent(
        id="claude-code",
        command="claude-code-acp",
        package="@zed-industries/claude-code-acp",
        key_env="ANTHROPIC_API_KEY",
    ),
    Agent(
        id="gemini",
        command="gemini",
        package="@google/gemini-cli",
        key_env="GEMINI_API_KEY",
        args=("--experimental-acp",),
    ),
)


def known() -> tuple[str, ...]:
    """Every id `--agent` accepts, in the order they are offered."""
    return tuple(agent.id for agent in AGENTS)


def find(agent_id: str) -> Agent | None:
    return next((agent for agent in AGENTS if agent.id == agent_id), None)


def located(agent: Agent) -> str | None:
    """Where this agent's binary is, or None.

    `shutil.which` and nothing cleverer (§3c). Present on `PATH` = offered;
    absent = named, with its install command printed. Wringer does not look in
    a package manager's cache, ask a registry, or run the binary to see if it
    answers — every one of those is a guess or a network call, and this step
    is neither.
    """
    return shutil.which(agent.command)


def survey() -> list[tuple[Agent, str | None]]:
    """Every agent and where it is, for the step that shows the human both."""
    return [(agent, located(agent)) for agent in AGENTS]


def worker(agent: Agent) -> config.AcpWorker:
    """The stanza `wring start` proposes for this agent.

    `command`, `args` and `env_passthrough` — the only three keys that exist
    under `run.worker.acp` (`config.py`'s `_ACP_KEYS`). `env_passthrough`
    carries the NAME of the variable holding the credential and never its
    value; `config.py` refuses a value there, and this is the caller that
    makes that refusal load-bearing rather than decorative.
    """
    return config.AcpWorker(
        command=agent.command,
        args=agent.args,
        env_passthrough=(agent.key_env,),
    )
