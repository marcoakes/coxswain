"""wring — command-line entry points.

Exit codes are contract (SPEC_VERIFY_V0.md):
0 = all required gates passed · 1 = a required gate failed ·
2 = config or environment error · 3 = unsafe dirty state / refused
precondition · 4 = interrupted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

from wringer import (
    __version__,
    acquire,
    agents,
    config,
    deliver,
    detect,
    doctor,
    evidence,
    fleet,
    forge,
    gates,
    git,
    judge,
    loop,
    redact,
    rubric,
    spec,
    start,
    summary,
    verify,
)

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_CONFIG = 2
EXIT_REFUSED = 3
EXIT_INTERRUPTED = 4
# `wring judge` only. "The evidence says no" and "nothing competent looked at
# the evidence" are different claims, so 5 must never collapse into 1.
EXIT_NEEDS_HUMAN = 5

# How much of a failing gate's logs to put on the console. The whole log is
# in the bundle; this is just enough to see what broke without opening it.
LOG_TAIL_LINES = 20

# `wring explain` is meant to be compact; a 400-file diff is a scroll, not a
# diagnosis.
EXPLAIN_FILE_LIMIT = 20


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wring",
        description=(
            "One command that proves whether this change is mergeable, "
            "and leaves behind evidence a human or agent can inspect."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"wring {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_start = subparsers.add_parser(
        "start",
        help="the guided launch: preflight, config, and your first build",
    )
    where_from = parser_start.add_mutually_exclusive_group()
    where_from.add_argument(
        "--repo",
        metavar="DIR",
        help="the repository to launch in; defaults to the current directory",
    )
    where_from.add_argument(
        "--clone",
        metavar="URL",
        help=(
            "clone this repository into the workspace and STOP. A fresh clone "
            "is untrusted input and its '.wringer.yaml' is code, so no gate of "
            "its runs in the same invocation — read it, then run wring start "
            "again inside it"
        ),
    )
    parser_start.add_argument(
        "--workspace",
        metavar="DIR",
        help=f"where `wring get` clones. Written to {config.CONFIG_FILENAME}; "
             "there is no default",
    )
    parser_start.add_argument(
        "--accept-gates",
        action="store_true",
        help=(
            "confirm the gates this repo declares, or the ones detection "
            "proposes, without being asked. There is deliberately no flag for "
            "the API key: a key on a command line is a process listing"
        ),
    )
    agent_choice = parser_start.add_mutually_exclusive_group()
    agent_choice.add_argument(
        "--agent",
        metavar="ID",
        help=(
            "the agent that drives the repair loop, by id "
            f"({', '.join(agents.known())}). It must already be installed: "
            "Wringer names what to install and never installs it"
        ),
    )
    agent_choice.add_argument(
        "--no-agent",
        action="store_true",
        help=(
            "configure no worker at all. The gates still run; the loop has "
            "nothing to drive it, and no 'run:' section is written"
        ),
    )
    parser_start.set_defaults(func=cmd_start)

    parser_init = subparsers.add_parser(
        "init", help=f"write a commented {config.CONFIG_FILENAME} template"
    )
    parser_init.set_defaults(func=cmd_init)

    parser_verify = subparsers.add_parser(
        "verify", help="run the declared gates and write an evidence bundle"
    )
    parser_verify.add_argument(
        "--gate",
        metavar="ID",
        help="run only this gate instead of every declared gate",
    )
    parser_verify.add_argument(
        "--output",
        metavar="DIR",
        help="write the bundle here instead of a new .wringer/runs/<run_id>/",
    )
    parser_verify.add_argument(
        "--prove",
        action="store_true",
        help=(
            "after the gates pass, run them again against the pre-change tree "
            "in a scratch worktree. A gate that passes on both proved nothing "
            "about this change. Roughly doubles gate time. There is no "
            "--no-prove: a flag may tighten what '.wringer.yaml' declares, "
            "never loosen it"
        ),
    )
    parser_verify.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human report",
    )
    parser_verify.set_defaults(func=cmd_verify)

    parser_run = subparsers.add_parser(
        "run",
        help="loop: verify, hand the failure to your worker, verify again",
    )
    parser_run.add_argument(
        "--max-iterations",
        type=int,
        metavar="N",
        help="override the config's max_iterations for this run",
    )
    parser_run.add_argument(
        "--worker-timeout",
        type=int,
        metavar="SECONDS",
        help="override the config's worker_timeout for this run",
    )
    parser_run.add_argument(
        "--wall-clock",
        type=int,
        metavar="SECONDS",
        help="stop the whole loop after this long, whatever the iteration count",
    )
    parser_run.add_argument(
        "--prove",
        action="store_true",
        help=(
            "prove the gates can fail on every iteration. Declare "
            "'run.prove: true' in '.wringer.yaml' to make it permanent — and "
            "note there is no --no-prove, deliberately: the audited party does "
            "not get to choose whether the audit runs"
        ),
    )
    parser_run.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human report",
    )
    parser_run.set_defaults(func=cmd_run)

    parser_fleet = subparsers.add_parser(
        "fleet",
        help="run many repair loops under supervision",
    )
    parser_fleet.add_argument(
        "tasks",
        metavar="TASKS_JSONL",
        help="one JSON object per line: {\"id\", \"brief\", \"dir\"}",
    )
    parser_fleet.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human report",
    )
    parser_fleet.set_defaults(func=cmd_fleet)

    parser_resume = subparsers.add_parser(
        "resume",
        help="continue a loop that was killed before it finished",
    )
    parser_resume.add_argument(
        "loop",
        nargs="?",
        metavar="LOOP_DIR",
        help="a loop directory; defaults to the most recent unfinished one",
    )
    parser_resume.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human report",
    )
    parser_resume.set_defaults(func=cmd_resume)

    parser_judge = subparsers.add_parser(
        "judge",
        help="judge a finished evidence bundle against a rubric",
    )
    parser_judge.add_argument(
        "run",
        nargs="?",
        metavar="RUN_DIR",
        help="a run directory; defaults to the most recent one",
    )
    parser_judge.add_argument(
        "--send",
        action="store_true",
        help=(
            "actually contact the endpoint — the only path in Wringer that "
            "opens a network connection. Without it, the request is built and "
            "written but nothing is sent."
        ),
    )
    parser_judge.add_argument(
        "--print-request",
        action="store_true",
        help="write the exact would-be request body to stdout and exit",
    )
    parser_judge.add_argument(
        "--rubric",
        metavar="PATH",
        help="override the configured rubric for this judgment",
    )
    parser_judge.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human report",
    )
    parser_judge.set_defaults(func=cmd_judge)

    parser_spec = subparsers.add_parser(
        "spec",
        help="draft a build spec from a PRD — a file you approve by hand",
    )
    parser_spec.add_argument(
        "prd",
        metavar="PRD",
        help="a plain-language requirements document inside this repository",
    )
    parser_spec.add_argument(
        "--send",
        action="store_true",
        help=(
            "actually contact the endpoint. Without it, the request is built "
            "and written but nothing is sent and nothing is drafted."
        ),
    )
    parser_spec.add_argument(
        "--print-request",
        action="store_true",
        help="write the exact would-be request body to stdout and exit",
    )
    parser_spec.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human report",
    )
    parser_spec.set_defaults(func=cmd_spec)

    parser_plan = subparsers.add_parser(
        "plan",
        help=f"compile an approved {spec.SPEC_FILENAME} into fleet tasks",
    )
    parser_plan.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human report",
    )
    parser_plan.set_defaults(func=cmd_plan)

    parser_get = subparsers.add_parser(
        "get", help="clone a repository into the workspace"
    )
    parser_get.add_argument("url", metavar="URL", help="the repository to clone")
    parser_get.add_argument(
        "--into", metavar="DIR", help="clone here instead of into the workspace"
    )
    parser_get.set_defaults(func=cmd_get)

    parser_issue = subparsers.add_parser(
        "issue", help="write a forge issue to a local markdown file"
    )
    parser_issue.add_argument(
        "issue", metavar="ISSUE", help="an issue number or its URL"
    )
    parser_issue.set_defaults(func=cmd_issue)

    parser_deliver = subparsers.add_parser(
        "deliver",
        help="turn a verified change into a branch and a merge request",
    )
    parser_deliver.add_argument(
        "run",
        nargs="?",
        metavar="RUN_DIR",
        help="the run that verified it; defaults to the most recent",
    )
    parser_deliver.add_argument(
        "--send",
        action="store_true",
        help=(
            "actually create the branch, commit, push and open the MR — the "
            "only path in Wringer that writes git history. Without it, the "
            "patch, message, branch and MR body are written and nothing runs."
        ),
    )
    parser_deliver.add_argument(
        "--task", metavar="ID", help="fill {task} in the branch template"
    )
    parser_deliver.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human report",
    )
    parser_deliver.set_defaults(func=cmd_deliver)

    parser_doctor = subparsers.add_parser(
        "doctor",
        help="check this machine's preconditions — one line per check",
    )
    parser_doctor.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human report",
    )
    parser_doctor.set_defaults(func=cmd_doctor)

    parser_attest = subparsers.add_parser(
        "attest",
        help="assemble the provenance claim for a verified change — offline",
    )
    parser_attest.add_argument(
        "anchor",
        nargs="?",
        metavar="RUN_OR_DELIVERY_DIR",
        help="what to attest; defaults to the newest delivery, else the "
             "newest run",
    )
    parser_attest.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human report",
    )
    parser_attest.set_defaults(func=cmd_attest)

    parser_audit = subparsers.add_parser(
        "audit",
        help="check an attestation offline — no config, no network, no LLM",
    )
    parser_audit.add_argument(
        "attestation",
        metavar="ATTESTATION_FILE",
        help="the attestation.json to check",
    )
    parser_audit.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human report",
    )
    parser_audit.set_defaults(func=cmd_audit)

    parser_explain = subparsers.add_parser(
        "explain",
        help="diagnose the latest (or a named) run — no LLM involved",
    )
    parser_explain.add_argument(
        "run",
        nargs="?",
        metavar="RUN_DIR",
        help="a run directory; defaults to the most recent one",
    )
    parser_explain.set_defaults(func=cmd_explain)

    return parser


# The steps of the guided launch, in SPEC_START_V0.md §1's order. Printed as
# `[n/7]` so a reader can see how far in they are — a wizard that gives no
# sense of length is one people abandon halfway.
START_STEPS = 7


def _start_step(number: int, title: str) -> None:
    print(f"\n[{number}/{START_STEPS}] {title}")


def cmd_start(args: argparse.Namespace) -> int:
    """The guided launch (SPEC_START_V0.md).

    Calls the other commands' machinery and reimplements none of it: doctor's
    checks, detection's proposal, and — from S5 — verify, the loop and attest.
    """
    here = Path(args.repo).expanduser() if args.repo else Path.cwd()
    if not here.is_dir():
        print(
            f"wring start: no directory at {args.repo} — --repo names a "
            "repository that is already on disk",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    # The one place this command reads from a human, built once and passed
    # down. Everything below asks through it or does not ask at all, which is
    # what makes the whole wizard runnable with no terminal.
    asking = start.prompts()

    print("wring start — set this up and start your first build")

    # [1/7] preflight. Diagnose, never repair: `wring doctor`'s own checks,
    # inline, so a launch does not send a new user to a second command first.
    _start_step(1, "preflight")
    checks = doctor.run_checks(here)
    _report_preflight(checks)
    # On the statuses, NOT on doctor's exit code. WARN and SKIP both count as
    # passed there, and outside a repo the repo checks SKIP — so an empty
    # directory reports "machine ready" and exits 0. Branching on that alone
    # is how a wizard walks into a machine that cannot run a gate.
    if any(check.status == doctor.FAIL for check in checks):
        print(
            "\nwring start: fix the ✗ lines above and run this again. This "
            "command diagnoses and never repairs.",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    # [2/7] workspace. No default, ever — Wringer does not choose where to put
    # someone's code. It is written when given and asked for when needed.
    _start_step(2, "workspace")
    if args.workspace:
        print(f"  {args.workspace}")
    else:
        print(
            "  not declared — nothing here needs one yet. `wring get` will "
            "ask\n  for one before it clones."
        )

    # [3/7] repo in. EITHER a directory already on disk — the human put it
    # there, and every other Wringer command already trusts that — OR a clone,
    # which records what it fetched and stops before any gate (§3e).
    _start_step(3, "repo")
    if args.clone:
        return _start_clone(here, args.clone, args.workspace)

    root = git.find_root(here.resolve())
    if not git.is_repo(root):
        print(
            f"\nwring start: {root} is not a git repository — the launch ends "
            "on a\nreceipt, and a receipt records which commit was proven. Run "
            "'git init'\nhere first, or point --repo at your repo.",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    print(start.fit(f"  {root}"))

    # [4/7] gates. Detection's proposal, or what the repo already declares —
    # shown before it is written, because `.wringer.yaml` is code.
    _start_step(4, "gates")
    refused = _start_gates(root, args.accept_gates, asking)
    if refused is not None:
        return refused

    # [5/7] agent. Detected, never assumed — and never installed (§3c-i).
    _start_step(5, "agent")
    worker, refused = _start_agent(args.agent, args.no_agent, asking)
    if refused is not None:
        return refused

    try:
        emission = start.emit(root, workspace=args.workspace, worker=worker)
    except start.StartError as exc:
        _fail("start", exc)
        return EXIT_CONFIG
    except start.Refused as exc:
        _fail("start", exc)
        return EXIT_REFUSED
    emission.write()

    # [6/7] key. Typed here, held in memory, written nowhere (§3a). The config
    # is already on disk by this point and that is deliberate: the launch is
    # idempotent, so stopping here leaves a valid repo and a re-runnable
    # command rather than a half-configured one.
    _start_step(6, "key")
    key_name, refused = _start_key(worker, asking)
    if refused is not None:
        return refused

    _report_start(emission, key_name)

    # [7/7] the first build: verify, then the loop if there is something to
    # repair, then the receipt.
    _start_step(7, "first build")
    return _start_build(root, worker)


def _start_gates(
    root: Path, accepted: bool, asking: start.Prompts
) -> int | None:
    """Show what will be declared and run, or refuse for want of consent."""
    path = root / config.CONFIG_FILENAME
    if path.is_file():
        try:
            cfg = config.load(path)
        except config.ConfigError as exc:
            _fail("start", exc)
            return EXIT_CONFIG
        print(f"  {path.name} already declares: {start.gate_summary(cfg)}")
        if detect.is_untouched_template(cfg.gates):
            print(f"\n  ! {detect.TEMPLATE_WARNING}")
    else:
        detection = detect.detect(root)
        if detection.found:
            print(
                f"  detected from {', '.join(detection.sources)}: "
                + ", ".join(candidate.id for candidate in detection.candidates)
            )
        else:
            print(
                "  nothing here declares a command Wringer recognises, so the\n"
                "  config will carry the placeholder gate — which proves "
                "nothing\n  about your code until you replace it."
            )

    if accepted:
        return None

    if asking.interactive():
        # §3b, row 1: a TTY and a missing answer means ask for exactly that
        # one. Declining is not an error to explain away — it is a person
        # reading a list of commands and saying no, which is the entire
        # reason the list is printed first.
        if asking.confirm("Run these commands to verify this repo?"):
            return None
        print(
            "\nwring start: not accepted, so nothing was written and nothing "
            "ran.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    # Exit 2 naming the answer, per §3b. Not a default, and not a guess:
    # these commands run through a shell with the user's privileges, and a
    # wizard that assumed consent to that would be the worst thing here.
    print(
        "\nwring start: this repository's gates are commands that will run on"
        "\nthis machine, so nothing is written or run until you say so. Re-run"
        "\nwith --accept-gates once you have read the list above.",
        file=sys.stderr,
    )
    return EXIT_CONFIG


def _start_agent(
    chosen: str | None, declined: bool, asking: start.Prompts
) -> tuple[config.AcpWorker | None, int | None]:
    """Detect, propose, and hand back the stanza — or refuse.

    Every agent name printed here comes out of `agents.py`. This function
    contains no product name, which is what makes swapping the offered set a
    table edit rather than a grep (AGENTS.md rule 5).
    """
    if declined:
        print(
            "  none — no 'run:' section will be written.\n"
            "  The gates still run; there is just nothing configured to fix "
            "them for you."
        )
        return None, None

    if chosen is not None:
        agent = agents.find(chosen)
        if agent is None:
            print(
                f"wring start: no agent with id {chosen!r}. Known: "
                f"{', '.join(agents.known())}",
                file=sys.stderr,
            )
            return None, EXIT_CONFIG
        where = agents.located(agent)
        if where is None:
            # SPEC_ACP_V0 rule 3 fixes the code, and §3c-i fixes the posture:
            # named, with the exact command printed for the human to run.
            # Wringer runs neither it nor anything else here.
            print(f"  {agent.id} is not on PATH.")
            print(
                f"\nwring start: install it yourself, then run this again:\n\n"
                f"  {agent.install}\n\n"
                "Wringer never installs an agent. Running your package manager "
                "is a\nlarger power than launching a build, and this command "
                "was not granted it.",
                file=sys.stderr,
            )
            return None, EXIT_CONFIG

        worker = agents.worker(agent)
        print(start.fit(f"  ✓ {agent.id:<14}{where}"))
        # Consent IS the written stanza (§3c), so the human sees the exact
        # YAML — from the same function that writes it, not a second renderer.
        print("\n  This is what will be added:\n")
        for line in start.worker_stanza(worker).rstrip("\n").splitlines():
            print(f"    {line}")
        return worker, None

    installed = []
    for agent, where in agents.survey():
        if where is not None:
            print(start.fit(f"  ✓ {agent.id:<14}{where}"))
            installed.append(agent.id)
        else:
            print(start.fit(f"  - {agent.id:<14}not installed:  {agent.install}"))

    if asking.interactive() and installed:
        picked = asking.choose(
            f"Which one? ({', '.join(installed)}, or "
            f"{start.NONE_ANSWER})",
            installed,
        )
        if picked == start.NONE_ANSWER:
            return _start_agent(None, True, asking)
        if picked is not None:
            return _start_agent(picked, False, asking)

    print(
        "\nwring start: choose one with --agent <id>, or --no-agent to "
        "configure\nnone. There is no default: Wringer drives the agent you "
        "wrote down,\nnever one it guessed.",
        file=sys.stderr,
    )
    return None, EXIT_CONFIG


def _report_preflight(checks: list[doctor.Check]) -> None:
    """`wring doctor`'s checks, rendered for a wizard.

    Its machinery, not its layout (§7 forbids reimplementing the command, not
    reformatting it). Two differences, both deliberate:

    - **Bounded to the console width.** doctor's own report is unbounded, and
      its fix lines run to 220 columns — fine in a terminal you are reading,
      impossible on the demo canvas.
    - **Only a ✗ gets its fix printed.** A ✗ stops the launch, so its fix is
      the next thing the reader needs. A ! does not, and eight wrapped
      paragraphs of optional advice before anything happens is how a wizard
      teaches people to skim past the line that mattered. `wring doctor` is
      one command away and this says so.
    """
    for check in checks:
        mark = doctor.MARKS[check.status]
        print(start.fit(f"{mark} {check.name:<22}{check.detail}"))
        if check.status == doctor.FAIL and check.fix:
            print(start.wrap(f"{'':<24}→ {check.fix}", indent=" " * 24))
    if any(check.status == doctor.WARN for check in checks):
        print("  (the ! lines are optional extras — `wring doctor` explains them)")


def _start_clone(here: Path, url: str, workspace: str | None) -> int:
    """Clone, record where it came from, and **stop** (§3e, ruling 5).

    This is the most important refusal in the command. `SPEC_GET_V0.md:85-87`
    is binding for the machinery being reused — *"Runs nothing it cloned. No
    gate, no hook, no install step — a fresh clone is untrusted input, and
    SECURITY.md's `.wringer.yaml`-is-code warning is exactly why"* — and
    `AGENTS.md` forbids widening that without a spec change and a SECURITY.md
    update. A guided launch that cloned and then executed would be the most
    dangerous command in the program, aimed at the least technical user it
    has. The second invocation costs one line of typing and is the entire
    safety property.
    """
    root = git.find_root(here.resolve())
    try:
        cfg_workspace = (
            config.load(root / config.CONFIG_FILENAME).workspace
            if (root / config.CONFIG_FILENAME).is_file()
            else None
        )
    except config.ConfigError as exc:
        _fail("start", exc)
        return EXIT_CONFIG

    if workspace is None and cfg_workspace is None:
        # Config precedes clone (§4): `wring get` requires `workspace:` before
        # it will clone, and there is no default because Wringer does not
        # choose where to put someone's code.
        print(
            "\nwring start: --clone needs somewhere to put it. There is no "
            "default:\nWringer does not choose where your code lives. Add "
            "--workspace <DIR>.",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    # The config is written FIRST, so the workspace this clone lands in is
    # recorded before anything is fetched — and so `wring get` works here
    # afterwards without asking again.
    try:
        emission = start.emit(root, workspace=workspace)
    except start.StartError as exc:
        _fail("start", exc)
        return EXIT_CONFIG
    except start.Refused as exc:
        _fail("start", exc)
        return EXIT_REFUSED
    emission.write()

    try:
        acquire.check_url(url)
        target = acquire.destination(
            url, (root / (workspace or cfg_workspace or ".")).resolve(), None
        )
        acquired = acquire.clone(url, target)
        manifest = acquire.record(root, acquired)
    except acquire.AcquireError as exc:
        _fail("start", exc)
        return EXIT_CONFIG

    print(start.fit(f"  cloned {acquired.origin}"))
    print(start.fit(f"  into   {acquired.directory}"))
    if acquired.head_sha:
        print(
            start.fit(
                f"  at     {acquired.head_sha[:12]} on "
                f"{acquired.default_branch or '?'}"
            )
        )
    print(f"\nProvenance: {_relative(manifest, root)}")
    print(
        "\nNothing in it has been run, and this launch stops here.\n"
        f"A repository's gates are code: {config.CONFIG_FILENAME} says what "
        "commands\nWringer will execute with your privileges, so read that "
        "file before\nanything runs it.\n\n"
        f"When you have:\n  cd {acquired.directory}\n  wring start"
    )
    # Exit 3, not 0: a precondition this command will not run untrusted code
    # for (§2). The launch did not complete — it deliberately did not.
    return EXIT_REFUSED


def _start_key(
    worker: config.AcpWorker | None, asking: start.Prompts
) -> tuple[str | None, int | None]:
    """The credential: prompted, held in memory, written nowhere (§3a).

    Never a flag. `--key <value>` is a process listing, which §3a forbids in
    the same breath as the ledger and the bundle.
    """
    if worker is None or not worker.env_passthrough:
        print(
            "  no agent is configured, so there is no credential to hold.\n"
            "  Nothing else in Wringer ever asks for one."
        )
        return None, None

    name = worker.env_passthrough[0]
    if start.key_in_environment(name):
        # The name is the answer; the value is never printed, prefixed or
        # otherwise hinted at — `wring doctor` has held that line since it
        # shipped and this step holds the same one.
        print(f"  {name} is already set here (value not shown).")
        return name, None

    # CHECKED BEFORE `getpass` IS EVER CALLED, and that ordering is the safety
    # property (§3a-i): `getpass` opens /dev/tty rather than stdin, so a
    # closed stdin would not stop it — it would block on a terminal nobody is
    # watching. stdin, not stdout: a pipeline, a CI job and the demo recorder
    # all present a non-interactive stdin while stdout may still be a tty.
    if not asking.interactive():
        print(
            f"\nwring start: {name} is not set, and this is not a terminal — "
            "so there is\nnothing to prompt. Set it and run this again:\n\n"
            f"  {start.PERSIST_HINT.format(name=name)}\n\n"
            "There is deliberately no --key flag: a value on a command line is "
            "a\nprocess listing anyone on the machine can read.",
            file=sys.stderr,
        )
        return None, EXIT_CONFIG

    print(
        f"  {name} is not set. Type it here — it is not echoed, not written\n"
        "  into this repository, and not stored anywhere."
    )
    try:
        value = asking.secret(name)
    except EOFError:
        print("\nwring start: nothing was typed", file=sys.stderr)
        return None, EXIT_CONFIG
    if not value.strip():
        print(
            f"\nwring start: {name} was left empty. Run this again when you "
            "have it.",
            file=sys.stderr,
        )
        return None, EXIT_CONFIG

    start.hold(name, value)
    print("  Held in memory for this launch.")
    return name, None


def _start_build(root: Path, worker: config.AcpWorker | None) -> int:
    """Verify, repair if there is something to repair, then the receipt.

    The loop runs only when the gates said no. `wring run` exists to hand a
    failure to a worker; starting an agent against a green tree would spend
    someone's money to be told nothing, and §1's "verify, then the loop" reads
    as a sequence rather than an obligation to run all of it.
    """
    try:
        cfg = config.load(root / config.CONFIG_FILENAME)
        planned = verify.plan(cfg, None)
    except config.ConfigError as exc:
        _fail("start", exc)
        return EXIT_CONFIG

    try:
        outcome = verify.run(root, cfg, planned, on_gate=_report_gate)
    except evidence.EvidenceError as exc:
        _fail("start", exc)
        return EXIT_CONFIG

    if outcome.interrupted is not None:
        return EXIT_INTERRUPTED

    if outcome.failed_gate is not None and worker is not None:
        outcome = _start_repair(root, cfg, outcome)
        if outcome is None:
            return EXIT_CONFIG

    if outcome.failed_gate is not None:
        _report_run(
            outcome.bundle, root, outcome.results, outcome.failed_gate,
            outcome.status, template_only=outcome.template_only,
        )
        _diagnose_failure(outcome)
        if worker is None:
            print(
                "\nNo agent is configured, so nothing tried to fix it. Read "
                "the log\nabove, or configure one and run: wring run"
            )
        return EXIT_GATE_FAILED

    if outcome.template_only:
        # §4 — the blank template's only gate runs `true`. A launch that ended
        # "your first build passed" over it would be a vacuous green produced
        # by the onboarding flow, which is the failure this project exists to
        # prevent. No receipt is attempted: `attest` would happily certify it
        # (its vacuity hook only fires on a `--prove` verdict), and a receipt
        # over a placeholder is a cryptographic-sounding wrapper around
        # nothing.
        #
        # Exit 3 rather than 0: the launch did not complete its last step, and
        # a placeholder gate is a precondition this command will not guess
        # past. An agent reading only the exit code is exactly the reader who
        # would over-read a 0 here.
        print(
            f"\n! {detect.TEMPLATE_WARNING}\n"
            f"\nEvidence written to:\n{_bundle_path(outcome.bundle, root)}/"
            f"\n\nNo receipt was written: there is nothing yet to attest to."
            f"\n\nNext:\n  edit {config.CONFIG_FILENAME} — replace the "
            "placeholder gate with the\n  commands that prove your change is "
            "mergeable, then: wring start"
        )
        return EXIT_REFUSED

    print("\n✓ every required gate passed.")
    print(f"Evidence: {_bundle_path(outcome.bundle, root)}/")
    return _start_receipt(root, outcome.bundle.directory)


def _start_repair(
    root: Path, cfg: config.Config, failed: verify.Outcome
) -> verify.Outcome | None:
    """Hand the failure to the configured agent, then report what came back."""
    print("\nThe gates said no. Handing it to the agent you configured.")
    try:
        loop_outcome = loop.run(
            root,
            cfg,
            on_iteration=_report_iteration,
            on_gate=_report_gate,
            on_worker=_report_worker,
        )
    except evidence.EvidenceError as exc:
        _fail("start", exc)
        return None
    _report_loop(loop_outcome, root)
    # The loop's own final verification is the one that counts; without it the
    # receipt would be written over the bundle from BEFORE the repair.
    return loop_outcome.final if loop_outcome.final is not None else failed


def _diagnose_failure(outcome: verify.Outcome) -> None:
    """Name the failure shape a new user hits first.

    `pytest: command not found` is the documented first failure
    (QUICKSTART.md:36-41) and it is Wringer working correctly — it ran what
    the repo declared. Showing a bare shell error to someone who installed the
    tool ten seconds ago teaches them the tool is broken.

    **It wears two faces, and a real launch on the maintainer's Mac hit the
    second one.** A gate of `pytest -q` with no pytest is exit 127 and
    `command not found`; a gate of `python3 -m pytest` with no pytest is exit
    1 and `No module named pytest` — same cause, same fix, entirely different
    text. Both are named here.
    """
    failure = next(
        (r for r in outcome.results if r.gate.id == outcome.failed_gate), None
    )
    if failure is None:
        return
    stderr = ""
    try:
        stderr = failure.stderr_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass

    if failure.exit_code == 127 or "command not found" in stderr:
        missing = "ran a command that is not on PATH"
    elif "No module named" in stderr:
        missing = "needs a package that is not installed in the environment"
    else:
        return

    print(
        f"\n! `{failure.gate.id}` {missing}. That is Wringer working "
        f"correctly:\n  it ran what {config.CONFIG_FILENAME} declares. Install "
        "this project's own\n  dependencies into the environment you run wring "
        f"from, or edit\n  {config.CONFIG_FILENAME}."
    )


def _start_receipt(root: Path, anchor: Path) -> int:
    """The last thing a new user sees: a receipt a stranger could check."""
    from wringer import attest

    try:
        built = attest.build(root, anchor)
    except (attest.Refused, attest.AttestError) as exc:
        # §2 — a bundle that cannot be attested is 3, not 1. `1` means the
        # gates answered no; conflating them would make the exit code lie
        # about which half failed.
        print(f"wring start: the receipt could not be made: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    bundle = attest.Bundle.create(root, built.payload["attestation_id"])
    written = bundle.write(built.payload)
    print(f"\nReceipt:  {_relative(written, root)}")
    print("\n" + start.wrap(f"! {attest.UNSIGNED_LIMIT}", indent="  "))
    print(
        f"\nCheck it yourself — offline, no config, no network:\n"
        f"  wring audit {_relative(written, root)}"
    )
    return EXIT_OK


def _report_start(emission: start.Emission, key_name: str | None) -> None:
    name = emission.path.name
    if emission.created:
        print(f"\nWrote {name}.")
    elif emission.added:
        print(f"\nAdded to {name}: {', '.join(emission.added)}.")
    else:
        print(f"\n{name} already says everything this launch would have added.")
    for section in emission.already:
        print(f"  '{section}' was already declared — left exactly as it was.")

    if key_name is not None:
        # §3a — it is never persisted. The command is printed and neither it
        # nor anything else is run: storing a credential is a larger power
        # than launching a build, and this slice was not granted it. A
        # keychain is a declared non-goal (§7) until a field report shows
        # people losing the key between sessions.
        print(
            "\n"
            + start.wrap(
                f"Wringer stored nothing. {name} records the NAME "
                f"{key_name}, never a value. To have it set next time, "
                "run this yourself:"
            )
            + f"\n\n  {start.PERSIST_HINT.format(name=key_name)}"
        )



def cmd_init(args: argparse.Namespace) -> int:
    root = Path.cwd()
    target = root / config.CONFIG_FILENAME
    if target.exists():
        print(
            f"wring init: refusing to overwrite existing {target.name}",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    detection = detect.detect(root)
    target.write_text(detect.template(detection), encoding="utf-8")

    if detection.found:
        gates = ", ".join(candidate.id for candidate in detection.candidates)
        print(
            f"Wrote {target.name} from {', '.join(detection.sources)} — "
            f"gates: {gates}"
        )
        print("Check they are the commands you want proven, then: wring verify")
    elif detection.seen:
        # Name what is on disk. Saying "nothing to detect here" to someone
        # looking at their own pyproject.toml reads as a broken detector
        # rather than as a deliberate refusal to guess (R2-07).
        print(
            f"Wrote {target.name} — found {', '.join(detection.seen)}, but "
            "nothing in it declares a command Wringer recognises, so it is a "
            "template rather than a guess."
        )
        print(
            "Replace the placeholder gate with the commands that prove your "
            "change is mergeable, then run: wring verify"
        )
    else:
        print(
            f"Wrote {target.name} — nothing here to read commands from, so it "
            "is a template rather than a guess."
        )
        print(
            "Replace the placeholder gate with the commands that prove your "
            "change is mergeable, then run: wring verify"
        )

    # Only where there is a git repo to ignore things in. Writing a
    # .gitignore into a plain directory is litter, and it implies a repo that
    # is not there.
    if git.is_repo(root):
        ignored = _ignore_runs(root)
        if ignored is not None:
            print(f"Added {evidence.RUNS_DIRNAME.parts[0]}/ to {ignored}")
    else:
        # Say it here rather than let `wring verify` refuse with exit 2 two
        # lines after this command recommended it. The runbook dead-ended.
        print(
            f"\nNote: {root} is not a git repository, so `wring verify` will "
            "refuse —\nverification records which commit and which changes "
            "were proven. Run\n'git init' first, or run wring from inside "
            "your repo."
        )
    return EXIT_OK


def _ignore_runs(root: Path) -> str | None:
    """Keep evidence out of git.

    Bundles hold raw gate output, so a repo that commits them is one
    `git push` away from publishing whatever a gate printed. Returns the
    file written, or None if it was already handled.
    """
    entry = f"{evidence.RUNS_DIRNAME.parts[0]}/"
    gitignore = root / ".gitignore"

    if gitignore.is_file():
        existing = gitignore.read_text(encoding="utf-8")
        if entry in existing.split():
            return None
        separator = "" if existing.endswith("\n") or not existing else "\n"
        gitignore.write_text(
            f"{existing}{separator}\n# Wringer evidence stays local\n{entry}\n",
            encoding="utf-8",
        )
        return ".gitignore"

    gitignore.write_text(
        f"# Wringer evidence stays local\n{entry}\n", encoding="utf-8"
    )
    return ".gitignore"


def cmd_verify(args: argparse.Namespace) -> int:
    root = git.find_root(Path.cwd())

    refused = _refuse_unverifiable(root, "verify")
    if refused is not None:
        return refused

    try:
        cfg = config.load(root / config.CONFIG_FILENAME)
        planned = verify.plan(cfg, args.gate)
    except config.ConfigError as exc:
        _fail("verify", exc)
        return EXIT_CONFIG

    try:
        outcome = verify.run(
            root,
            cfg,
            planned,
            output=args.output,
            # Printed as each gate finishes, so a long run reports as it
            # happens; --json wants one object and nothing else.
            on_gate=None if args.json else _report_gate,
            # The flag TIGHTENS; `run.prove: true` in the config is read
            # inside `verify.wants_prove` and nothing here can turn it off.
            prove=args.prove,
        )
    except evidence.EvidenceError as exc:
        _fail("verify", exc)
        return EXIT_CONFIG

    if args.json:
        _report_json(
            outcome.bundle,
            root,
            outcome.failed_gate,
            outcome.status,
            template_only=outcome.template_only,
        )
    else:
        _report_run(
            outcome.bundle,
            root,
            outcome.results,
            outcome.failed_gate,
            outcome.status,
            template_only=outcome.template_only,
            vacuity_result=outcome.vacuity,
        )

    if outcome.interrupted is not None:
        return EXIT_INTERRUPTED
    return EXIT_GATE_FAILED if outcome.failed_gate is not None else EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    """Loop until the evidence says stop (SPEC_RUN_V0.md)."""
    root = git.find_root(Path.cwd())

    refused = _refuse_unverifiable(root, "run")
    if refused is not None:
        return refused

    try:
        cfg = config.load(root / config.CONFIG_FILENAME)
        verify.plan(cfg, None)  # fail on a broken gate list before any work
    except config.ConfigError as exc:
        _fail("run", exc)
        return EXIT_CONFIG

    if cfg.run is None:
        print(
            f"wring run: no 'run:' section in {config.CONFIG_FILENAME} — "
            "the loop needs to know what edits the code. Add one:\n\n"
            "  run:\n"
            '    worker: claude -p "$(cat {brief})"\n\n'
            "There is no default worker: Wringer runs the command you wrote "
            "down, never one it guessed.",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    if args.max_iterations is not None and args.max_iterations < 1:
        print(
            f"wring run: --max-iterations must be at least 1 "
            f"(got {args.max_iterations})",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    quiet = args.json
    try:
        outcome = loop.run(
            root,
            cfg,
            max_iterations=args.max_iterations,
            worker_timeout=args.worker_timeout,
            wall_clock=args.wall_clock,
            on_iteration=None if quiet else _report_iteration,
            on_gate=None if quiet else _report_gate,
            on_worker=None if quiet else _report_worker,
            prove=args.prove,
        )
    except evidence.EvidenceError as exc:
        _fail("run", exc)
        return EXIT_CONFIG

    if args.json:
        print(
            json.dumps(
                {
                    "status": outcome.status,
                    "reason": outcome.reason,
                    "iterations": outcome.iterations,
                    "loop_dir": _relative(outcome.directory, root),
                    "final": (
                        verify.json_summary(outcome.final, root)
                        if outcome.final is not None
                        else None
                    ),
                }
            )
        )
    else:
        _report_loop(outcome, root)

    if outcome.status == "interrupted":
        return EXIT_INTERRUPTED
    return EXIT_OK if outcome.converged else EXIT_GATE_FAILED


def _report_iteration(iteration: int, budget: int) -> None:
    print(f"\niteration {iteration}/{budget}", flush=True)


def _report_worker(result: gates.GateResult) -> None:
    """One line for the worker's turn, shaped like a gate's so the two read
    as one transcript."""
    note = "timed out" if result.timed_out else f"exit {result.exit_code}"
    label = "→ worker"
    padding = " " * max(1, 21 - len(label))
    print(f"{label}{padding}{_duration(result.duration_ms)}  ({note})", flush=True)


def _duration(duration_ms: int) -> str:
    """Seconds for a gate, minutes once a worker has been thinking a while."""
    seconds = duration_ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}m {seconds:02d}s"


_LOOP_ENDINGS = {
    "converged": "Converged in {n} iteration{s}.",
    "max_iterations": "Stopped after {n} iteration{s} — the budget ran out and "
    "the gates still fail.",
    "no_progress": "Stopped after {n} iteration{s} — the worker changed nothing, "
    "so the gates would say the same again.",
    "interrupted": "Interrupted after {n} iteration{s}.",
}


def _report_loop(outcome: loop.Outcome, root: Path) -> None:
    ending = _LOOP_ENDINGS.get(outcome.reason, "Stopped after {n} iteration{s}.")
    print(
        "\n"
        + ending.format(n=outcome.iterations, s="" if outcome.iterations == 1 else "s")
    )
    print(f"Loop evidence: {_relative(outcome.directory, root)}/")
    if not outcome.converged and outcome.final is not None:
        print(f"Last verification: {verify.bundle_path(outcome.final.bundle, root)}/")


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnose, never repair. Exit 1 on any blocking problem, so a setup
    script can branch on it without parsing prose."""
    root = git.find_root(Path.cwd())
    checks = doctor.run_checks(root)
    print(doctor.as_json(checks) if args.json else doctor.report(checks))
    return EXIT_OK if all(check.passed for check in checks) else EXIT_GATE_FAILED


