"""The rubric judge — `wringer.judge.v1` (SPEC_JUDGE_V0.md).

Reads a *finished* evidence bundle plus a rubric and produces a structured
verdict. It is a standalone command over a completed artifact, the way
`wring verify` shipped before `wring run`.

That shape is what makes worker/judge isolation **physical**: this module
reads `.wringer/runs/<id>/`, while everything a worker ever said lives in
`.wringer/loops/<id>/iterations/`. The two trees do not overlap, so a
worker's reasoning cannot reach a judge — there is no code path along which
it could travel. `Packet` below is the type-level expression of that: a
frozen dataclass with a fixed field set, and no field that could carry a
loop, a brief, or a worker log.

**Dry run is the default.** `request.json` is written before the transport
is ever consulted, so what leaves the machine is auditable rather than
asserted, and `--send` is the same code path continuing one step further.
`send()` below is one of the two functions in Wringer that open a
socket; `forge.request` is the other (SPEC_GET_V0.md §7).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from wringer import evidence
from wringer.redact import Redactor
from wringer.rubric import Criterion, Rubric

SCHEMA_VERSION = "wringer.judge.v1"
VERDICTS_DIRNAME = Path(".wringer") / "verdicts"
VERDICT_FILENAME = "verdict.json"
REQUEST_FILENAME = "request.json"
RESPONSE_FILENAME = "response.json"
SUMMARY_FILENAME = "summary.md"

# The diff is the bulk of what travels. Beyond this it is truncated with a
# declared marker — a judge that needs more than 64 KB of patch is being
# asked the wrong question.
MAX_DIFF_BYTES = 64 * 1024

PASS, FAIL, NEEDS_HUMAN = "pass", "fail", "needs_human"


class JudgeError(Exception):
    """The judgment could not be made (CLI exit code 2)."""


class TransportFailed(Exception):
    """The endpoint could not be reached, or did not answer usefully.

    Never a verdict: the caller turns this into `needs_human`, because
    "nothing competent looked at the evidence" is not "the evidence says no".
    """


@dataclass(frozen=True)
class Packet:
    """**The closed list**: everything the judge is allowed to see.

    A frozen dataclass with a fixed field set, built by one function from one
    bundle directory and one rubric. There is no field here that could carry
    a worker's output, so passing one is a type error rather than a review
    comment — which is the difference between isolation that is structural
    and isolation that is merely intended.
    """

    rubric_title: str
    criteria: tuple[dict[str, Any], ...]
    diff: str
    diff_truncated: bool
    gates: tuple[dict[str, Any], ...]
    head_sha: str | None
    branch: str | None
    dirty: bool


@dataclass(frozen=True)
class Verdict:
    verdict: str | None  # None in a dry run: nothing judged anything
    criteria: tuple[dict[str, Any], ...] = ()
    note: str = ""


def gates_passed(evidence_dir: Path) -> tuple[bool, str | None]:
    """Whether the bundle's required gates passed, and what failed if not.

    A judge has nothing to add when the deterministic gates already said no,
    so this is a precondition rather than an input.
    """
    try:
        manifest = evidence.read_manifest(evidence_dir)
    except evidence.EvidenceError as exc:
        raise JudgeError(str(exc)) from exc
    result = manifest.get("result", {})
    return result.get("status") == "passed", result.get("failed_gate")


def build_packet(evidence_dir: Path, rubric: Rubric) -> Packet:
    """Assemble the closed list from a bundle and a rubric — nothing else."""
    try:
        manifest = evidence.read_manifest(evidence_dir)
        rows = evidence.read_gate_results(evidence_dir)
    except evidence.EvidenceError as exc:
        raise JudgeError(str(exc)) from exc

    diff_path = evidence_dir / evidence.DIFF_FILENAME
    diff, truncated = "", False
    if diff_path.is_file():
        raw = diff_path.read_bytes()
        if len(raw) > MAX_DIFF_BYTES:
            raw = raw[:MAX_DIFF_BYTES]
            truncated = True
        diff = raw.decode("utf-8", errors="replace")
        if truncated:
            diff += "\n[wringer: diff truncated at 64 KB for the judge]\n"

    repo = manifest.get("repo", {})
    return Packet(
        rubric_title=rubric.title,
        criteria=tuple(
            {"id": c.id, "title": c.title, "guidance": c.guidance,
             "required": c.required, "human": c.human}
            for c in rubric.criteria
        ),
        diff=diff,
        diff_truncated=truncated,
        gates=tuple(
            {
                "id": row.get("gate_id"),
                "command": row.get("command"),
                "exit_code": row.get("exit_code"),
                "duration_ms": row.get("duration_ms"),
                "status": row.get("status"),
            }
            for _, row in rows
        ),
        head_sha=repo.get("head_sha"),
        branch=repo.get("branch"),
        dirty=bool(repo.get("dirty")),
    )


def render_request(packet: Packet, model: str, max_output_tokens: int) -> dict:
    """The exact chat-completions body. Built from a Packet and nothing else.

    Criteria marked `human` are left out entirely: they are not in the prompt,
    not in the reply format, and so cannot be answered. A judge that was never
    asked cannot be said to have guessed.
    """
    asked = [c for c in packet.criteria if not c["human"]]
    criteria_lines = "\n".join(
        f"- {c['id']} ({'required' if c['required'] else 'optional'}): "
        f"{c['title']}" + (f" — {c['guidance']}" if c["guidance"] else "")
        for c in asked
    )
    gate_lines = "\n".join(
        f"- {g['id']}: {g['status']} (exit {g['exit_code']}, `{g['command']}`)"
        for g in packet.gates
    ) or "- (none recorded)"

    ids = [c["id"] for c in asked]
    user = (
        f"# Rubric: {packet.rubric_title}\n\n"
        f"Judge the change below against each criterion.\n\n"
        f"## Criteria\n{criteria_lines}\n\n"
        f"## Gates (all passed — the change works; you are judging whether it "
        f"is the right change)\n{gate_lines}\n\n"
        f"## Repo\n- HEAD: {packet.head_sha}\n- branch: {packet.branch}\n"
        f"- dirty: {packet.dirty}\n\n"
        f"## Diff\n```diff\n{packet.diff}\n```\n\n"
        f"## Reply format\nReturn ONLY a JSON object:\n"
        f'{{"criteria": [{{"id": "<one of: {", ".join(ids)}>", "met": true, '
        f'"reason": "<one sentence>"}}]}}\n'
        f"Include every criterion exactly once."
    )
    return {
        "model": model,
        "max_tokens": max_output_tokens,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a code-review judge. You see a diff, the gates it "
                    "already passed, and a rubric. You never see the author's "
                    "reasoning. Answer only with the requested JSON."
                ),
            },
            {"role": "user", "content": user},
        ],
    }


def parse_response(body: Any, rubric: Rubric) -> Verdict:
    """Turn a model reply into a verdict, or `needs_human` if it cannot be.

    Every failure to understand the reply is `needs_human`, never `fail`:
    "the evidence says no" and "nothing competent looked at the evidence"
    are different claims.
    """
    try:
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(_strip_fences(content))
        answers = {a["id"]: a for a in parsed["criteria"]}
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return Verdict(NEEDS_HUMAN, note="the reply could not be parsed")

    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    awaiting: list[str] = []
    for criterion in rubric.criteria:
        if criterion.human:
            # Never asked, so whatever the model volunteered about this id is
            # not read. Unscored is the honest record, not a guess.
            if criterion.required:
                awaiting.append(criterion.id)
            rows.append(_human_row(criterion))
            continue
        answer = answers.get(criterion.id)
        if answer is None or not isinstance(answer.get("met"), bool):
            missing.append(criterion.id)
            rows.append(
                {"id": criterion.id, "met": None, "required": criterion.required,
                 "reason": "not scored by the judge"}
            )
            continue
        rows.append(
            {
                "id": criterion.id,
                "met": answer["met"],
                "required": criterion.required,
                "reason": str(answer.get("reason", ""))[:500],
            }
        )

    if missing:
        return Verdict(
            NEEDS_HUMAN,
            tuple(rows),
            f"criteria not scored: {', '.join(missing)}",
        )
    # A definite no outranks a pending look: the change is rejected either way,
    # and "fail" is the more actionable of the two.
    failed = [r["id"] for r in rows if r["required"] and r["met"] is False]
    if failed:
        return Verdict(FAIL, tuple(rows), f"required criteria unmet: "
                                          f"{', '.join(failed)}")
    if awaiting:
        return Verdict(
            NEEDS_HUMAN,
            tuple(rows),
            f"required criteria only a human can score: {', '.join(awaiting)}",
        )
    return Verdict(PASS, tuple(rows))


def _human_row(criterion: Criterion) -> dict[str, Any]:
    return {
        "id": criterion.id,
        "met": None,
        "required": criterion.required,
        "reason": "needs a human — not a criterion a judge can score",
    }


def nothing_to_ask(rubric: Rubric) -> Verdict | None:
    """The verdict when there is no question to send, or None to carry on.

    A rubric whose every criterion is `human` has nothing to ask a model.
    Opening a socket to ask it anyway would be a network call made for
    appearance rather than for an answer.
    """
    if rubric.machine_criteria:
        return None
    return Verdict(
        NEEDS_HUMAN,
        tuple(_human_row(c) for c in rubric.criteria),
        "every criterion needs a human, so nothing was sent",
    )


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:-1] if len(lines) > 2 and lines[-1].startswith("```") \
            else lines[1:]
        return "\n".join(lines)
    return stripped


def send(request: dict, endpoint: str, timeout: int, api_key: str | None) -> dict:
    """Post the request and return the parsed reply.

    **One of the two functions in Wringer that open a socket** — deliberately,
    so
    that `grep -rn build_opener src/` has exactly two answers — this and
    `forge.request`, added in P3 and named in SPEC_GET_V0.md §7. It is reached only
    from `wring judge --send`, only when a repo declared an endpoint, and
    only after `request.json` is already on disk.

    Redirects are not followed: a redirect could move a diff to a host the
    repo never declared, and the endpoint safety rules were checked against
    the URL that was written down.
    """
    import urllib.error
    import urllib.request

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    posted = urllib.request.Request(
        endpoint,
        data=json.dumps(request).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    class _NoRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None

    opener = urllib.request.build_opener(_NoRedirects)

    # `timeout=` bounds each socket OPERATION, not the exchange: an endpoint
    # that dribbles one byte before every expiry resets it indefinitely, so
    # `judge.timeout` bounded no total. Invariant 3 — nothing waits without a
    # deadline — and this is the deadline.
    import threading

    result: list[str] = []
    failure: list[Exception] = []

    def exchange() -> None:
        try:
            with opener.open(posted, timeout=timeout) as reply:
                result.append(reply.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
            failure.append(exc)

    caller = threading.Thread(target=exchange, daemon=True)
    caller.start()
    caller.join(timeout)
    if caller.is_alive():
        raise TransportFailed(
            f"the endpoint did not finish within {timeout}s"
        )
    if failure:
        # A transport failure is not a verdict. The caller turns this into
        # needs_human, never fail.
        raise TransportFailed(str(failure[0])) from failure[0]
    body = result[0] if result else ""

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise TransportFailed(f"the endpoint did not return JSON: {exc}") from exc


@dataclass(frozen=True)
class Bundle:
    """`.wringer/verdicts/<id>/`. Owns the redactor, so every write scrubs."""

    directory: Path
    verdict_id: str
    started_at: datetime
    redactor: Redactor = Redactor()

    @classmethod
    def create(
        cls,
        verdicts_root: Path,
        now: datetime | None = None,
        redactor: Redactor | None = None,
    ) -> Bundle:
        started_at = now if now is not None else datetime.now().astimezone()
        try:
            verdicts_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise JudgeError(f"cannot create {verdicts_root}: {exc}") from exc
        for _ in range(64):
            verdict_id = evidence.new_run_id(started_at)
            directory = verdicts_root / verdict_id
            try:
                directory.mkdir(exist_ok=False)
            except FileExistsError:
                continue
            except OSError as exc:
                raise JudgeError(f"cannot create {directory}: {exc}") from exc
            return cls(directory, verdict_id, started_at, redactor or Redactor())
        raise JudgeError(f"could not allocate a directory under {verdicts_root}")

    def write_request(self, request: dict) -> Path:
        """Written BEFORE any socket is opened, so what would leave the
        machine is auditable rather than asserted."""
        path = self.directory / REQUEST_FILENAME
        scrubbed = evidence.deep_scrub(self.redactor, request)
        path.write_text(json.dumps(scrubbed, indent=2) + "\n", encoding="utf-8")
        return path

    def write_response(self, body: Any) -> Path:
        path = self.directory / RESPONSE_FILENAME
        scrubbed = evidence.deep_scrub(self.redactor, body)
        path.write_text(json.dumps(scrubbed, indent=2) + "\n", encoding="utf-8")
        return path

    def write_verdict(
        self,
        mode: str,
        evidence_dir: str,
        rubric: Rubric,
        endpoint: str,
        model: str,
        verdict: Verdict,
        duration_ms: int,
    ) -> Path:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "verdict_id": self.verdict_id,
            "started_at": self.started_at.replace(microsecond=0).isoformat(),
            "mode": mode,
            "evidence_dir": evidence_dir,
            "rubric": {"path": rubric.path, "sha256": rubric.sha256},
            "endpoint": self.redactor.scrub(endpoint),
            "model": model,
            "verdict": verdict.verdict,
            "criteria": list(verdict.criteria),
            "note": verdict.note,
            "duration_ms": duration_ms,
        }
        path = self.directory / VERDICT_FILENAME
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    def write_summary(
        self, mode: str, evidence_dir: str, rubric: Rubric, verdict: Verdict
    ) -> Path:
        lines = [
            f"# wring judge — {self.verdict_id}",
            "",
            f"- mode: **{mode}**",
            f"- evidence: `{evidence_dir}`",
            f"- rubric: `{rubric.path}` (`{rubric.sha256[:12]}`)",
            f"- verdict: **{verdict.verdict or 'none — nothing was sent'}**",
        ]
        if verdict.note:
            lines.append(f"- note: {verdict.note}")
        if verdict.criteria:
            lines += [
                "",
                "| criterion | required | met | reason |",
                "|---|---|---|---|",
            ]
            for row in verdict.criteria:
                met = {True: "yes", False: "no", None: "—"}[row["met"]]
                lines.append(
                    f"| {row['id']} | {'yes' if row['required'] else 'no'} "
                    f"| {met} | {row['reason']} |"
                )
        elif mode == "dry_run":
            lines += [
                "",
                "No criteria were scored: this was a dry run, so the request "
                f"was built and written to `{REQUEST_FILENAME}` and nothing "
                "was sent.",
            ]
        else:
            # A live judgment that scored nothing is NOT a dry run, and a
            # summary that said so would be a false claim in an evidence
            # artifact — the one thing this repo cannot do.
            lines += [
                "",
                "No criteria were scored, and this was **not** a dry run: the "
                f"endpoint was contacted. `{REQUEST_FILENAME}` holds what was "
                "sent; the note above says why nothing came back usable.",
            ]
        path = self.directory / SUMMARY_FILENAME
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
