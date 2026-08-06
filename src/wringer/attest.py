"""`wring attest` and `wring audit` — SPEC_PROVENANCE_V0.md.

> "Who wrote this code, under whose authority, verified how?" — answered by a
> file, checkable offline, by someone who trusts none of us.

`attest` assembles the claim; `audit` checks it. **Neither calls an LLM and
neither touches a network, ever.** These commands *prove* things, so they live
on the never-reaches-a-network side of the line the README draws. There is no
`--send` here and never will be — a test greps this file for the modules that
could open a socket.

The claim, stated whole:

> Change **C** was **authorized** by spec **S**, **proven** by gates **G**
> with recorded results against tree **T**, **judged** against rubric **R**
> with verdict **V**, and **delivered** as branch **B** — and every bundle
> backing those clauses is byte-identical to when it was written.

And what it does NOT claim is in the artifact itself, not only in the docs.
See `LIMITS`: an attestation that reads as stronger than it is would be the
vacuity failure in a new costume, and this project has already ruled once that
a passing artifact must narrate its own emptiness.

Nothing here is signed. That is a decision (SPEC_PROVENANCE_V0 §5 ruling 1),
not an omission: signing in v0 would force a key into CI, and never touching a
credential is the product's most distinctive promise. `attestation.json.sig`
is a SIBLING file so that adding one later is purely additive — every v0
attestation stays valid byte-for-byte, and `audit` ignores a `.sig` it finds
rather than choking on it.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from wringer import evidence

SCHEMA_VERSION = "wringer.attestation.v1"
ATTESTATIONS_DIRNAME = Path(".wringer") / "attestations"
ATTESTATION_FILENAME = "attestation.json"
SIGNATURE_FILENAME = "attestation.json.sig"
SUMMARY_FILENAME = "summary.md"

# Verbatim, and a test fails if it is deleted or reworded. The word
# *attestation* sounds cryptographic, and a reader who assumes it means
# "signed by someone" has been misled by a green thing that means less than it
# looks like.
UNSIGNED_LIMIT = (
    "unsigned — this proves the named bundles are unaltered since they were "
    "written, not who produced them, and not that they were not fabricated "
    "wholesale."
)
LIMITS = (
    UNSIGNED_LIMIT,
    "digests.json cannot cover itself, so whoever owns the disk can rewrite "
    "everything consistently. This is tamper-evidence: a silent edit becomes "
    "a detectable one, and nothing more.",
    "worker identity is recorded, not proven — the loop wrote down a command "
    "or an agent's self-reported name. That is provenance of configuration.",
    "a commit signature is reported exactly as git states it and is never "
    "re-verified here; that needs the reader's own keyring and their trust "
    "root, which is theirs and not ours.",
)

# git's `%G?` alphabet, spelled out so a reader of the artifact does not have
# to know it. Recorded verbatim either way — the mapping is a courtesy, not an
# interpretation, and `audit` reports rather than re-verifies.
SIGNATURE_MEANINGS = {
    "G": "a good signature",
    "B": "a BAD signature",
    "U": "a good signature, unknown validity",
    "X": "a good signature that has expired",
    "Y": "a good signature made by an expired key",
    "R": "a good signature made by a revoked key",
    "E": "a signature that could not be checked (missing key)",
    "N": "no signature",
}

_GIT_TIMEOUT_SECONDS = 10


class AttestError(Exception):
    """The attestation could not be built or read (CLI exit code 2)."""


class Refused(Exception):
    """This bundle cannot be attested, or the audit found a mismatch.

    Exit 1 in both directions. An honest refusal is the product: `wring
    attest` on a doctored bundle saying **no** is the demo.
    """


# --- reading a bundle, carefully -------------------------------------------


@dataclass(frozen=True)
class BundleRef:
    """One bundle an attestation names, re-anchored by digest.

    Bundles link to each other by PATH. The attestation records the sha256 of
    each one's `digests.json`, so from the moment it is written the linkage is
    content-addressed even though the manifests only ever named paths.
    """

    role: str
    path: str
    digests_sha256: str
    files: int


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AttestError(f"cannot read {path}: {exc}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AttestError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise AttestError(f"{path} is not a JSON object")
    return loaded


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_digests(bundle: Path, role: str) -> tuple[str, int]:
    """Re-verify a bundle against its own `digests.json`.

    Returns the digest file's own sha256 and how many files it covers. Raises
    `Refused` when the file is missing, unreadable, or disagrees with what is
    on disk — including a file present in the bundle that the record does not
    mention, which is how content gets ADDED to a bundle after the fact.
    """
    record = bundle / evidence.DIGESTS_FILENAME
    if not record.is_file():
        raise Refused(
            f"the {role} bundle {bundle.name} has no "
            f"{evidence.DIGESTS_FILENAME} — cannot attest what cannot be "
            "checked. Bundles written before 0.3 do not carry one; re-run the "
            "command that produced it"
        )
    try:
        recorded = _read_json(record).get("files", {})
    except AttestError as exc:
        raise Refused(f"the {role} bundle {bundle.name}: {exc}") from exc
    if not isinstance(recorded, dict):
        raise Refused(
            f"the {role} bundle {bundle.name} has a malformed "
            f"{evidence.DIGESTS_FILENAME}"
        )

    on_disk = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != evidence.DIGESTS_FILENAME
    }
    missing = sorted(set(recorded) - on_disk)
    if missing:
        raise Refused(
            f"the {role} bundle {bundle.name} is missing "
            f"{', '.join(missing[:5])}, which its own "
            f"{evidence.DIGESTS_FILENAME} records"
        )
    extra = sorted(on_disk - set(recorded))
    if extra:
        raise Refused(
            f"the {role} bundle {bundle.name} holds {', '.join(extra[:5])}, "
            f"which its own {evidence.DIGESTS_FILENAME} does not record — "
            "something was added to it after it was written"
        )
    for name in sorted(recorded):
        if _sha256(bundle / name) != recorded[name]:
            raise Refused(
                f"{bundle.name}/{name} does not match the digest "
                f"{bundle.name} recorded for it — that file has changed since "
                "the bundle was written"
            )
    return _sha256(record), len(recorded)


def check_chain(ledger: Path, role: str) -> None:
    """Re-walk a ledger's `prev_hash` chain, raising `Refused` on the break.

    Every event carries the sha256 of the previous line's bytes, so altering
    or removing any line breaks every hash after it. `chain_head` wrote them;
    this is the first code that reads them, which is exactly the shape this
    repository keeps finding in itself — a field nothing verified.
    """
    if not ledger.is_file():
        return
    expected = evidence.GENESIS_HASH
    try:
        raw_lines = ledger.read_bytes().split(b"\n")
    except OSError as exc:
        raise Refused(f"cannot read the {role} ledger {ledger.name}: {exc}") from exc

    number = 0
    for raw in raw_lines:
        if not raw.strip():
            continue
        number += 1
        try:
            event = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise Refused(
                f"the {role} ledger {ledger.name} line {number} is not valid "
                f"JSON: {exc}"
            ) from exc
        if event.get("prev_hash") != expected:
            raise Refused(
                f"the {role} ledger {ledger.name} breaks its hash chain at "
                f"line {number}: it records prev_hash "
                f"{str(event.get('prev_hash'))[:12]}… where the line before it "
                f"hashes to {expected[:12]}…. A line has been altered, removed "
                "or inserted"
            )
        expected = hashlib.sha256(raw).hexdigest()


# --- what git says about a commit, recorded and never judged ---------------


def commit_signature(root: Path, commit: str | None) -> dict[str, Any]:
    """What git says about `commit`'s signature — as a FACT, unjudged.

    `git log -1 --format=%G?` yields one character: `G` good, `B` bad, `U`
    good-but-untrusted, `N` none, and a few more. Wringer never verifies a
    signature and never consults a trust store — that is the verifier's job
    and their trust root, not ours. A repo that already signs its commits gets
    a genuine chain for nothing; a repo that does not records `N` and loses
    nothing at all.
    """
    if not commit:
        return {"commit": None, "status": None, "signer": None, "means": None}
    status = _git(root, ["log", "-1", "--format=%G?", commit]) or "N"
    signer = _git(root, ["log", "-1", "--format=%GS", commit]) or None
    status = status.strip()[:1] or "N"
    return {
        "commit": commit,
        "status": status,
        "signer": signer,
        "means": SIGNATURE_MEANINGS.get(status),
    }


def _git(root: Path, args: list[str]) -> str | None:
    """A read-only git call that is never fatal: no git, no repo, no problem."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