def cmd_fleet(args: argparse.Namespace) -> int:
    """Run many loops under supervision (SPEC_SUPERVISION_V0.md §S3)."""
    root = git.find_root(Path.cwd())

    refused = _refuse_unverifiable(root, "fleet")
    if refused is not None:
        return refused

    try:
        cfg = config.load(root / config.CONFIG_FILENAME)
    except config.ConfigError as exc:
        _fail("fleet", exc)
        return EXIT_CONFIG

    if cfg.fleet is None:
        print(
            f"wring fleet: no 'fleet:' section in {config.CONFIG_FILENAME} — "
            "it must at least declare a deadline:\n\n"
            "  fleet:\n"
            "    concurrency: 4\n"
            "    deadline: 21600",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    try:
        tasks = fleet.load_tasks(Path(args.tasks))
    except fleet.FleetError as exc:
        _fail("fleet", exc)
        return EXIT_CONFIG

    if not args.json:
        print(
            f"{len(tasks)} task{'' if len(tasks) == 1 else 's'}, "
            f"{cfg.fleet.concurrency} at a time."
        )

    try:
        outcome = fleet.run(root, cfg, tasks)
    except fleet.FleetError as exc:
        _fail("fleet", exc)
        return EXIT_CONFIG

    if args.json:
        print(
            json.dumps(
                {
                    "succeeded": outcome.succeeded,
                    "failed": outcome.failed,
                    "parked": outcome.parked,
                    "join_satisfied": outcome.join_satisfied,
                    "fleet_dir": _relative(outcome.directory, root),
                }
            )
        )
    else:
        print(
            f"\n{outcome.succeeded} succeeded, {outcome.failed} failed, "
            f"{outcome.parked} parked."
        )
        if outcome.parked:
            print(
                "Parked work kept its evidence in the fleet bundle. There is\n"
                "no fleet resume yet — re-run 'wring fleet' with a task file\n"
                "holding the parked ids to try them again."
            )
        print(f"Fleet evidence: {_relative(outcome.directory, root)}/")

    return EXIT_OK if outcome.join_satisfied else EXIT_GATE_FAILED


def cmd_resume(args: argparse.Namespace) -> int:
    """Continue a loop whose ledger stopped without `loop.finished`.

    A loop that ended — converged, stopped, or interrupted by a human — is
    over. Only one that was *killed* leaves a ledger that simply stops, and
    its completed iterations are facts worth continuing from.
    """
    root = git.find_root(Path.cwd())

    refused = _refuse_unverifiable(root, "resume")
    if refused is not None:
        return refused

    try:
        cfg = config.load(root / config.CONFIG_FILENAME)
        verify.plan(cfg, None)
    except config.ConfigError as exc:
        _fail("resume", exc)
        return EXIT_CONFIG

    if cfg.run is None:
        print(
            f"wring resume: no 'run:' section in {config.CONFIG_FILENAME}",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    if args.loop is not None:
        loop_dir = Path(args.loop)
        if not loop_dir.is_dir():
            print(f"wring resume: no loop directory at {args.loop}", file=sys.stderr)
            return EXIT_CONFIG
    else:
        found = loop.latest_loop(root / loop.LOOPS_DIRNAME)
        if found is None:
            print(
                f"wring resume: no loops under "
                f"{(root / loop.LOOPS_DIRNAME).as_posix()}",
                file=sys.stderr,
            )
            return EXIT_CONFIG
        loop_dir = found

    try:
        resumable = loop.inspect_for_resume(loop_dir)
    except evidence.EvidenceError as exc:
        _fail("resume", exc)
        return EXIT_CONFIG

    if resumable is None:
        print(
            f"wring resume: {_relative(loop_dir, root)} finished — there is "
            "nothing to resume. A loop that converged, stopped or was "
            "interrupted by hand is over; start a new one with 'wring run'.",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    quiet = args.json
    if not quiet:
        print(
            f"Resuming {_relative(loop_dir, root)} — "
            f"{resumable.iterations_done} iteration"
            f"{'' if resumable.iterations_done == 1 else 's'} already done."
        )

    try:
        outcome = loop.run(
            root,
            cfg,
            on_iteration=None if quiet else _report_iteration,
            on_gate=None if quiet else _report_gate,
            on_worker=None if quiet else _report_worker,
            resuming=resumable,
        )
    except evidence.EvidenceError as exc:
        _fail("resume", exc)
        return EXIT_CONFIG

    if args.json:
        print(
            json.dumps(
                {
                    "status": outcome.status,
                    "reason": outcome.reason,
                    "iterations": outcome.iterations,
                    "resumed_from": resumable.iterations_done,
                    "loop_dir": _relative(outcome.directory, root),
                    "final": (
                        verify.json_summary(outcome.final, root)
                        if outcome.final is not None
                        else None
                    ),
                }
            )
        )
    else:
        _report_loop(outcome, root)

    if outcome.status == "interrupted":
        return EXIT_INTERRUPTED
    return EXIT_OK if outcome.converged else EXIT_GATE_FAILED


def cmd_judge(args: argparse.Namespace) -> int:
    """Judge a finished bundle against a rubric (SPEC_JUDGE_V0.md)."""
    import time

    root = git.find_root(Path.cwd())

    try:
        cfg = config.load(root / config.CONFIG_FILENAME)
    except config.ConfigError as exc:
        _fail("judge", exc)
        return EXIT_CONFIG

    if cfg.judge is None:
        print(
            f"wring judge: no 'judge:' section in {config.CONFIG_FILENAME} — "
            "there is no default endpoint and never will be, so a repo that "
            "has not opted in cannot reach a network at all. Add one:\n\n"
            "  judge:\n"
            "    endpoint: http://127.0.0.1:11434/v1/chat/completions\n"
            "    model: qwen2.5-coder:7b\n"
            "    rubric: rubric.yaml",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    run_dir = _judge_target(args.run, root)
    if run_dir is None:
        return EXIT_CONFIG

    try:
        loaded = rubric.load(Path(args.rubric or cfg.judge.rubric), root)
    except rubric.RubricError as exc:
        _fail("judge", exc)
        return EXIT_CONFIG

    redactor = redact.Redactor.from_config(
        cfg.evidence, extra_names=config.declared_secret_names(cfg)
    )

    try:
        passed, failed_gate = judge.gates_passed(run_dir)
    except judge.JudgeError as exc:
        _fail("judge", exc)
        return EXIT_CONFIG

    if not passed:
        print(
            f"wring judge: refusing to judge {_relative(run_dir, root)} — its "
            f"gates did not pass"
            + (f" (`{failed_gate}` failed)" if failed_gate else "")
            + ". A judge has nothing to add when the deterministic gates "
            "already said no.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    if cfg.judge.api_key_env and os.environ.get(cfg.judge.api_key_env) is None:
        print(
            f"wring judge: 'judge.api_key_env' names {cfg.judge.api_key_env}, "
            "which is not set in this environment",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    try:
        packet = judge.build_packet(run_dir, loaded)
    except judge.JudgeError as exc:
        _fail("judge", exc)
        return EXIT_CONFIG

    request = judge.render_request(
        packet, cfg.judge.model, cfg.judge.max_output_tokens
    )

    if args.print_request:
        print(json.dumps(request, indent=2))
        return EXIT_OK

    started = time.monotonic()
    try:
        bundle = judge.Bundle.create(root / judge.VERDICTS_DIRNAME, redactor=redactor)
    except judge.JudgeError as exc:
        _fail("judge", exc)
        return EXIT_CONFIG

    # Written before any transport is consulted: what would leave the machine
    # is auditable rather than asserted, and --send is this same path
    # continuing one step further.
    bundle.write_request(request)

    mode = "live" if args.send else "dry_run"
    verdict = judge.Verdict(None)
    unaskable = judge.nothing_to_ask(loaded) if args.send else None
    if unaskable is not None:
        # Every criterion needs a human. There is no question to send, so no
        # socket opens: --send is permission to ask, not an instruction to.
        verdict = unaskable
    elif args.send:
        try:
            body = judge.send(
                request,
                cfg.judge.endpoint,
                cfg.judge.timeout,
                os.environ.get(cfg.judge.api_key_env or ""),
            )
        except judge.TransportFailed as exc:
            # Unreachable is not a verdict. Record it and say so.
            verdict = judge.Verdict(
                judge.NEEDS_HUMAN, note=f"the endpoint could not be used: {exc}"
            )
            body = None
        else:
            bundle.write_response(body)
            verdict = judge.parse_response(body, loaded)

    duration_ms = int((time.monotonic() - started) * 1000)
    shown = _relative(run_dir, root)
    bundle.write_verdict(
        mode, shown, loaded, cfg.judge.endpoint, cfg.judge.model, verdict, duration_ms
    )
    bundle.write_summary(mode, shown, loaded, verdict)
    # LAST, so it covers verdict.json, request.json and the summary — the
    # three files `wring attest` names when it makes a `judged_by` clause.
    bundle.write_digests()

    if args.json:
        print(
            json.dumps(
                {
                    "mode": mode,
                    "verdict": verdict.verdict,
                    "note": verdict.note,
                    "evidence_dir": shown,
                    "verdict_dir": _relative(bundle.directory, root),
                }
            )
        )
    else:
        _report_judge(mode, verdict, bundle, root, loaded)

    return _judge_exit(mode, verdict)


def _judge_target(named: str | None, root: Path) -> Path | None:
    if named is not None:
        run_dir = Path(named)
        if not run_dir.is_dir():
            print(f"wring judge: no run directory at {named}", file=sys.stderr)
            return None
        return run_dir
    found = evidence.latest_run(root / evidence.RUNS_DIRNAME)
    if found is None:
        print(
            f"wring judge: no runs under "
            f"{(root / evidence.RUNS_DIRNAME).as_posix()} — run 'wring verify' "
            "first; a judge reads a finished bundle",
            file=sys.stderr,
        )
        return None
    return found


def _judge_exit(mode: str, verdict: judge.Verdict) -> int:
    if mode == "dry_run":
        return EXIT_OK
    if verdict.verdict == judge.PASS:
        return EXIT_OK
    if verdict.verdict == judge.FAIL:
        return EXIT_GATE_FAILED
    return EXIT_NEEDS_HUMAN


def _report_judge(
    mode: str, verdict: judge.Verdict, bundle: judge.Bundle, root: Path, loaded
) -> None:
    if mode == "dry_run":
        print("dry run — the request was built and written; nothing was sent.")
    human = {c.id for c in loaded.criteria if c.human}
    for row in verdict.criteria:
        mark = {True: "✓", False: "✗", None: "?"}[row["met"]]
        tag = "" if row["required"] else "  (optional)"
        if row["id"] in human:
            tag += "  (needs a human)"
        print(f"{mark} {row['id']}{tag}")
    if verdict.verdict is not None:
        print(f"\nVerdict: {verdict.verdict}")
    if verdict.note:
        print(f"  {verdict.note}")
    print(f"\nJudgment written to:\n{_relative(bundle.directory, root)}/")


def cmd_spec(args: argparse.Namespace) -> int:
    """Draft a build spec from a PRD (SPEC_INTENT_V0.md).

    Dry run by default, like the judge and for the judge's reason: the exact
    bytes are on disk before any socket opens. Nothing here touches git and
    nothing here runs a gate — this command reads one file and writes another.
    """
    root = git.find_root(Path.cwd())

    try:
        cfg = config.load(root / config.CONFIG_FILENAME)
    except config.ConfigError as exc:
        _fail("spec", exc)
        return EXIT_CONFIG

    if cfg.judge is None:
        print(
            f"wring spec: no 'judge:' section in {config.CONFIG_FILENAME} — "
            "drafting reuses the judge's endpoint, model and key rules, so "
            "that one network config is the only one. Add it:\n\n"
            "  judge:\n"
            "    endpoint: http://127.0.0.1:11434/v1/chat/completions\n"
            "    model: qwen2.5-coder:7b\n"
            f"    rubric: {spec.RUBRIC_FILENAME}",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    # Built BEFORE the PRD is read, because the PRD is scrubbed on the way in
    # rather than on the way to disk: a request.json saying [REDACTED] beside a
    # socket that carried the real value is an audit record that lies.
    redactor = redact.Redactor.from_config(
        cfg.evidence, extra_names=config.declared_secret_names(cfg)
    )

    try:
        prd = spec.read_prd(Path(args.prd), root, redactor)
    except spec.SpecError as exc:
        _fail("spec", exc)
        return EXIT_CONFIG

    target = root / spec.SPEC_FILENAME
    if args.send and target.exists():
        print(
            f"wring spec: refusing to overwrite {spec.SPEC_FILENAME} — it may "
            "already carry your approval and your answers. Move or delete it "
            "if you want a fresh draft.",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    request = spec.render_request(
        prd, cfg.judge.model, cfg.judge.max_output_tokens, cfg.gates
    )
    if args.print_request:
        print(json.dumps(request, indent=2))
        return EXIT_OK

    # Checked only when a request will really be sent: a dry run needs no
    # credential, and refusing one for a key it never uses would be theatre.
    if (
        args.send
        and cfg.judge.api_key_env
        and os.environ.get(cfg.judge.api_key_env) is None
    ):
        print(
            f"wring spec: 'judge.api_key_env' names {cfg.judge.api_key_env}, "
            "which is not set in this environment",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    try:
        bundle = spec.Bundle.create(root / spec.SPECS_DIRNAME, redactor=redactor)
    except spec.SpecError as exc:
        _fail("spec", exc)
        return EXIT_CONFIG

    bundle.write_request(request)

    mode = "live" if args.send else "dry_run"
    drafted: spec.Spec | None = None
    if args.send:
        try:
            body = judge.send(
                request,
                cfg.judge.endpoint,
                cfg.judge.timeout,
                os.environ.get(cfg.judge.api_key_env or ""),
            )
        except judge.TransportFailed as exc:
            bundle.write_summary(
                mode, args.prd, cfg.judge.endpoint, cfg.judge.model, None
            )
            print(
                f"wring spec: the endpoint could not be used: {exc}. The "
                f"request is on disk at "
                f"{_relative(bundle.directory, root)}/{spec.REQUEST_FILENAME}.",
                file=sys.stderr,
            )
            return EXIT_CONFIG

        bundle.write_response(body)
        try:
            drafted = spec.parse_response(body, prd)
        except spec.SpecError as exc:
            bundle.write_summary(
                mode, args.prd, cfg.judge.endpoint, cfg.judge.model, None
            )
            print(
                f"wring spec: {exc}. The reply is on disk at "
                f"{_relative(bundle.directory, root)}/{spec.RESPONSE_FILENAME}.",
                file=sys.stderr,
            )
            return EXIT_CONFIG

        # Written only now, once the whole document has been through the same
        # parsers the file itself will face: a half-written spec is worse than
        # no spec, because a half-written one gets approved.
        target.write_text(spec.render(drafted), encoding="utf-8")

    bundle.write_summary(
        mode, args.prd, cfg.judge.endpoint, cfg.judge.model, drafted
    )

    if args.json:
        print(
            json.dumps(
                {
                    "mode": mode,
                    "spec": spec.SPEC_FILENAME if drafted else None,
                    "approved": drafted.approved if drafted else None,
                    "criteria": len(drafted.criteria) if drafted else 0,
                    "gates": len(drafted.gates) if drafted else 0,
                    "tasks": len(drafted.tasks) if drafted else 0,
                    "open_questions": len(drafted.questions) if drafted else 0,
                    "spec_dir": _relative(bundle.directory, root),
                }
            )
        )
    else:
        _report_spec(drafted, bundle, root)
    return EXIT_OK


def _report_spec(
    drafted: spec.Spec | None, bundle: spec.Bundle, root: Path
) -> None:
    if drafted is None:
        print("dry run — the request was built and written; nothing was sent.")
        print(f"\nRequest written to:\n{_relative(bundle.directory, root)}/")
        print("\nWhen you are ready:\n  wring spec <PRD> --send")
        return

    unresolved = sum(1 for q in drafted.questions if q.required and not q.answered)
    scored_by_hand = sum(1 for c in drafted.criteria if c.human)
    print(f"Drafted {spec.SPEC_FILENAME} — {drafted.title}")
    print(
        f"  {len(drafted.criteria)} criteria"
        + (f" ({scored_by_hand} need a human)" if scored_by_hand else "")
        + f" · {len(drafted.gates)} proposed gates · {len(drafted.tasks)} tasks"
    )
    if unresolved:
        print(
            f"  {unresolved} required question"
            f"{'' if unresolved == 1 else 's'} it could not answer for you"
        )
    print("\n  approved: false   ← nothing runs until you change this by hand")
    print(f"\nNext:\n  read {spec.SPEC_FILENAME}, answer its open questions,")
    print("  set 'approved: true', then run: wring plan")
    print(f"\nDraft evidence: {_relative(bundle.directory, root)}/")


def cmd_plan(args: argparse.Namespace) -> int:
    """Compile an approved spec into work (SPEC_INTENT_V0.md §4).

    Runs nothing. Writes `tasks.jsonl`, the brief files and the rubric, prints
    the gate change it would like `.wringer.yaml` to have, and stops.
    """
    root = git.find_root(Path.cwd())

    try:
        loaded = spec.load(root / spec.SPEC_FILENAME)
    except spec.SpecError as exc:
        _fail("plan", exc)
        return EXIT_CONFIG

    if not loaded.approved:
        print(
            f"wring plan: {spec.SPEC_FILENAME} says 'approved: false', so "
            "nothing was written.\n\nRead the file, then set 'approved: true' "
            "in it by hand. There is deliberately no --yes: the whole point of "
            "this step is that a person read what is about to be built.",
            file=sys.stderr,
        )
        return EXIT_GATE_FAILED

    if loaded.unanswered:
        print(
            f"wring plan: {len(loaded.unanswered)} required question"
            f"{'' if len(loaded.unanswered) == 1 else 's'} in "
            f"{spec.SPEC_FILENAME} "
            f"{'is' if len(loaded.unanswered) == 1 else 'are'} unanswered:",
            file=sys.stderr,
        )
        for question in loaded.unanswered:
            print(f"  - {question.id}: {question.question}", file=sys.stderr)
        print(
            "\nWrite an 'answer:' under each, or delete the question if it no "
            "longer matters. Building on an assumption is how the wrong thing "
            "gets built confidently.",
            file=sys.stderr,
        )
        return EXIT_GATE_FAILED

    # Everything is checked before anything is written: a plan that half-ran
    # leaves a tasks file describing briefs that do not exist.
    try:
        writes, brief_paths = _plan_writes(loaded, root)
    except spec.SpecError as exc:
        _fail("plan", exc)
        return EXIT_CONFIG

    for path, body in writes:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    existing = root / config.CONFIG_FILENAME
    diff, fresh, already = spec.gate_diff(
        existing.read_text(encoding="utf-8") if existing.is_file() else "", loaded
    )

    briefs = [_relative(path, root) for path in brief_paths]
    if args.json:
        print(
            json.dumps(
                {
                    "tasks_file": spec.TASKS_FILENAME,
                    "tasks": [t.id for t in loaded.tasks],
                    "briefs": briefs,
                    "rubric": spec.RUBRIC_FILENAME,
                    "gates_proposed": list(fresh),
                    "gates_already_declared": list(already),
                    "gate_diff": diff,
                }
            )
        )
    else:
        _report_plan(loaded, briefs, diff, fresh, already)
    return EXIT_OK


def _plan_writes(
    loaded: spec.Spec, root: Path
) -> tuple[list[tuple[Path, str]], list[Path]]:
    """Every file `wring plan` would write, or an error and no files at all.

    Returns (all writes, the brief paths among them). Nothing reaches the disk
    until every check has passed: a plan that half-ran leaves a task file
    describing briefs that do not exist.
    """
    rubric_text = spec.render_rubric(loaded)
    # Prove it is a rubric before writing it, with the judge's own parser.
    # "No translation layer" is a claim, and this is the check behind it.
    spec.validate_rubric_text(rubric_text)

    # Our own two fixed paths still get resolved: either could be a symlink
    # pointing out of the repository, and write_text follows one.
    tasks_path = spec.resolve_inside(root, spec.TASKS_FILENAME, spec.TASKS_FILENAME)
    rubric_path = spec.resolve_inside(
        root, spec.RUBRIC_FILENAME, spec.RUBRIC_FILENAME
    )
    if not spec.tasks_file_is_generated(tasks_path):
        raise spec.SpecError(
            f"{spec.TASKS_FILENAME} exists and is not a task file — refusing to "
            "overwrite it"
        )
    if not spec.rubric_is_generated(rubric_path):
        raise spec.SpecError(
            f"{spec.RUBRIC_FILENAME} exists and `wring plan` did not write it — "
            "refusing to overwrite it. It is the document that decides whether "
            "the work is accepted, so replacing a hand-written one is not a "
            "thing to do quietly; move it, or point 'judge.rubric:' elsewhere"
        )

    writes: list[tuple[Path, str]] = [
        (tasks_path, spec.render_tasks(loaded)),
        (rubric_path, rubric_text),
    ]
    brief_paths: list[Path] = []
    claimed: dict[Path, str] = {}
    for task in loaded.tasks:
        where = f"{spec.SPEC_FILENAME}: task '{task.id}'"
        directory = spec.resolve_inside(root, task.dir, f"{where}: 'dir'")
        if not directory.is_dir():
            raise spec.SpecError(
                f"{where} names dir '{task.dir}', which does not exist — the "
                "fleet would park it"
            )
        brief_path = spec.check_writable(root, task.brief, f"{where}: 'brief'")
        if brief_path in claimed:
            # Two tasks, one file. The second write wins, the fleet dispatches
            # both tasks against it, and one objective is simply gone.
            raise spec.SpecError(
                f"{where} names the same brief as task '{claimed[brief_path]}' "
                f"({task.brief}) — one of the two objectives would be lost, and "
                "both tasks would be sent the other's"
            )
        claimed[brief_path] = task.id
        if not spec.brief_is_generated(brief_path):
            raise spec.SpecError(
                f"{where} would overwrite {task.brief}, which `wring plan` did "
                "not write — rename the brief in the spec"
            )
        writes.append((brief_path, spec.render_brief(loaded, task)))
        brief_paths.append(brief_path)
    return writes, brief_paths


def _report_plan(
    loaded: spec.Spec,
    briefs: list[str],
    diff: str,
    fresh: tuple[str, ...],
    already: tuple[str, ...],
) -> None:
    count = len(loaded.tasks)
    print(f"Wrote {spec.TASKS_FILENAME} — {count} task{'' if count == 1 else 's'}.")
    print(f"Wrote {len(briefs)} brief{'' if len(briefs) == 1 else 's'}: "
          f"{', '.join(briefs)}")
    scored_by_hand = sum(1 for c in loaded.criteria if c.human)
    print(
        f"Wrote {spec.RUBRIC_FILENAME} — {len(loaded.criteria)} criteria"
        + (f" ({scored_by_hand} need a human)" if scored_by_hand else "")
        + "."
    )

    if diff:
        print(
            f"\nProposed gates ({', '.join(fresh)}). Wringer does not install "
            "these — changing what 'verified' means is yours to do:\n"
        )
        print(diff.rstrip())
    elif fresh:
        # No diff, but there IS something to propose: the config's gate list is
        # not a block-style one this can safely add to. Saying so beats a diff
        # that looks additive and is not.
        print(
            f"\nProposed gates ({', '.join(fresh)}), as text rather than a diff: "
            f"{config.CONFIG_FILENAME}'s gate list is not in the block style "
            "this can add to, and a patch that appended a second 'gates:' key "
            "would delete the gates you already have. Add these by hand:\n"
        )
        for gate in loaded.gates:
            if gate.id in fresh:
                print(f"  - id: {gate.id}\n    run: {gate.run}")
    if already:
        print(
            f"\nAlready declared, so not proposed: {', '.join(already)}. Check "
            f"they run what the spec meant."
        )
    if not diff and not fresh and not already:
        print(f"\nNo gates proposed; {config.CONFIG_FILENAME} is unchanged.")

    print(
        f"\nNext:\n  point 'judge.rubric:' at {spec.RUBRIC_FILENAME}\n"
        f"  wring fleet {spec.TASKS_FILENAME}"
    )


def cmd_get(args: argparse.Namespace) -> int:
    """Clone a repository into the workspace (SPEC_GET_V0.md §3)."""
    root = git.find_root(Path.cwd())

    try:
        cfg = config.load(root / config.CONFIG_FILENAME)
    except config.ConfigError as exc:
        _fail("get", exc)
        return EXIT_CONFIG

    if cfg.workspace is None and not args.into:
        print(
            f"wring get: no 'workspace:' in {config.CONFIG_FILENAME} and no "
            "--into — there is no default, because Wringer does not choose "
            "where to put your code. Add one:\n\n  workspace: ../work",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    try:
        acquire.check_url(args.url)
        target = acquire.destination(
            args.url, (root / (cfg.workspace or ".")).resolve(), args.into
        )
        acquired = acquire.clone(args.url, target)
        manifest = acquire.record(root, acquired)
    except acquire.AcquireError as exc:
        _fail("get", exc)
        return EXIT_CONFIG

    print(f"Cloned {acquired.origin}\n  into {acquired.directory}")
    if acquired.head_sha:
        print(f"  at   {acquired.head_sha[:12]} on {acquired.default_branch or '?'}")
    print(f"\nProvenance: {_relative(manifest, root)}")
    print(
        "\nNothing in it has been run. Read its .wringer.yaml before you "
        "verify — a repo's gates are code."
    )
    return EXIT_OK


def cmd_issue(args: argparse.Namespace) -> int:
    """Write a forge issue to a local file (SPEC_GET_V0.md §4)."""
    root = git.find_root(Path.cwd())

    try:
        cfg = config.load(root / config.CONFIG_FILENAME)
    except config.ConfigError as exc:
        _fail("issue", exc)
        return EXIT_CONFIG

    if cfg.forge is None:
        print(
            f"wring issue: no 'forge:' section in {config.CONFIG_FILENAME} — "
            "there is no default host and never will be. Add one:\n\n"
            "  forge:\n"
            "    kind: github\n"
            "    endpoint: https://api.github.com\n"
            "    repo: owner/name\n"
            "    token_env: FORGE_TOKEN",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    if cfg.forge.token_env and os.environ.get(cfg.forge.token_env) is None:
        print(
            f"wring issue: 'forge.token_env' names {cfg.forge.token_env}, which "
            "is not set in this environment",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    redactor = redact.Redactor.from_config(
        cfg.evidence, extra_names=config.declared_secret_names(cfg)
    )
    settings = cfg.deliver or config.Deliver()

    try:
        number = forge.issue_number(args.issue, cfg.forge)
        fetched = forge.fetch_issue(
            cfg.forge, number, os.environ.get(cfg.forge.token_env or "")
        )
    except forge.ForgeError as exc:
        _fail("issue", exc)
        return EXIT_CONFIG

    target = root / settings.issues_dir / f"{fetched.number}.md"
    if target.exists():
        try:
            existing = target.read_text(encoding="utf-8", errors="replace")[:300]
        except OSError:
            existing = ""
        if forge.ISSUE_MARKER not in existing:
            print(
                f"wring issue: {_relative(target, root)} exists and `wring "
                "issue` did not write it — refusing to overwrite it",
                file=sys.stderr,
            )
            return EXIT_CONFIG

    # Scrubbed at the write, like the PRD: the file, any later request and the
    # wire all carry the same text.
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        redactor.scrub(forge.render_issue(fetched)), encoding="utf-8"
    )

    print(f"Wrote {_relative(target, root)} — {fetched.title}")
    print(
        "\nIt is a copy of something a stranger wrote: read it, then\n"
        f"  wring spec {_relative(target, root)}"
    )
    return EXIT_OK


def cmd_deliver(args: argparse.Namespace) -> int:
    """A verified change becomes a branch and an MR (SPEC_GET_V0.md §5).

    The only command in Wringer that writes git history, and it does so only
    when a human types `--send` — the amended law 6, in one function.
    """
    root = git.find_root(Path.cwd())

    try:
        cfg = config.load(root / config.CONFIG_FILENAME)
    except config.ConfigError as exc:
        _fail("deliver", exc)
        return EXIT_CONFIG

    if cfg.deliver is None:
        print(
            f"wring deliver: no 'deliver:' section in {config.CONFIG_FILENAME} "
            "— its absence is what makes writing git history unreachable. "
            "Add one:\n\n"
            "  deliver:\n"
            '    branch: "wringer/{run}"\n'
            "    remote: origin",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    run_dir = _delivery_target(args.run, root)
    if run_dir is None:
        return EXIT_CONFIG

    # Every name this config declares, not just the forge's. A credential an
    # AGENT was handed — `run.worker.acp.env_passthrough` — reached the
    # delivery patch in cleartext while `verify`'s own bundle had scrubbed it.
    # Every name this config declares, not just the forge's. Two things need
    # it: a credential an AGENT was handed (run.worker.acp.env_passthrough)
    # reached the delivery patch in cleartext, AND the tree-match check below
    # compares this redactor's output against verify's — so a narrower list
    # here makes the two disagree and refuses a tree that never moved.
    # Every name this config declares, not just the forge's. Two things need
    # it: a credential an AGENT was handed (run.worker.acp.env_passthrough)
    # reached the delivery patch in cleartext, AND the tree-match check below
    # compares this redactor's output against verify's — so a narrower list
    # here makes the two disagree and refuses a tree that never moved.
    redactor = redact.Redactor.from_config(
        cfg.evidence, extra_names=config.declared_secret_names(cfg)
    )

    try:
        planned = deliver.plan(
            root, cfg, run_dir, run_dir.name, args.task, redactor=redactor
        )
    except deliver.Refused as exc:
        _fail("deliver", exc)
        return exc.exit_code
    except deliver.DeliverError as exc:
        _fail("deliver", exc)
        return EXIT_CONFIG

    try:
        bundle = deliver.Bundle.create(
            root / deliver.DELIVERIES_DIRNAME, redactor=redactor
        )
    except deliver.DeliverError as exc:
        _fail("deliver", exc)
        return EXIT_CONFIG

    # Written before anything runs: what would happen is auditable rather than
    # asserted, and --send is this same path continuing one step further.
    bundle.write_plan(planned)

    mode = "live" if args.send else "dry_run"
    delivered: dict[str, object] = {"branch": None, "commit": None,
                                    "pushed": False, "merge_request": None}
    if args.send:
        try:
            delivered.update(deliver.send(root, bundle, planned))
        except deliver.DeliverError as exc:
            bundle.event("delivery.failed", why=str(exc))
            bundle.write_manifest(mode, planned, delivered)
            # A failed delivery is still a bundle somebody may audit, and a
            # bundle without digests is one `wring audit` has to refuse. The
            # failure path gets the same treatment as the happy one.
            bundle.write_digests()
            _fail("deliver", exc)
            return EXIT_CONFIG

        opened = _open_merge_request(cfg, bundle, planned, root)
        if opened is not None:
            delivered["merge_request"] = opened

    bundle.write_manifest(mode, planned, delivered)
    bundle.write_digests()  # LAST, so it covers the manifest

    if args.json:
        print(
            json.dumps(
                {
                    "mode": mode,
                    # The PLAN's branch, always — a dry run planned one even
                    # though it created none, and reporting null there would
                    # tell a consumer nothing was going to happen.
                    "branch": planned.branch,
                    "base": planned.base,
                    "files": len(planned.changed_files),
                    "delivery_dir": _relative(bundle.directory, root),
                    "created": delivered["branch"],
                    "commit": delivered["commit"],
                    "pushed": delivered["pushed"],
                    "merge_request": delivered["merge_request"],
                }
            )
        )
    else:
        _report_delivery(mode, planned, delivered, bundle, root)
    return EXIT_OK


def _open_merge_request(
    cfg: config.Config, bundle: deliver.Bundle, planned: deliver.Plan, root: Path
) -> dict[str, object] | None:
    """Open the MR, or say plainly that the branch is up and this step is not.

    A push that landed and an MR that did not is a real state, and it is more
    useful to name it than to fail the whole command over it.
    """
    if cfg.forge is None:
        print(
            "wring deliver: the branch is pushed, but no 'forge:' section is "
            "declared, so no merge request was opened.",
            file=sys.stderr,
        )
        return None
    bundle.event("mr.planned", head=planned.branch, base=planned.base)
    try:
        opened = forge.open_merge_request(
            cfg.forge,
            os.environ.get(cfg.forge.token_env or ""),
            planned.title,
            planned.branch,
            planned.base,
            (bundle.directory / deliver.MR_FILENAME).read_text(encoding="utf-8"),
        )
    except (forge.ForgeError, OSError) as exc:
        bundle.event("mr.failed", why=str(exc))
        print(
            f"wring deliver: the branch is pushed, but the merge request could "
            f"not be opened: {exc}",
            file=sys.stderr,
        )
        return None
    bundle.event("mr.opened", number=opened.number, url=opened.url)
    return {"number": opened.number, "url": opened.url}


def _delivery_target(named: str | None, root: Path) -> Path | None:
    if named is not None:
        run_dir = Path(named)
        if not run_dir.is_dir():
            print(f"wring deliver: no run directory at {named}", file=sys.stderr)
            return None
        return run_dir
    found = evidence.latest_run(root / evidence.RUNS_DIRNAME)
    if found is None:
        print(
            f"wring deliver: no runs under "
            f"{(root / evidence.RUNS_DIRNAME).as_posix()} — run 'wring verify' "
            "first; delivery needs something that passed",
            file=sys.stderr,
        )
        return None
    return found


def _report_delivery(
    mode: str,
    planned: deliver.Plan,
    delivered: dict[str, object],
    bundle: deliver.Bundle,
    root: Path,
) -> None:
    where = _relative(bundle.directory, root)
    if mode == "dry_run":
        print("dry run — nothing was written to git.\n")
        print(f"Would create branch:  {planned.branch}")
        print(f"        targeting:    {planned.base}")
        print(f"        with:         {len(planned.changed_files)} file(s)")
        print(f"\nThe patch, message, branch and MR body are in:\n{where}/")
        print(
            "\nRead them — and edit commit.txt or mr.md if you want — then:\n"
            "  wring deliver --send"
        )
        return

    print(f"Branch:  {delivered.get('branch')}")
    if delivered.get("commit"):
        print(f"Commit:  {str(delivered['commit'])[:12]}")
    print(f"Pushed:  {'yes' if delivered.get('pushed') else 'no'}")
    merge_request = delivered.get("merge_request")
    if isinstance(merge_request, dict):
        print(f"MR:      {merge_request.get('url')}")
    print(f"\nDelivery evidence: {where}/")


def _refuse_unverifiable(root: Path, command: str) -> int | None:
    """The preconditions every verifying command shares, or None to proceed.

    A bundle that describes an unsafe or unknowable state is worse than no
    bundle, so neither one gets written.
    """
    if not git.is_repo(root):
        print(
            f"wring {command}: {Path.cwd()} is not a git repository — verification "
            "records which commit and which changes were proven, so it needs "
            "one. Run 'git init', or verify from inside your repo.",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    unfinished = git.in_progress(root)
    if unfinished is not None:
        print(
            f"wring {command}: refusing to verify in the middle of {unfinished} — "
            "HEAD and the working tree describe a state nobody chose. Finish "
            "or abort it, then verify.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    return None


def cmd_attest(args: argparse.Namespace) -> int:
    """Assemble the provenance claim. Never opens a socket, never calls an LLM."""
    from wringer import attest

    root = git.find_root(Path.cwd())
    if args.anchor:
        anchor = Path(args.anchor)
        if not anchor.is_absolute():
            anchor = root / anchor
        if not anchor.is_dir():
            print(f"wring attest: no such directory: {anchor}", file=sys.stderr)
            return EXIT_CONFIG
    else:
        found = attest.latest_anchor(root)
        if found is None:
            print(
                "wring attest: nothing to attest — no runs and no deliveries "
                "under .wringer/. Run 'wring verify' first",
                file=sys.stderr,
            )
            return EXIT_CONFIG
        anchor = found

    try:
        built = attest.build(root, anchor)
    except attest.Refused as exc:
        _fail("attest", exc)
        return EXIT_GATE_FAILED
    except attest.AttestError as exc:
        _fail("attest", exc)
        return EXIT_CONFIG

    bundle = attest.Bundle.create(root, built.payload["attestation_id"])
    written = bundle.write(built.payload)

    if args.json:
        print(json.dumps({
            "attestation_id": built.payload["attestation_id"],
            "attestation": _relative(written, root),
            "signature": built.payload["signature"],
            "limits": built.payload["limits"],
            "bundles": built.payload["bundles"],
            "change": built.payload["change"],
            "clauses": [
                name for name in
                ("authorized_by", "proven_by", "judged_by", "delivered_as")
                if name in built.payload
            ],
        }))
        return EXIT_OK

    payload = built.payload
    print(f"Attested {payload['attestation_id']}\n")
    # The CLAUSES only. The summary renders the limits as bullets too, and
    # scraping its "- " lines printed the whole limits list here and then
    # again as the `!` line below — which teaches a reader to skim past the
    # one sentence that says what this artifact is not.
    for label, line in attest.clause_lines(payload):
        print(f"  {label:<14} {line}")
    # `!` — doctor's mark for "worth knowing, not a problem". NEVER `✗`:
    # nothing failed, and a red mark here would teach people to ignore the
    # one line that says what this artifact is not.
    print(f"\n! {attest.UNSIGNED_LIMIT}")
    print(f"\nWritten to {_relative(bundle.directory, root)}/")
    print(f"Check it yourself:\n  wring audit {_relative(written, root)}")
    return EXIT_OK


def cmd_audit(args: argparse.Namespace) -> int:
    """Check an attestation. No config is read — an auditor may not have one."""
    from wringer import attest

    path = Path(args.attestation)
    if path.is_dir():  # a directory is an easy mistake; point at the file
        path = path / attest.ATTESTATION_FILENAME
    if not path.is_file():
        print(f"wring audit: no such file: {path}", file=sys.stderr)
        return EXIT_CONFIG

    try:
        report = attest.audit(path)
    except attest.AttestError as exc:
        _fail("audit", exc)
        return EXIT_CONFIG

    if args.json:
        print(json.dumps({
            "ok": report.ok,
            "attestation": report.attestation,
            "checked": report.checked,
            "problem": report.problem,
            "signature": report.signature,
            "limits": report.limits,
        }))
        return EXIT_OK if report.ok else EXIT_GATE_FAILED

    if not report.ok:
        print(f"✗ {path.name} does not verify\n", file=sys.stderr)
        print(f"  {report.problem}", file=sys.stderr)
        return EXIT_GATE_FAILED

    files = sum(entry["files"] for entry in report.checked)
    print(f"✓ {path.name} verifies")
    for entry in report.checked:
        print(f"  {entry['role']:<9} {entry['path']}  ({entry['files']} files)")
    print(f"\n  {len(report.checked)} bundle(s), {files} file(s) — every digest "
          "matches and every ledger chain is intact.")
    # Repeated on SUCCESS, deliberately: a passing audit must not read as a
    # stronger claim than it is.
    print(f"\n! {attest.UNSIGNED_LIMIT}")
    return EXIT_OK


def cmd_explain(args: argparse.Namespace) -> int:
    """Read a finished run and say what happened, without an LLM.

    Everything printed here is already in the bundle — this command exists
    so a human (or an agent shelling out) does not have to open four files
    to learn which gate failed and how to rerun it.
    """
    root = git.find_root(Path.cwd())

    if args.run is not None:
        run_dir = Path(args.run)
        if not run_dir.is_dir():
            print(f"wring explain: no run directory at {args.run}", file=sys.stderr)
            return EXIT_CONFIG
    else:
        runs_root = root / evidence.RUNS_DIRNAME
        found = evidence.latest_run(runs_root)
        if found is None:
            print(
                f"wring explain: no runs under {runs_root.as_posix()} — "
                "run 'wring verify' first",
                file=sys.stderr,
            )
            return EXIT_CONFIG
        run_dir = found

    try:
        manifest = evidence.read_manifest(run_dir)
        recorded = evidence.read_events(run_dir)
        rows = evidence.read_gate_results(run_dir)
    except evidence.EvidenceError as exc:
        _fail("explain", exc)
        return EXIT_CONFIG

    _explain(run_dir, manifest, recorded, rows)
    return EXIT_OK


def _explain(
    run_dir: Path,
    manifest: dict,
    recorded: list[dict],
    rows: list[tuple[Path, dict]],
) -> None:
    result = manifest.get("result", {})
    status = result.get("status", "unknown")
    failed_gate = result.get("failed_gate")
    repo = manifest.get("repo", {})
    started = next(
        (event for event in recorded if event.get("type") == "run.started"), {}
    )

    print(f"Run {manifest.get('run_id', run_dir.name)} — {status}")
    print(_explain_repo_line(started, repo, manifest))
    print()

    for _, row in rows:
        print(
            _gate_line(
                row.get("gate_id", "?"),
                row.get("status") == "passed",
                bool(row.get("timed_out")),
                int(row.get("duration_ms", 0)),
                bool(row.get("optional")),
            )
        )

    if failed_gate is not None:
        _explain_failure(run_dir, failed_gate, rows)
    elif status == "interrupted":
        # An interrupted run has no failing gate, but "nothing to diagnose"
        # would be a lie: gates after the interruption never ran at all.
        _explain_interruption(run_dir, recorded)
    elif _bundle_was_template_only(run_dir):
        # "Every required gate passed" is true and, on its own, misleading:
        # the only gate was the placeholder `wring init` writes, so nothing
        # about this code was proven. `wring verify` says so at the time and
        # `summary.md` carries it, but `explain` is what someone reads AFTER
        # the terminal is gone — and it printed an unqualified green verdict
        # over a bundle whose own summary said otherwise.
        #
        # Read from the bundle's summary rather than recomputed from config:
        # `explain` may be pointed at a bundle from another repo, or one
        # whose `.wringer.yaml` has since been fixed, and the bundle is the
        # thing being explained.
        print(f"\n! {detect.TEMPLATE_WARNING}")
    else:
        print("\nEvery required gate passed — nothing to diagnose.")

    _explain_changes(recorded)

    report = run_dir / summary.SUMMARY_FILENAME
    try:
        shown = report.relative_to(Path.cwd()).as_posix()
    except ValueError:
        shown = report.as_posix()
    print(f"\nFull report:\n  {shown}")
    if failed_gate is not None:
        print(f"\nRerun:\n  wring verify --gate {failed_gate}")
    elif status == "interrupted":
        # The whole run, not one gate: an interrupt leaves everything from
        # the stopped gate onwards unproven.
        print("\nRerun:\n  wring verify")


def _bundle_was_template_only(run_dir: Path) -> bool:
    """Whether this bundle recorded that it proved nothing.

    The fact lives in `summary.md`, not in the manifest: `wringer.evidence.v1`
    is frozen and cannot grow a key for it, so the bundle's prose is where it
    was written. Reading it back means `explain` agrees with the file it is
    explaining, even for a bundle produced by another repo or another version.
    """
    report = run_dir / summary.SUMMARY_FILENAME
    try:
        return detect.TEMPLATE_WARNING in report.read_text(encoding="utf-8")
    except OSError:
        return False


def _explain_repo_line(started: dict, repo: dict, manifest: dict) -> str:
    name = started.get("repo") or "repo"
    sha = repo.get("head_sha")
    where = f"{name} @ {sha[:7]}" if sha else f"{name} (not a git repository)"
    if repo.get("branch"):
        tree = "dirty" if repo.get("dirty") else "clean"
        where += f" (branch {repo['branch']}, {tree})"
    at = manifest.get("started_at")
    return f"{where} · started {at}" if at else where


def _explain_failure(
    run_dir: Path, failed_gate: str, rows: list[tuple[Path, dict]]
) -> None:
    match = next(
        ((d, r) for d, r in rows if r.get("gate_id") == failed_gate), None
    )
    if match is None:  # a bundle that names a gate it never recorded
        print(f"\nFailing gate: {failed_gate} (no result.json recorded)")
        return

    gate_dir, row = match
    print(f"\nFailing gate: {failed_gate}")
    print(f"  command    {row.get('command', '?')}")
    print(f"  exit code  {row.get('exit_code', '?')}")
    if row.get("timed_out"):
        print("  timed out  yes")

    for stream in ("stdout", "stderr"):
        path = gate_dir / f"{stream}.log"
        # label it the way the bundle does, so the reader can find the file
        _print_tail(path, path.relative_to(run_dir).as_posix())


def _explain_interruption(run_dir: Path, recorded: list[dict]) -> None:
    """Name the gate that was running when the run stopped.

    It has no `result.json` — it never finished — so the record of it is the
    `gate.started` event nothing answered, plus whatever it managed to print
    before it was killed.
    """
    answered = {
        event.get("gate_id")
        for event in recorded
        if event.get("type") == "gate.finished"
    }
    unanswered = [
        event
        for event in recorded
        if event.get("type") == "gate.started"
        and event.get("gate_id") not in answered
    ]
    if not unanswered:
        print("\nInterrupted before any gate started.")
        return

    event = unanswered[-1]
    gate_id = event.get("gate_id", "?")
    print(f"\nInterrupted during gate: {gate_id}")
    print(f"  command    {event.get('command', '?')}")

    gate_dir = _gate_dir_for(run_dir, str(gate_id))
    if gate_dir is None:
        return
    for stream in ("stdout", "stderr"):
        path = gate_dir / f"{stream}.log"
        _print_tail(path, path.relative_to(run_dir).as_posix())


def _gate_dir_for(run_dir: Path, gate_id: str) -> Path | None:
    """The `gates/NNN_<id>/` directory for one gate id.

    Matched on the whole name after the numeric prefix, never a suffix
    search: a gate called `test` must not find `unit_test`'s evidence.
    """
    gates_root = run_dir / evidence.GATES_DIRNAME
    if not gates_root.is_dir():
        return None
    for path in sorted(gates_root.iterdir()):
        name = path.name
        if path.is_dir() and name[:3].isdigit() and name[3:] == f"_{gate_id}":
            return path
    return None


def _explain_changes(recorded: list[dict]) -> None:
    git_status = next(
        (event for event in recorded if event.get("type") == "git.status"), None
    )
    if git_status is None:
        return

    changed = git_status.get("changed_files", [])
    untracked = git_status.get("untracked", [])
    if not changed and not untracked:
        print("\nNo uncommitted changes.")
        return

    if changed:
        print(f"\nChanged files ({len(changed)}):")
        for path in changed[:EXPLAIN_FILE_LIMIT]:
            print(f"  {path}")
        if len(changed) > EXPLAIN_FILE_LIMIT:
            print(f"  … {len(changed) - EXPLAIN_FILE_LIMIT} more")
    if untracked:
        lead = "" if changed else "\n"
        shown = ", ".join(untracked[:5])
        more = f", … {len(untracked) - 5} more" if len(untracked) > 5 else ""
        print(f"{lead}Untracked ({len(untracked)}): {shown}{more}")


def _gate_line(
    gate_id: str,
    passed: bool,
    timed_out: bool,
    duration_ms: int,
    optional: bool,
) -> str:
    """The spec's demo shape, used live by `verify` and replayed by `explain`
    so one gate never reads two different ways."""
    mark = "✓" if passed else "✗"
    outcome = "passed" if passed else ("timed out" if timed_out else "failed")
    label = f"{gate_id} {outcome}"
    padding = " " * max(1, 19 - len(label))
    note = "  (optional)" if not passed and optional else ""
    return f"{mark} {label}{padding}{duration_ms / 1000:.1f}s{note}"


def _report_gate(result: gates.GateResult) -> None:
    """One line per gate, printed as it finishes."""
    print(
        _gate_line(
            result.gate.id,
            result.passed,
            result.timed_out,
            result.duration_ms,
            result.gate.optional,
        ),
        flush=True,
    )


def _bundle_path(bundle: evidence.Bundle, root: Path) -> str:
    """The bundle's path as a reader would type it — repo-relative when it
    lives inside the repo, absolute when it somehow does not."""
    try:
        return bundle.directory.relative_to(root).as_posix()
    except ValueError:
        return str(bundle.directory)


def _report_json(
    bundle: evidence.Bundle,
    root: Path,
    failed_gate: str | None,
    status: str = "passed",
    template_only: bool = False,
) -> None:
    """One object on stdout and nothing else (spec §CLI surface).

    This is what a coding agent consumes, so the keys are stable and present
    even when empty: a consumer should never have to distinguish "passed"
    from "the tool forgot to tell me".
    """
    print(
        json.dumps(
            {
                "status": status,
                "failed_gate": failed_gate,
                "rerun": (
                    f"wring verify --gate {failed_gate}"
                    if failed_gate is not None
                    else None
                ),
                "evidence_dir": _bundle_path(bundle, root),
                # An agent is the reader most likely to over-read a bare
                # `"status": "passed"`, and it is exactly the reader the
                # terminal warning cannot reach. Without this key, the one
                # consumer that cannot see the `!` line is the one acting on
                # the result.
                "template_only": template_only,
            }
        )
    )


def _report_run(
    bundle: evidence.Bundle,
    root: Path,
    results: list[gates.GateResult],
    failed_gate: str | None,
    status: str = "passed",
    template_only: bool = False,
    vacuity_result: object | None = None,
) -> None:
    if status == "interrupted":
        print("\n✗ interrupted — the run stopped before every gate finished")
    if failed_gate is not None:
        failure = next(r for r in results if r.gate.id == failed_gate)
        for path in (failure.stdout_path, failure.stderr_path):
            _print_tail(path, bundle.relative(path))
    if template_only:
        # A `!`, deliberately — the same mark `wring doctor` uses for "worth
        # knowing, not a problem". This run did not fail and must not look
        # like it did; it just did not prove anything either.
        print(
            "\n! This config is still a template: the only gate is the"
            "\n  placeholder, so this run proved nothing about your code."
            "\n  Replace it with the commands that prove your change is"
            "\n  mergeable."
        )
    _report_vacuity(vacuity_result, bundle, root)

    shown = _bundle_path(bundle, root)
    print(f"\nEvidence written to:\n{shown}/")

    if failed_gate is not None:
        print(
            f"\nNext:\n  open {shown}/summary.md\n"
            f"  rerun wring verify --gate {failed_gate}"
        )


def _report_vacuity(
    result: object | None, bundle: evidence.Bundle, root: Path
) -> None:
    """Say on the TERMINAL what the prove pass decided.

    `vacuity.json` recorded `gates_vacuous` and `summary.md` carried the
    warning, and the console printed "✓ test passed" and exited 0.
    Everything a reader needed was on disk and none of it was in front of
    them — and `wring deliver` would refuse the bundle much later, for a
    reason nothing had mentioned.

    `template_only` is the same class and this file already solved it
    there: a run that PASSED while proving nothing gets a `!` line. This
    is that case with a sharper edge, because the gates are real and just
    cannot fail.

    Silent on `proven`, and silent when no prove pass ran at all —
    SPEC_VACUITY_V0 §7 is explicit that a repo which never opted in must
    not be nagged.
    """
    from wringer import vacuity as vacuity_module

    if result is None:
        return
    verdict = getattr(result, "verdict", None)
    if verdict in (None, vacuity_module.PROVEN, vacuity_module.NOT_APPLICABLE):
        return

    # Wrapped rather than hand-broken: the reason names the insensitive
    # gates, so its length depends on the repo. A line that runs past the
    # terminal is also a line the demo canvas cannot draw.
    print(
        "\n! "
        + textwrap.fill(
            str(getattr(result, "reason", verdict)),
            width=78,
            subsequent_indent="  ",
        )
    )
    if verdict == vacuity_module.GATES_VACUOUS:
        where = f"{_bundle_path(bundle, root)}/{vacuity_module.VACUITY_DIRNAME}"
        print(f"  Both trees' output: {where}/")
        print("  `wring deliver` will refuse this bundle.")


def _wrap_message(text: str, width: int = 78) -> str:
    """Reflow a message to fit a terminal, without flattening its structure.

    Every refusal in this program is composed as prose, and `wring deliver`'s
    vacuity refusal rendered as a single **402-column line** — four times past
    the edge of any terminal, in a message whose entire job is to be read and
    acted on.

    Line-by-line rather than `textwrap.fill` over the whole string, because
    about half of these messages carry an indented example the reader is meant
    to copy — a `judge:` stanza, a `git remote set-head` command. An INDENTED
    line is structure and is left exactly as it is; an unindented one is prose
    and gets reflowed. Blank lines survive, because they separate the prose
    from the thing to copy.

    Long words are never broken: a path or a URL split across two lines is a
    path nobody can paste.
    """
    lines: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            lines.append("")
        elif line[:1].isspace():
            lines.append(line)
        else:
            lines.extend(
                textwrap.fill(
                    line,
                    width=width,
                    break_long_words=False,
                    break_on_hyphens=False,
                ).split("\n")
            )
    return "\n".join(lines)


def _fail(command: str, message: object) -> None:
    """The one way this CLI reports a refusal or an error to stderr."""
    print(_wrap_message(f"wring {command}: {message}"), file=sys.stderr)


def _print_tail(path: Path, label: str) -> None:
    """The tail of a failing gate's log — skipped when it wrote nothing."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    if not lines:
        return

    shown = lines[-LOG_TAIL_LINES:]
    elided = len(lines) - len(shown)
    where = f"{label} (last {len(shown)} of {len(lines)} lines)" if elided else label
    print(f"\n--- {where} ---")
    for line in shown:
        print(line)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        # A Ctrl-C between the phases that handle it themselves still owes the
        # caller the contract's exit code, not a traceback.
        print("\nwring: interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
