"""Turn a verified change into a branch and an MR — `wringer.delivery.v1`.

**The only module in Wringer that writes git history**, and the only reason
handover law 6 needed amending. The amendment is worth exactly its five
conditions, and each is a refusal here rather than a line in a document:

1. **Only a branch Wringer created.** `Bundle.event("branch.planned")` is
   appended *before* the branch exists, so "did Wringer make this?" is a
   question the ledger answers. An existing branch is a refusal.
2. **Never the default branch.** Resolved from the remote, and an
   unresolvable default is itself a refusal — a branch you could not name is
   not one you can be sure you avoided.
3. **No force push, anywhere.** `--force`, `--force-with-lease` and `+refs/`
   appear nowhere in this program, and a test greps for them.
4. **Dry run is the default.** Everything below `plan()` is written to disk
   and printed; `send()` is the same path continuing one step further.
5. **A ledger event before every git write**, so a crash mid-delivery still
   says what was attempted. Nothing is rolled back: a half-delivered branch
   is a fact, and a tidy-up that deleted branches would be a worse power than
   the one being granted.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from wringer import config, evidence, git, summary
from wringer.redact import Redactor

DELIVERIES_DIRNAME = Path(".wringer") / "deliveries"
SCHEMA_VERSION = "wringer.delivery.v1"
EVENTS_FILENAME = "delivery.jsonl"
MANIFEST_FILENAME = "manifest.json"
PATCH_FILENAME = "patch.diff"
COMMIT_FILENAME = "commit.txt"
BRANCH_FILENAME = "branch.txt"
MR_FILENAME = "mr.md"
COMMANDS_FILENAME = "commands.txt"

GIT_TIMEOUT_SECONDS = 120

# Wringer's own directory, which a delivery must never carry. Evidence stays
# with the machine that produced it — that is a promise the README makes and
# the one this module is in the best position to break.
EVIDENCE_DIRNAME = ".wringer"

# Branch names git will not take, and names that would be a disaster if it
# did. Checked before the name reaches a subprocess.
_BAD_BRANCH = ("..", "~", "^", ":", "?", "*", "[", "\\", " ", "@{")


class DeliverError(Exception):
    """The change could not be delivered (CLI exit code 2)."""


class Refused(Exception):
    """A precondition said no — about the work, not the environment.

    Carries the exit code the CLI should use, because "there is nothing to
    deliver" (1) and "this tree is unsafe" (3) are different answers.
    """

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class Plan:
    """Everything the delivery would do, before any of it is done."""

    branch: str
    base: str
    remote: str
    title: str
    commit_message: str
    mr_body: str
    patch: str
    changed_files: tuple[str, ...]
    run_dir: str
    commands: tuple[str, ...]
    # The approved spec this change answers, if any. Recorded because
    # `approved: true` is the authority the whole build ran on, and
    # nothing else in the program wrote down which spec that was.
    spec_sha256: str | None = None


def resolve_branch(template: str, run_id: str, task: str | None) -> str:
    """Fill the declared placeholders, then check git would accept the name."""
    name = config.substitute(template, run=run_id, task=task or run_id)
    if not name or name.startswith("-") or name.endswith(("/", ".lock", ".")):
        raise DeliverError(f"'{name}' is not a usable branch name")
    for bad in _BAD_BRANCH:
        if bad in name:
            raise DeliverError(f"branch name '{name}' contains {bad!r}")
    return name


def check_tree(root: Path) -> None:
    unfinished = git.in_progress(root)
    if unfinished is not None:
        raise Refused(
            f"refusing to deliver in the middle of {unfinished} — HEAD and the "
            "working tree describe a state nobody chose",
            3,
        )


def check_identity(root: Path) -> None:
    """Refuse before the branch exists if git has nobody to attribute to.

    Checked in `plan()` rather than discovered at `git commit` — on a machine
    with no identity (a CI runner, a fresh container) the commit fails *after*
    the branch has been created, which leaves a half-delivered branch for a
    reason that had nothing to do with the change.

    macOS hides this: git invents `user@host`. Linux with an unqualified
    hostname does not, and says so.
    """
    for key in ("user.name", "user.email"):
        code, _ = _git(root, ["config", "--get", key], check=False)
        if code != 0:
            raise Refused(
                f"git has no {key} here, so a commit would have no author. "
                "Wringer commits as you, using your git identity — it does not "
                "invent one. Set it:\n"
                f"  git config --global {key} \"...\"",
                2,
            )


def gates_passed(run_dir: Path) -> tuple[bool, str | None]:
    try:
        manifest = evidence.read_manifest(run_dir)
    except evidence.EvidenceError as exc:
        raise DeliverError(str(exc)) from exc
    result = manifest.get("result", {})
    return result.get("status") == "passed", result.get("failed_gate")


def branch_exists(root: Path, name: str, remote: str | None = None) -> bool:
    """Whether the branch already exists — locally OR on the remote.

    Checking only local refs let delivery create a branch that already exists
    upstream, and push into someone else's history. Condition 1 says *only a
    branch Wringer created*; a name that exists anywhere is not one of those.
    """
    refs = [f"refs/heads/{name}"]
    if remote:
        refs.append(f"refs/remotes/{remote}/{name}")
    for ref in refs:
        if _git(root, ["rev-parse", "--verify", "--quiet", ref], check=False)[0] == 0:
            return True
    if remote:
        # A remote ref we have never fetched is still a branch that exists.
        #
        # And a remote we could not REACH is not an answer at all. This used
        # to fall through to `return False`, folding "the branch does not
        # exist" and "I could not find out" into the same value — so an
        # unreachable remote silently satisfied condition 1 and delivery
        # planned a branch that might already be someone else's. Refusing is
        # the only honest option: the whole point of the check is that
        # Wringer commits only to a branch it created, and that cannot be
        # asserted from a failed lookup.
        code, out = _git(
            root, ["ls-remote", "--heads", remote, f"refs/heads/{name}"], check=False
        )
        if code != 0:
            raise Refused(
                f"cannot reach '{remote}' to check whether the branch "
                f"'{name}' already exists, so Wringer cannot promise it is "
                "creating a branch of its own rather than writing into "
                f"someone else's. Fix the remote (try 'git ls-remote {remote}') "
                "and run this again",
                3,
            )
        if out.strip():
            return True
    return False


def check_verified_tree(root: Path, run_dir: Path, state: git.RepoState) -> None:
    """Refuse unless the bundle describes the tree being shipped.

    **The most important refusal in this module.** `gates_passed` reads the
    bundle's *status*; it says nothing about *what* passed. Without this, a
    user could verify, keep working, and deliver — and the MR body would
    report the gate table of a run that never saw the delivered code.

    That is not a near-miss. It is Wringer publishing a claim of verification
    about code that was never verified: law 1 and law 2, broken by the one
    command that speaks to the outside world, in the product whose entire
    pitch is "your agent says it passed; prove it".

    Two things must match: the commit the bundle was taken against, and the
    working-tree changes it captured. The second is the one that bites — the
    common case is an unchanged HEAD and edits made after the gates ran.
    """
    try:
        manifest = evidence.read_manifest(run_dir)
    except evidence.EvidenceError as exc:
        raise DeliverError(str(exc)) from exc

    repo = manifest.get("repo", {})
    verified_sha = repo.get("head_sha")
    if verified_sha and state.head_sha and verified_sha != state.head_sha:
        raise Refused(
            f"{run_dir.name} verified {verified_sha[:12]}, but HEAD is now "
            f"{state.head_sha[:12]}. The gates never ran against the tree you "
            "are delivering — run 'wring verify' again",
            1,
        )

    # What the tree looked like when the gates ran, from the bundle's own
    # git.status event. Compared as sets: order is not meaning.
    try:
        recorded = evidence.read_events(run_dir)
    except evidence.EvidenceError as exc:
        raise DeliverError(str(exc)) from exc
    snapshot = next(
        (e for e in recorded if e.get("type") == "git.status"), None
    )
    if snapshot is None:
        return  # a bundle with no git snapshot cannot contradict the tree

    then = set(snapshot.get("changed_files", [])) | set(
        snapshot.get("untracked", [])
    )
    now = set(state.changed_files) | set(state.untracked)
    then = {p for p in then if not p.startswith(f"{EVIDENCE_DIRNAME}/")}
    now = {p for p in now if not p.startswith(f"{EVIDENCE_DIRNAME}/")}
    if then != now:
        added, removed = sorted(now - then), sorted(then - now)
        detail = []
        if added:
            detail.append(f"changed since: {', '.join(added[:5])}")
        if removed:
            detail.append(f"no longer changed: {', '.join(removed[:5])}")
        raise Refused(
            f"the working tree has moved since {run_dir.name} verified it "
            f"({'; '.join(detail)}). Delivering now would attach that run's "
            "gate results to code it never saw — run 'wring verify' again",
            1,
        )

    # The same file list can hold different bytes, so compare the patch too.
    # This is what catches an edit to a file that was already changed when the
    # gates ran — the commonest way a tree moves without its shape moving.
    captured = run_dir / evidence.DIFF_FILENAME
    if captured.is_file():
        before = captured.read_text(encoding="utf-8", errors="replace")
        after = git.diff(root, state.head_sha) or ""
        if before.strip() != after.strip():
            raise Refused(
                f"the tracked changes differ from what {run_dir.name} verified. "
                "The file list matches but the contents do not, so that run's "
                "gate results describe different code — run 'wring verify' again",
                1,
            )
    # And the untracked bytes, which git cannot diff because it has never seen
    # the files. Without this the check compared untracked content by NAME
    # alone, so editing a new file between verify and deliver was undetectable
    # — the last hole in this function's promise.
    _check_untracked_bytes(root, run_dir, state)


# 2026-08-06. `d0f866c` landed `untracked.json` and its commit message called
# it "the last hole in this function's promise". It was not, and the claim is
# left standing above rather than quietly rewritten because the repo's rule is
# that a wrong claim gets corrected in place.
#
# What that version missed: it hashed the bytes `open("rb")` returned, which
# FOLLOWS a symlink. git commits mode `120000` and a blob holding the link
# TEXT, so retargeting a link at a file with identical bytes, or `chmod +x` on
# a new script, changed the delivered tree without changing anything the check
# compared. It also read three perfectly committable paths as `unreadable` — a
# dangling link, a link to a directory — which refused delivery permanently
# (re-verifying recorded `unreadable` again), and blocked forever on a link to
# a FIFO. An adversarial review found all five; `wringer.untracked.v2` records
# git's identity for the path instead, which closes them together.
#
# The honest general statement, which is what this function can promise: it
# refuses when the untracked part of the tree is not the object git would have
# committed at verify time. Whether that is the LAST hole is not something a
# commit message gets to assert.
def _check_untracked_bytes(root: Path, run_dir: Path, state: git.RepoState) -> None:
    """Refuse when an untracked path's identity moved since the gates ran.

    Only for bundles that recorded them. A bundle written before
    `untracked.json` existed keeps exactly the behaviour it had — names
    compared, contents not — because retro-fitting a refusal onto evidence
    that never made the claim would fail deliveries that were always fine.
    """
    recorded = run_dir / evidence.UNTRACKED_FILENAME
    if not recorded.is_file():
        return
    try:
        payload = json.loads(recorded.read_text(encoding="utf-8"))
        version = payload.get("schema_version")
        stored = payload.get("files", {})
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        raise Refused(
            f"{run_dir.name} recorded untracked files but "
            f"{evidence.UNTRACKED_FILENAME} cannot be read ({exc}). That run "
            "cannot vouch for the tree — run 'wring verify' again",
            1,
        ) from exc

    if version == evidence.UNTRACKED_SCHEMA_VERSION_V1:
        # A v1 record answers a different question — what a gate could read
        # through the symlink — so it cannot be compared against a v2 one, and
        # re-deriving the v1 answer would mean keeping the code that hangs on
        # a FIFO. A v1 bundle therefore delivers exactly as a bundle written
        # before this file existed: names compared, bytes not. v1 shipped
        # unreleased and lived for one day, so this weakens nothing that was
        # ever promised to a user.
        return
    if version != evidence.UNTRACKED_SCHEMA_VERSION:
        raise Refused(
            f"{run_dir.name} recorded its untracked files as "
            f"{version!r}, which this version of Wringer cannot read. An "
            "unanswerable check refuses rather than passes — upgrade Wringer, "
            "or run 'wring verify' again with this one",
            1,
        )

    unreadable = sorted(p for p, d in stored.items() if d == evidence.UNREADABLE)
    if unreadable:
        raise Refused(
            f"{run_dir.name} could not read {', '.join(unreadable[:5])} when it "
            "verified, so their contents were never checked. Delivering would "
            "claim they were — fix the permissions and run 'wring verify' again",
            1,
        )
    unsupported = sorted(p for p, d in stored.items() if d == evidence.UNSUPPORTED)
    if unsupported:
        raise Refused(
            f"{', '.join(unsupported[:5])} is neither a regular file nor a "
            "symlink, so git will not commit it and "
            f"{run_dir.name} could not record what it holds. Remove it and run "
            "'wring verify' again",
            1,
        )

    live = evidence.hash_untracked(
        root, evidence.untracked_subject(state.untracked)
    )
    moved = sorted(
        path
        for path, digest in stored.items()
        if live.get(path) != digest and not path.startswith(f"{EVIDENCE_DIRNAME}/")
    )
    if moved:
        raise Refused(
            f"{', '.join(moved[:5])} is not what {run_dir.name} verified — its "
            "contents, its file mode or its symlink target has changed. git "
            "never saw these files, so nothing else would have caught it — run "
            "'wring verify' again",
            1,
        )


# What git reads as false in a boolean config value — git's own list.
_CONFIG_FALSE = {"false", "no", "off", "0", ""}


def _case_insensitive(root: Path) -> bool:
    """Whether git treats two paths differing only in case as one file here.

    Read from `core.ignorecase`, which `git init` probes and writes, rather
    than guessed from the platform: a case-sensitive volume mounted on macOS
    is an ordinary thing to have. Unset answers false, which is git's own
    default when nothing probed it.
    """
    code, out = _git(root, ["config", "--get", "core.ignorecase"], check=False)
    if code != 0:
        return False
    return out.strip().lower() not in _CONFIG_FALSE


def _case_aliases(paths: tuple[str, ...]) -> list[tuple[str, str]]:
    """Pairs in `paths` that name the same file on a case-insensitive volume."""
    first: dict[str, str] = {}
    pairs: list[tuple[str, str]] = []
    for path in paths:
        key = path.lower()
        if key in first and first[key] != path:
            pairs.append((first[key], path))
        else:
            first.setdefault(key, path)
    return pairs


def _check_no_case_aliases(root: Path, carried: tuple[str, ...]) -> None:
    """Refuse a case-only rename here, where no branch exists yet to strand.

    `git mv Foo.py foo.py` on a case-insensitive volume puts BOTH names in
    `changed_files`, because that is what the porcelain reports — one `R`
    entry whose two paths differ only in case. **No path-restricted commit can
    express it.** Measured on git 2.50.1:

      - `commit --only foo.py` exits 128: *will not add file alias 'foo.py'
        ('Foo.py' already exists in index)*. `--only` rebuilds from HEAD, HEAD
        holds `Foo.py`, and adding `foo.py` beside it is the alias git refuses.
      - `commit --only Foo.py` exits 1, "nothing to commit": the pathspec
        matches HEAD's entry and the worktree file has the same content, so
        the rename is invisible.
      - naming both, in either order, fails exactly like naming the new one.

    Two ways out were measured and rejected. Committing the whole index works
    and would ship whatever else the user had staged, which is the hole
    `--only` exists to close. Building the tree through a temporary index and
    `commit-tree` *succeeds* and writes BOTH paths into the tree — a wrong
    tree, delivered silently, which is worse than any refusal.

    So it refuses, and it refuses from `plan()`. The failure used to arrive
    from `send()` **after** `switch --create`, leaving the user standing on a
    branch Wringer had made and abandoned, with a git fatal for a message.
    """
    if not _case_insensitive(root):
        return  # here the two names really are two files, and git is happy
    aliases = _case_aliases(carried)
    if not aliases:
        return
    named = "; ".join(f"'{old}' and '{new}'" for old, new in aliases[:3])
    raise Refused(
        f"{named} are the same file on this filesystem, so this change "
        "renames a file by its capitalisation alone. git cannot commit that "
        "through a path-restricted commit — 'git commit --only' refuses with "
        "'will not add file alias' — and Wringer will not commit the whole "
        "index instead, because that would ship whatever else you have "
        "staged. Commit the rename yourself with 'git commit', then run "
        "'wring verify' again",
        1,
    )


def resolve_base(root: Path, settings: config.Deliver) -> tuple[str, str | None]:
    """The branch the MR targets, and the remote's default branch.

    Both, always — because condition 2 is "never the default branch", and a
    configured `deliver.base` used to skip the lookup entirely. That let a
    config key defeat the condition: set `base: main` and the branch template
    to `main`, and delivery would happily commit to and push the default
    branch. The default is now resolved whatever `base` says, so it can be
    refused against.
    """
    from wringer import acquire

    default = acquire.default_branch(root, settings.remote)
    # Resolved FIRST, and refused on before `base` is consulted. The early
    # return used to sit above this check, so a configured `deliver.base`
    # carried an unresolvable `None` default straight through to `plan`,
    # whose condition-2 guard reads `if default and branch == default` — a
    # None short-circuits it, and delivery would happily plan to create and
    # push the remote's actual default branch. Setting `base` says which
    # branch the MR targets; it has never said "skip the safety check", and
    # this function's own docstring already promised it did not.
    if not default:
        # The remedy has to be one that can actually clear THIS refusal. The
        # message used to end "or set the branch name to something that is
        # plainly not the default", which cannot: this fires from here, and
        # `resolve_branch` has not run yet — no branch name has reached the
        # code, so no branch name can change its mind. Nor can `deliver.base`,
        # deliberately, per the check just above. Sending a reader off to do
        # work that changes nothing is worse than saying only "no".
        raise Refused(
            f"the remote's default branch could not be determined, so Wringer "
            f"cannot be sure it is avoiding it. Make '{settings.remote}' "
            f"answer, then record its default locally:\n"
            f"  git fetch {settings.remote}\n"
            f"  git remote set-head {settings.remote} -a\n"
            "Setting 'deliver.base' does not clear this, and neither does the "
            "branch name: the default is resolved whatever 'base' says, "
            "because 'base' names the branch the merge request targets and "
            "has never meant 'skip the check'",
            3,
        )
    if settings.base:
        return settings.base, default
    return default, default


def plan(
    root: Path,
    cfg: config.Config,
    run_dir: Path,
    run_id: str,
    task: str | None = None,
) -> Plan:
    """Work out the whole delivery. Touches git only to read."""
    assert cfg.deliver is not None
    settings = cfg.deliver

    check_tree(root)
    check_identity(root)

    passed, failed_gate = gates_passed(run_dir)
    if not passed:
        raise Refused(
            f"refusing to deliver {run_dir.name} — its gates did not pass"
            + (f" (`{failed_gate}` failed)" if failed_gate else "")
            + ". An unverified change does not get a branch",
            1,
        )

    state = git.inspect(root)
    check_verified_tree(root, run_dir, state)

    # The delivered set, honestly: `.wringer/` is excluded at `git add` time,
    # so counting it here would make the plan describe a commit that will not
    # happen. A repo that gitignored it never sees these paths at all.
    #
    # Deduplicated, because one path can arrive from both lists. `git mv a.c
    # b.c` followed by a NEW file at `a.c` reports `R a.c -> b.c` AND `?? a.c`
    # — the source is a deletion git is tracking and the new file is one it
    # has never seen, both true of the same name. Counted twice, a two-file
    # change was announced as "3 file(s)" on the terminal, in `--json`, and in
    # the MR body a human reads before approving a push.
    #
    # First occurrence wins so the order still follows git's, which is what
    # the patch and the plan display.
    carried = tuple(
        dict.fromkeys(
            path
            for path in tuple(state.changed_files) + tuple(state.untracked)
            if not path.startswith(f"{EVIDENCE_DIRNAME}/")
            and path != EVIDENCE_DIRNAME
        )
    )
    if not carried:
        raise Refused("there is nothing to deliver — the working tree is clean", 1)

    _check_no_case_aliases(root, carried)

    base, default = resolve_base(root, settings)
    branch = resolve_branch(settings.branch, run_id, task)

    if branch == base:
        raise Refused(
            f"the branch template resolved to '{branch}', which is the base "
            "branch. Wringer never commits to the branch it is merging into",
            3,
        )
    if default and branch == default:
        # Condition 2, enforced even when `deliver.base` names something else.
        raise Refused(
            f"the branch template resolved to '{branch}', which is the "
            f"remote's default branch. Wringer never writes to it, whatever "
            "'deliver.base' says",
            3,
        )
    if state.branch == branch:
        raise Refused(
            f"you are standing on '{branch}'. Wringer commits to a branch it "
            "created, never the one you are on",
            3,
        )
    if branch_exists(root, branch, settings.remote):
        raise Refused(
            f"branch '{branch}' already exists (locally or on "
            f"'{settings.remote}'). Wringer only ever commits to a branch it "
            "created itself, so it will not check this one out",
            3,
        )

    title = _title(run_dir, root, task)
    # Tracked changes, plus a real new-file diff for the untracked ones. A
    # change made entirely of new files used to render an EMPTY patch, so the
    # human approving `--send` approved nothing. `--no-index` gets the content
    # without staging, so the dry run still touches git's index not at all.
    untracked = tuple(p for p in carried if p in set(state.untracked))
    patch = (git.diff(root, state.head_sha) or "") + git.diff_untracked(
        root, untracked
    )
    return Plan(
        branch=branch,
        base=base,
        remote=settings.remote,
        title=title,
        commit_message=f"{title}\n\nVerified by wringer: {run_dir.name}\n",
        mr_body=_mr_body(run_dir, root, state, len(carried)),
        patch=patch,
        changed_files=carried,
        run_dir=str(run_dir),
        spec_sha256=_spec_module().authorising_sha256(root),
        commands=(
            f"git switch --create {branch}",
            # the planned paths on stdin — never a bare add --all; see send()
            "git add --all --pathspec-from-file=- --pathspec-file-nul",
            "git commit --file .wringer/deliveries/<id>/commit.txt",
            f"git push --set-upstream {settings.remote} {branch}",
            f"POST a merge request: {branch} -> {base}",
        ),
    )


def _spec_module():
    from wringer import spec as spec_module

    return spec_module


def _title(run_dir: Path, root: Path, task: str | None) -> str:
    """A one-line subject, taken from something a human wrote.

    Never invented: the spec's title if there is an approved spec, else the
    task id, else the run id. A commit message nobody wrote is a commit
    message nobody meant.
    """
    from wringer import spec as spec_module

    spec_path = root / spec_module.SPEC_FILENAME
    if spec_path.is_file():
        try:
            loaded = spec_module.load(spec_path)
        except spec_module.SpecError:
            pass
        else:
            return loaded.title
    return task or f"wringer: verified change {run_dir.name}"


def _mr_body(
    run_dir: Path, root: Path, state: git.RepoState, carried: int
) -> str:
    """The receipts, which is what the OKR actually promises.

    The gate table and where the bundle is — **never raw gate logs**. A bundle
    may hold whatever a gate printed (SECURITY.md), and an MR body is public.
    """
    lines = ["## What was verified", ""]
    try:
        rows = evidence.read_gate_results(run_dir)
    except evidence.EvidenceError:
        rows = []
    if rows:
        lines += ["| gate | status | exit | duration |", "|---|---|---|---|"]
        for _, row in rows:
            lines.append(
                f"| {row.get('gate_id')} | {row.get('status')} "
                f"| {row.get('exit_code')} | {row.get('duration_ms', 0) / 1000:.1f}s |"
            )
    else:
        lines.append("_No gate results were recorded._")

    verdict = _verdict(root)
    if verdict:
        lines += ["", "## Judge", "", verdict]

    shown = run_dir.name
    lines += [
        "",
        "## Evidence",
        "",
        f"- run: `{shown}`",
        f"- commit verified at: `{state.head_sha or 'unknown'}`",
        f"- files changed: {carried}",
        "",
        "The full bundle — `evidence.jsonl`, `manifest.json`, `summary.md`, "
        "`diff.patch` and per-gate logs — stays with the machine that ran it. "
        "Gate output is deliberately not reproduced here: a bundle may contain "
        "whatever a gate printed.",
        "",
        f"_Opened by `wring deliver`. {summary.SUMMARY_FILENAME} in the bundle "
        "is the human-readable report._",
        "",
    ]
    return "\n".join(lines)


def _verdict(root: Path) -> str | None:
    from wringer import judge

    root_dir = root / judge.VERDICTS_DIRNAME
    found = evidence.latest_run(root_dir) if root_dir.is_dir() else None
    if found is None:
        return None
    try:
        recorded = json.loads(
            (found / judge.VERDICT_FILENAME).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if not recorded.get("verdict"):
        return None
    note = f" — {recorded['note']}" if recorded.get("note") else ""
    return f"**{recorded['verdict']}**{note}"


@dataclass(frozen=True)
class Bundle:
    """`.wringer/deliveries/<id>/`. Owns the redactor, so every write scrubs."""

    directory: Path
    delivery_id: str
    started_at: datetime
    redactor: Redactor = Redactor()

    @classmethod
    def create(
        cls, deliveries_root: Path, redactor: Redactor | None = None
    ) -> Bundle:
        started_at = datetime.now().astimezone()
        try:
            deliveries_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DeliverError(f"cannot create {deliveries_root}: {exc}") from exc
        for _ in range(64):
            delivery_id = evidence.new_run_id(started_at)
            directory = deliveries_root / delivery_id
            try:
                directory.mkdir(exist_ok=False)
            except FileExistsError:
                continue
            except OSError as exc:
                raise DeliverError(f"cannot create {directory}: {exc}") from exc
            return cls(directory, delivery_id, started_at, redactor or Redactor())
        raise DeliverError(f"could not allocate a directory under {deliveries_root}")

    def event(self, event_type: str, **fields: Any) -> None:
        """Appended BEFORE the git write it describes (condition 5)."""
        scrubbed = evidence.deep_scrub(self.redactor, fields)
        path = self.directory / EVENTS_FILENAME
        line = json.dumps(
            {
                "type": event_type,
                "ts": evidence.timestamp(),
                "prev_hash": evidence.chain_head(path),
                **scrubbed,
            }
        )
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def write_plan(self, planned: Plan) -> None:
        write = self.redactor.scrub
        (self.directory / BRANCH_FILENAME).write_text(
            write(planned.branch) + "\n", encoding="utf-8"
        )
        (self.directory / COMMIT_FILENAME).write_text(
            write(planned.commit_message), encoding="utf-8"
        )
        (self.directory / MR_FILENAME).write_text(
            write(planned.mr_body), encoding="utf-8"
        )
        (self.directory / PATCH_FILENAME).write_text(
            write(planned.patch), encoding="utf-8"
        )
        (self.directory / COMMANDS_FILENAME).write_text(
            "\n".join(write(c) for c in planned.commands) + "\n", encoding="utf-8"
        )

    def read_commit_message(self, planned: Plan) -> str:
        """What `--send` commits — read back from disk, not from memory.

        The dry run wrote it and invited the human to edit it. Reading the
        object instead of the file would quietly discard that edit.
        """
        path = self.directory / COMMIT_FILENAME
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return planned.commit_message

    def write_manifest(
        self, mode: str, planned: Plan, delivered: dict[str, Any]
    ) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "delivery_id": self.delivery_id,
            "started_at": self.started_at.replace(microsecond=0).isoformat(),
            "mode": mode,
            "run_dir": planned.run_dir,
            "branch": planned.branch,
            "base": planned.base,
            "remote": planned.remote,
            "files": list(planned.changed_files),
            # What authorised this delivery, so `wring attest` has something
            # to point at. Null when no spec drove it — a delivery can be a
            # plain verified change, and saying "none" is honest.
            "spec_sha256": planned.spec_sha256,
            "result": delivered,
        }
        (self.directory / MANIFEST_FILENAME).write_text(
            json.dumps(evidence.deep_scrub(self.redactor, payload), indent=2) + "\n",
            encoding="utf-8",
        )


def send(
    root: Path,
    bundle: Bundle,
    planned: Plan,
    push: bool = True,
) -> dict[str, Any]:
    """Create the branch, commit, and push. Every step logged before it runs.

    **The branch is undone if the commit never happens, and never once it
    has.** Those two halves are one rule with one boundary.

    The branch is created before the commit, so anything that goes wrong in
    between used to leave the user standing on a branch Wringer had made and
    walked away from, changes still uncommitted, with a git fatal for an
    explanation — and the next `wring deliver` then refused, because
    condition 1 is *only a branch Wringer created* and that name now exists.
    Two causes were confirmed (a case-only rename, an over-long argv) and
    there are obviously others: a pre-commit hook, a full disk. So the repair
    is at the failure rather than at each cause.

    After the commit lands, nothing is rolled back, and that is deliberate.
    The branch then holds real work; a push that fails afterwards is a state
    to report — the CLI already does — not one to delete. Deleting there
    would destroy the commit, which is a larger power than this slice was
    granted.
    """
    done: dict[str, Any] = {"branch": None, "commit": None, "pushed": False}
    # Where to put the user back. Captured BEFORE anything moves, and as a ref
    # rather than a name so a detached HEAD is restored detached.
    was_on = _read(root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    was_at = _read(root, ["rev-parse", "HEAD"])

    bundle.event("branch.planned", branch=planned.branch, base=planned.base)
    _run(root, ["switch", "--create", planned.branch])
    done["branch"] = planned.branch
    bundle.event("branch.created", branch=planned.branch)

    try:
        done["commit"] = _commit(root, bundle, planned)
    except BaseException:
        # BaseException, not Exception: a Ctrl-C between the two commands is
        # the likeliest way to reach here, and it strands a branch exactly the
        # same way an error does.
        _abandon(root, bundle, planned.branch, was_on, was_at)
        raise
    bundle.event("commit.written", sha=done["commit"])

    if push:
        bundle.event("push.planned", remote=planned.remote, branch=planned.branch)
        # No force. Not here, not anywhere — a test greps the whole program.
        _run(root, ["push", "--set-upstream", planned.remote, planned.branch])
        done["pushed"] = True
        bundle.event("push.done", remote=planned.remote, branch=planned.branch)

    return done


def _abandon(
    root: Path,
    bundle: Bundle,
    branch: str,
    was_on: str | None,
    was_at: str | None,
) -> None:
    """Put the user back and remove the branch that never got a commit.

    Best-effort throughout, and it must never raise: it runs from an `except`
    block, and a failure here would replace the real diagnosis with a second,
    less useful one. What it could not undo is recorded instead, so the
    delivery bundle says what state the tree was left in.

    Deleting is safe precisely because it only runs when the commit did not:
    the branch is still exactly where `switch --create` put it, so `-D`
    discards nothing that was not already reachable from where it started.
    """
    # NEVER `--force`. `git switch --force` is `--discard-changes`, and the
    # whole reason this function is running is that the user's work did not
    # get committed — throwing it away to tidy up a branch would be a far
    # worse bug than the stranded branch. Caught by the test below, which
    # asserts the change is still there to deliver afterwards.
    #
    # A plain switch is safe here and cannot conflict: the abandoned branch
    # was created at the commit we are going back to, so the two refs name the
    # same tree and git carries the modifications across untouched. If it
    # somehow refuses, the branch stays and the ledger says so.
    restored = False
    try:
        if was_on:
            _run(root, ["switch", was_on])
            restored = True
        elif was_at:
            _run(root, ["switch", "--detach", was_at])
            restored = True
    except DeliverError:
        restored = False

    removed = False
    if restored:
        try:
            _run(root, ["branch", "-D", branch])
            removed = True
        except DeliverError:
            removed = False

    try:
        bundle.event(
            "branch.abandoned",
            branch=branch,
            restored=restored,
            deleted=removed,
        )
    except OSError:  # the bundle is not worth a second exception either
        pass


def _commit(root: Path, bundle: Bundle, planned: Plan) -> str | None:
    """Stage the planned paths and commit exactly them."""
    bundle.event("commit.planned", files=list(planned.changed_files))
    # Stage exactly what the plan said it would carry — never `add --all`.
    # A repo that ran `wring init` has `.wringer/` gitignored, but `wring
    # verify` alone writes no .gitignore, so `add --all` swept the whole
    # evidence bundle into the commit and pushed it to a public branch.
    # SECURITY.md says a bundle may hold whatever a gate printed, and the
    # README promises nothing uploads, ever.
    #
    # Paths arrive NUL-separated on stdin rather than as argv: they come from
    # the repository, so there is no length and no character this has to hope
    # about. `--all` still applies to them, so a deletion stages as one.
    #
    # Only the paths `git add` can actually match are passed to it. A rename's
    # source is a change (the file was deleted) and belongs in the commit, but
    # `git mv` has already removed it from BOTH the worktree and the index, so
    # `git add` answers "pathspec did not match any files" and exits 128 —
    # taking the whole delivery down. Nothing needs adding for those: the
    # deletion is staged already, and `commit --only` below names them anyway,
    # which is what records it (verified: the commit lands as `R100 src -> dst`).
    #
    # A deletion the user made WITHOUT git — plain `rm` — is different: the
    # path is still in the index, so it matches, and `--all` stages it. That
    # case must keep working, which is why this filters on matchability rather
    # than on "the file exists".
    addable = _matchable(root, planned.changed_files)
    if addable:
        _run(
            root,
            ["add", "--all", "--pathspec-from-file=-", "--pathspec-file-nul"],
            stdin="\0".join(addable),
        )
    # `--only` commits the named paths and NOTHING else. Staging the right
    # paths was not enough: `git commit` commits the whole index, so anything
    # the user had already staged — a `.wringer/` bundle, an unrelated
    # half-finished edit — rode along into a public branch and into an MR
    # claiming those files were verified. The plan's file list IS the commit.
    #
    # The message comes from the file rather than stdin because stdin is
    # carrying the pathspecs; `--file -` and `--pathspec-from-file=-` cannot
    # both have it. That file is also the one the dry run invited the human to
    # edit, so reading it here is the behaviour we want anyway.
    message_file = bundle.directory / COMMIT_FILENAME
    if not message_file.is_file():
        message_file.write_text(planned.commit_message, encoding="utf-8")
    _run(
        root,
        ["commit", "--only", "--file", str(message_file),
         "--pathspec-from-file=-", "--pathspec-file-nul"],
        stdin="\0".join(planned.changed_files),
    )
    return _read(root, ["rev-parse", "HEAD"])


# How many bytes of pathspec one `ls-files` call may carry. ARG_MAX is
# 1048576 on the machine this was measured on, and both the environment and
# git's own arguments come out of the same allowance; a few tens of kilobytes
# is comfortably under every modern platform's limit while keeping the number
# of subprocesses small. The count cap is for the other shape — tens of
# thousands of two-character paths, which no byte budget would ever stop.
_PATHSPEC_BYTES = 64 * 1024
_PATHSPEC_COUNT = 1000


def _batched(paths: tuple[str, ...]) -> list[list[str]]:
    """`paths` split into chunks each safe to pass as argv."""
    chunks: list[list[str]] = []
    current: list[str] = []
    size = 0
    for path in paths:
        cost = len(path.encode("utf-8", "surrogateescape")) + 1
        if current and (
            size + cost > _PATHSPEC_BYTES or len(current) >= _PATHSPEC_COUNT
        ):
            chunks.append(current)
            current, size = [], 0
        current.append(path)
        size += cost
    if current:
        chunks.append(current)
    return chunks


def _matchable(root: Path, paths: tuple[str, ...]) -> list[str]:
    """The subset of `paths` that `git add` can resolve to something.

    `git add` matches against the worktree and the index. A path in neither —
    a rename source, already removed from both by `git mv` — makes it exit
    128 for the whole pathspec list, so those are filtered out here rather
    than allowed to abort a delivery that is otherwise correct.

    **Batched, because the pathspec used to be one argv.** Measured: 4500
    paths of ~200 characters went through and 6000 raised `[Errno 7] Argument
    list too long`, which arrived as a failed delivery AFTER the branch had
    been created. A generated tree, a vendored dependency, a `dist/` nobody
    gitignored — none of those are exotic.

    `add` and `commit` avoid this by taking their pathspecs on stdin, and the
    obvious fix was to do the same here. `git ls-files` has no
    `--pathspec-from-file`: git 2.50.1 answers ``unknown option
    `pathspec-from-file=-'`` and exits 129. So this batches instead.
    """
    indexed: set[str] = set()
    for chunk in _batched(paths):
        code, listed = _git(root, ["ls-files", "-z", "--", *chunk])
        if code == 0:
            indexed.update(listed.split("\0"))
    return [path for path in paths if path in indexed or (root / path).exists()]


def _run(root: Path, args: list[str], stdin: str | None = None) -> None:
    code, out = _git(root, args, stdin=stdin)
    if code != 0:
        raise DeliverError(f"git {' '.join(args)} failed (exit {code}): {out}")


def _read(root: Path, args: list[str]) -> str | None:
    code, out = _git(root, args)
    return out.strip() if code == 0 else None


def _git(
    root: Path, args: list[str], stdin: str | None = None, check: bool = True
) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise DeliverError(f"git {' '.join(args)} did not finish") from exc
    except OSError as exc:
        raise DeliverError(f"could not run git: {exc}") from exc
    return proc.returncode, (proc.stderr or proc.stdout).strip()