# --- building the claim ----------------------------------------------------


def latest_anchor(root: Path) -> Path | None:
    """The newest delivery, else the newest run. None if there is neither."""
    from wringer import deliver

    deliveries = root / deliver.DELIVERIES_DIRNAME
    newest = evidence.latest_run(deliveries) if deliveries.is_dir() else None
    if newest is not None:
        return newest
    runs = root / evidence.RUNS_DIRNAME
    return evidence.latest_run(runs) if runs.is_dir() else None


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _run_dir_of(root: Path, delivery: Path) -> Path:
    """The run a delivery names, resolved against the repo root."""
    manifest = _read_json(delivery / "manifest.json")
    named = manifest.get("run_dir")
    if not isinstance(named, str) or not named:
        raise Refused(
            f"the delivery {delivery.name} does not name the run it delivered, "
            "so there is nothing to attest it against"
        )
    candidate = Path(named)
    return candidate if candidate.is_absolute() else root / candidate


def _verdict_for(root: Path, run_dir: Path) -> Path | None:
    """The newest verdict about THIS run, or None.

    Same matching rule as the merge-request body: a verdict about a different
    change is worse than no verdict, and an attestation is the last place that
    should be loose about it.
    """
    from wringer import judge

    verdicts = root / judge.VERDICTS_DIRNAME
    if not verdicts.is_dir():
        return None
    wanted = {str(run_dir), run_dir.name, _relative(run_dir, root)}
    found = []
    for candidate in verdicts.iterdir():
        if not candidate.is_dir():
            continue
        try:
            recorded = _read_json(candidate / judge.VERDICT_FILENAME)
        except AttestError:
            continue
        named = recorded.get("evidence_dir")
        if isinstance(named, str) and (
            named in wanted or Path(named).name == run_dir.name
        ):
            found.append(candidate)
    if not found:
        return None
    return max(found, key=evidence._started_at)


@dataclass
class Built:
    payload: dict[str, Any]
    refs: list[BundleRef] = field(default_factory=list)


def build(root: Path, anchor: Path, now: datetime | None = None) -> Built:
    """Assemble the attestation for `anchor`, or refuse and say why.

    `anchor` is a delivery directory or a run directory. A delivery names its
    run and its spec; a run carries the tree and the gate results; a verdict
    names the run it judged. Every one of them is re-verified against its own
    `digests.json` here, and only then recorded.
    """
    from wringer import deliver, judge
    from wringer import spec as spec_module

    created = now if now is not None else datetime.now().astimezone()
    refs: list[BundleRef] = []

    delivery: Path | None = None
    if (anchor / deliver.MANIFEST_FILENAME).is_file() and _read_json(
        anchor / deliver.MANIFEST_FILENAME
    ).get("schema_version") == deliver.SCHEMA_VERSION:
        delivery = anchor
        run_dir = _run_dir_of(root, delivery)
    else:
        run_dir = anchor

    if not (run_dir / evidence.MANIFEST_FILENAME).is_file():
        raise Refused(
            f"{_relative(run_dir, root)} is not a Wringer bundle — there is no "
            f"{evidence.MANIFEST_FILENAME} in it"
        )

    # ---- proven_by: the run, its tree, its gates
    digest, count = check_digests(run_dir, "run")
    check_chain(run_dir / evidence.EVIDENCE_FILENAME, "run")
    refs.append(
        BundleRef("run", _relative(run_dir, root), digest, count)
    )
    manifest = _read_json(run_dir / evidence.MANIFEST_FILENAME)
    result = manifest.get("result", {})
    if result.get("status") != "passed":
        failed = result.get("failed_gate")
        raise Refused(
            f"{run_dir.name}'s gates did not pass"
            + (f" (`{failed}` failed)" if failed else "")
            + ". No attestation dresses up a failure"
        )
    _refuse_if_vacuous(run_dir)

    gates = [
        {
            "gate_id": row.get("gate_id"),
            "status": row.get("status"),
            "exit_code": row.get("exit_code"),
        }
        for _, row in evidence.read_gate_results(run_dir)
    ]
    repo = manifest.get("repo", {})
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "attestation_id": evidence.new_run_id(created),
        "created_at": created.replace(microsecond=0).isoformat(),
        # A sibling `.sig` is where a signature goes if one ever arrives, so
        # this stays null forever in v0 rather than becoming a seat somebody
        # is tempted to fill. See the module docstring.
        "signature": None,
        "limits": list(LIMITS),
        "proven_by": {
            "run": _relative(run_dir, root),
            "head_sha": repo.get("head_sha"),
            "branch": repo.get("branch"),
            "dirty": repo.get("dirty"),
            "gates": gates,
        },
    }

    # ---- authorized_by: the spec, and whether it was actually approved
    spec_path = root / spec_module.SPEC_FILENAME
    if spec_path.is_file():
        # `spec_sha256` hashes the file WITHOUT parsing it, so an unapproved
        # spec hashes exactly like an approved one. The clause is about
        # authority, and an unapproved spec is not authority — so it is loaded
        # and the clause is refused rather than quietly made.
        try:
            loaded = spec_module.load(spec_path)
        except Exception as exc:  # SpecError, and anything malformed
            raise Refused(
                f"{spec_module.SPEC_FILENAME} is present but cannot be read "
                f"({exc}), so the change's authority cannot be established"
            ) from exc
        if not loaded.approved:
            raise Refused(
                f"{spec_module.SPEC_FILENAME} says `approved: false`, so "
                "nothing here was authorized. An attestation naming an "
                "unapproved spec would be the interlock defeated by the "
                "command that exists to record it"
            )
        payload["authorized_by"] = {
            "spec": spec_module.SPEC_FILENAME,
            "sha256": spec_module.authorising_sha256(root),
            "approved": True,
        }

    # ---- judged_by: the verdict about THIS run
    verdict_dir = _verdict_for(root, run_dir)
    if verdict_dir is not None:
        digest, count = check_digests(verdict_dir, "verdict")
        refs.append(
            BundleRef("verdict", _relative(verdict_dir, root), digest, count)
        )
        recorded = _read_json(verdict_dir / judge.VERDICT_FILENAME)
        if recorded.get("mode") == "dry_run":
            raise Refused(
                f"the verdict {verdict_dir.name} was a dry run — nothing was "
                "judged, so a `judged by` clause would be theatre. Run 'wring "
                "judge --send', or attest a bundle with no verdict at all"
            )
        payload["judged_by"] = {
            "verdict_dir": _relative(verdict_dir, root),
            "rubric": recorded.get("rubric"),
            "verdict": recorded.get("verdict"),
            "model": recorded.get("model"),
        }

    # ---- delivered_as: the branch and the commit
    delivered_commit: str | None = None
    if delivery is not None:
        digest, count = check_digests(delivery, "delivery")
        check_chain(delivery / deliver.EVENTS_FILENAME, "delivery")
        refs.append(
            BundleRef("delivery", _relative(delivery, root), digest, count)
        )
        recorded = _read_json(delivery / deliver.MANIFEST_FILENAME)
        outcome = recorded.get("result", {})
        delivered_commit = outcome.get("commit")
        payload["delivered_as"] = {
            "delivery_dir": _relative(delivery, root),
            "mode": recorded.get("mode"),
            "branch": recorded.get("branch"),
            "base": recorded.get("base"),
            "commit": delivered_commit,
            "pushed": bool(outcome.get("pushed")),
            "merge_request": outcome.get("merge_request"),
        }

    # ---- the change itself, and free attribution where the repo has it
    named_commit = delivered_commit or repo.get("head_sha")
    payload["change"] = {
        "commit": named_commit,
        "commit_signature": commit_signature(root, named_commit),
    }
    payload["bundles"] = [
        {
            "role": ref.role,
            "path": ref.path,
            "digests_sha256": ref.digests_sha256,
            "files": ref.files,
        }
        for ref in refs
    ]
    return Built(payload, refs)


def _refuse_if_vacuous(run_dir: Path) -> None:
    """Refuse a run whose own gates proved nothing.

    `vacuity.json` is written by `wring verify --prove` (SPEC_VACUITY_V0). The
    hook lands with `attest` rather than with the feature that writes the file,
    because it is a consequence of THIS spec's §3 — and because the alternative
    is a window in which attestations get made over vacuous runs and nobody
    notices. A bundle with no `vacuity.json` is unaffected, exactly as a repo
    that never opted in should be.
    """
    record = run_dir / "vacuity.json"
    if not record.is_file():
        return
    try:
        verdict = _read_json(record).get("verdict")
    except AttestError:
        return  # the digest check already vouched for the file's integrity
    if verdict == "gates_vacuous":
        raise Refused(
            f"{run_dir.name} recorded `gates_vacuous` — its gates passed "
            "without the change too, so they proved nothing. An attestation "
            "over that would be a cryptographic-sounding wrapper around a "
            "green tick that cannot fail. Write a test that fails without your "
            "change, verify again, then attest"
        )


# --- writing it ------------------------------------------------------------


@dataclass(frozen=True)
class Bundle:
    directory: Path
    attestation_id: str

    @classmethod
    def create(cls, root: Path, attestation_id: str) -> Bundle:
        directory = root / ATTESTATIONS_DIRNAME / attestation_id
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise AttestError(f"cannot create {directory}: {exc}") from exc
        return cls(directory, attestation_id)

    def write(self, payload: dict[str, Any]) -> Path:
        path = self.directory / ATTESTATION_FILENAME
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        (self.directory / SUMMARY_FILENAME).write_text(
            render_summary(payload), encoding="utf-8"
        )
        return path


def clause_lines(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """The claim, one clause per line, for the terminal.

    Only the clauses — the limits are printed separately, once, as the `!`
    line, because a reader who sees them twice learns to skip them.
    """
    lines: list[tuple[str, str]] = []
    change = payload.get("change", {})
    if change.get("commit"):
        lines.append(("change", str(change["commit"])[:12]))
    signature = change.get("commit_signature") or {}
    if signature.get("status"):
        lines.append((
            "signed",
            f"{signature['status']} — {signature.get('means') or 'unknown'}"
            + (f", {signature['signer']}" if signature.get("signer") else "")
            + " (git's word, never re-checked here)",
        ))
    authorized = payload.get("authorized_by")
    if authorized:
        lines.append((
            "authorized by",
            f"{authorized['spec']} ({str(authorized.get('sha256'))[:12]}), approved",
        ))
    proven = payload["proven_by"]
    passed = sum(1 for gate in proven["gates"] if gate.get("status") == "passed")
    lines.append((
        "proven by",
        f"{proven['run']} — {passed} gate(s) passed against "
        f"{str(proven.get('head_sha'))[:12]}",
    ))
    judged = payload.get("judged_by")
    if judged:
        rubric = judged.get("rubric") or {}
        lines.append((
            "judged by",
            f"{rubric.get('path')} ({str(rubric.get('sha256'))[:12]}) — "
            f"{judged.get('verdict')}",
        ))
    delivered = payload.get("delivered_as")
    if delivered:
        lines.append((
            "delivered as",
            f"{delivered.get('branch')} -> {delivered.get('base')}"
            + (f" @ {str(delivered['commit'])[:12]}" if delivered.get("commit")
               else f" ({delivered.get('mode')})"),
        ))
    return lines


def render_summary(payload: dict[str, Any]) -> str:
    lines = [
        f"# wring attest — {payload['attestation_id']}",
        "",
        f"- created: {payload['created_at']}",
    ]
    change = payload.get("change", {})
    if change.get("commit"):
        lines.append(f"- change: `{change['commit']}`")
    signature = change.get("commit_signature") or {}
    if signature.get("status"):
        means = signature.get("means") or "unknown"
        lines.append(
            f"- commit signature: `{signature['status']}` — {means}"
            + (f", signer {signature['signer']}" if signature.get("signer") else "")
            + " (recorded as git states it; never re-verified here)"
        )

    authorized = payload.get("authorized_by")
    if authorized:
        lines.append(
            f"- authorized by: `{authorized['spec']}` "
            f"(`{str(authorized.get('sha256'))[:12]}`), approved"
        )
    proven = payload["proven_by"]
    passed = sum(1 for g in proven["gates"] if g.get("status") == "passed")
    lines.append(
        f"- proven by: `{proven['run']}` — {passed} gate(s) passed against "
        f"`{str(proven.get('head_sha'))[:12]}`"
    )
    judged = payload.get("judged_by")
    if judged:
        rubric = judged.get("rubric") or {}
        lines.append(
            f"- judged by: `{rubric.get('path')}` "
            f"(`{str(rubric.get('sha256'))[:12]}`) — **{judged.get('verdict')}**"
        )
    delivered = payload.get("delivered_as")
    if delivered:
        lines.append(
            f"- delivered as: `{delivered.get('branch')}` -> "
            f"`{delivered.get('base')}`"
            + (f" @ `{str(delivered['commit'])[:12]}`" if delivered.get("commit")
               else "")
        )

    lines += ["", "## Bundles", ""]
    lines += ["| role | path | files | digests.json sha256 |", "|---|---|---|---|"]
    for ref in payload["bundles"]:
        lines.append(
            f"| {ref['role']} | `{ref['path']}` | {ref['files']} | "
            f"`{ref['digests_sha256'][:16]}` |"
        )

    lines += ["", "## What this does NOT claim", ""]
    lines += [f"- {limit}" for limit in payload["limits"]]
    lines += [
        "",
        "_Check it yourself, offline, with `wring audit`._",
        "",
    ]
    return "\n".join(lines)


# --- checking it -----------------------------------------------------------


@dataclass
class AuditReport:
    ok: bool
    attestation: str
    checked: list[dict[str, Any]] = field(default_factory=list)
    limits: list[str] = field(default_factory=list)
    signature: str | None = None
    problem: str | None = None


def root_for(attestation_path: Path) -> Path:
    """The repo root a handed-over attestation is sitting in.

    `<root>/.wringer/attestations/<id>/attestation.json` is the layout, so the
    root is four parents up. An attestation that has been moved somewhere else
    is looked for by walking up to the nearest `.wringer/`, and failing that
    the file's own directory is used — `audit` then reports the bundles as
    missing, which is the honest answer rather than a crash.
    """
    resolved = attestation_path.resolve()
    for parent in resolved.parents:
        if parent.name == evidence.WRINGER_DIRNAME and parent.parent is not None:
            return parent.parent
    return resolved.parent


def audit(attestation_path: Path) -> AuditReport:
    """Re-check every claim in an attestation, offline and without config.

    An auditor may not have a `.wringer.yaml` and must not need one: nothing
    in here reads the config, and nothing in here opens a socket.
    """
    payload = _read_json(attestation_path)
    if payload.get("schema_version") != SCHEMA_VERSION:
        return AuditReport(
            ok=False,
            attestation=str(attestation_path),
            problem=(
                f"{attestation_path.name} says it is "
                f"{payload.get('schema_version')!r}, which this version of "
                f"Wringer cannot check. It reads {SCHEMA_VERSION}"
            ),
        )

    limits = [x for x in payload.get("limits", []) if isinstance(x, str)]
    if UNSIGNED_LIMIT not in limits:
        return AuditReport(
            ok=False,
            attestation=str(attestation_path),
            limits=limits,
            problem=(
                "this attestation does not carry the sentence saying what it "
                "does not claim. An attestation that has had its own limits "
                "removed reads as a stronger claim than it is, so it does not "
                "pass"
            ),
        )

    root = root_for(attestation_path)
    checked: list[dict[str, Any]] = []
    refs = payload.get("bundles")
    if not isinstance(refs, list) or not refs:
        return AuditReport(
            ok=False,
            attestation=str(attestation_path),
            limits=limits,
            problem="this attestation names no bundles, so it claims nothing",
        )

    for ref in refs:
        role, named = ref.get("role", "?"), ref.get("path", "")
        bundle = root / named
        if not bundle.is_dir():
            return AuditReport(
                ok=False, attestation=str(attestation_path), limits=limits,
                checked=checked,
                problem=(
                    f"the {role} bundle `{named}` is not here, so nothing about "
                    "it can be re-checked"
                ),
            )
        try:
            digest, count = check_digests(bundle, role)
            for ledger in (
                evidence.EVIDENCE_FILENAME, "delivery.jsonl", "loop.jsonl",
                "fleet.jsonl",
            ):
                check_chain(bundle / ledger, role)
        except Refused as exc:
            return AuditReport(
                ok=False, attestation=str(attestation_path), limits=limits,
                checked=checked, problem=str(exc),
            )
        if digest != ref.get("digests_sha256"):
            return AuditReport(
                ok=False, attestation=str(attestation_path), limits=limits,
                checked=checked,
                problem=(
                    f"the {role} bundle `{named}` has a different "
                    f"{evidence.DIGESTS_FILENAME} from the one this "
                    "attestation names. The bundle's files may agree with its "
                    "own record, but that record is not the one that was "
                    "attested"
                ),
            )
        checked.append({"role": role, "path": named, "files": count})

    problem = _cross_check(root, payload)
    if problem is not None:
        return AuditReport(
            ok=False, attestation=str(attestation_path), limits=limits,
            checked=checked, problem=problem,
        )

    return AuditReport(
        ok=True,
        attestation=str(attestation_path),
        checked=checked,
        limits=limits,
        signature=None,
    )


def _cross_check(root: Path, payload: dict[str, Any]) -> str | None:
    """Every claim in the attestation, re-read from the bundles themselves.

    The digests prove the bundles have not changed. This proves the
    ATTESTATION still says what they say — a hand-edited `verdict: pass` in
    the attestation over an untouched `verdict.json` saying otherwise is
    exactly the forgery a digest check alone would wave through.
    """
    from wringer import deliver, judge

    proven = payload.get("proven_by") or {}
    run_dir = root / str(proven.get("run", ""))
    try:
        manifest = _read_json(run_dir / evidence.MANIFEST_FILENAME)
    except AttestError as exc:
        return str(exc)
    repo = manifest.get("repo", {})
    if repo.get("head_sha") != proven.get("head_sha"):
        return (
            f"the attestation says the gates ran against "
            f"{str(proven.get('head_sha'))[:12]}, and {run_dir.name} records "
            f"{str(repo.get('head_sha'))[:12]}"
        )
    if manifest.get("result", {}).get("status") != "passed":
        return (
            f"the attestation claims proven gates, and {run_dir.name} records "
            f"status {manifest.get('result', {}).get('status')!r}"
        )

    judged = payload.get("judged_by")
    if judged:
        try:
            recorded = _read_json(
                root / str(judged.get("verdict_dir", "")) / judge.VERDICT_FILENAME
            )
        except AttestError as exc:
            return str(exc)
        if recorded.get("verdict") != judged.get("verdict"):
            return (
                f"the attestation says the verdict was "
                f"{judged.get('verdict')!r}, and the verdict bundle records "
                f"{recorded.get('verdict')!r}"
            )

    delivered = payload.get("delivered_as")
    if delivered:
        try:
            recorded = _read_json(
                root / str(delivered.get("delivery_dir", ""))
                / deliver.MANIFEST_FILENAME
            )
        except AttestError as exc:
            return str(exc)
        if recorded.get("branch") != delivered.get("branch"):
            return (
                f"the attestation says branch {delivered.get('branch')!r}, and "
                f"the delivery bundle records {recorded.get('branch')!r}"
            )
        if recorded.get("result", {}).get("commit") != delivered.get("commit"):
            return (
                "the attestation names a different commit from the one the "
                "delivery bundle records"
            )
    return None
