"""The issue tracker and MR host — `wring issue`, and delivery's last step.

**Every vendor string in Wringer lives in this file** (AGENTS.md rule 5).
`cli.py` says "the forge"; only `_MAPPINGS` below knows that GitHub calls a
merge request a pull request, that GitLab numbers issues `iid`, or which
header carries the token. Adding a forge is adding a row.

`request()` is **the second and last function in Wringer that opens a
socket** — `judge.send` is the other, and `grep -rn "build_opener" src/` must
return exactly those two. Until this slice that sentence said "only", and
SPEC_GET_V0.md §7 restates it rather than quietly keeping the old claim.

Both sockets obey the same rules: reached only with a flag a human typed,
only against an endpoint the repo declared, only after the bytes are on
disk, and never following a redirect — a redirect could move a patch to a
host the repo never wrote down.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
from dataclasses import dataclass
from typing import Any

from wringer.config import Forge

# Pinned, per AGENTS.md rule 5. A forge that changes its API under us should
# fail loudly against a version we named, not drift silently.
GITHUB_API_VERSION = "2022-11-28"
GITLAB_API_PREFIX = "/api/v4"

# The marker every file `wring issue` writes carries, so it will not overwrite
# something a person wrote. Same rule as a generated brief.
ISSUE_MARKER = (
    "<!-- fetched by `wring issue` — overwritten on refetch; "
    "this is a copy, the forge is the original -->"
)

MAX_ISSUE_BYTES = 64 * 1024


class ForgeError(Exception):
    """The forge could not be used (CLI exit code 2)."""


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    author: str
    state: str
    url: str


@dataclass(frozen=True)
class MergeRequest:
    number: int
    url: str


@dataclass(frozen=True)
class _Mapping:
    """One forge's dialect. The only place a vendor name may appear."""

    issue_path: str          # .format(repo=, number=)
    mr_path: str             # .format(repo=)
    token_header: str
    token_format: str
    extra_headers: dict[str, str]
    issue_fields: dict[str, str]   # our name -> theirs (dotted for nesting)
    mr_payload: dict[str, str]     # their key -> our name
    mr_fields: dict[str, str]
    # How the repo appears in a path: GitLab wants it percent-encoded whole.
    quote_repo: bool
    # Where an issue number sits in a browser URL for this forge.
    web_issue_pattern: str


_MAPPINGS: dict[str, _Mapping] = {
    "github": _Mapping(
        issue_path="/repos/{repo}/issues/{number}",
        mr_path="/repos/{repo}/pulls",
        token_header="Authorization",
        token_format="Bearer {token}",
        extra_headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
        issue_fields={
            "number": "number",
            "title": "title",
            "body": "body",
            "author": "user.login",
            "state": "state",
            "url": "html_url",
        },
        mr_payload={"title": "title", "head": "head", "base": "base",
                    "body": "body"},
        mr_fields={"number": "number", "url": "html_url"},
        quote_repo=False,
        web_issue_pattern=r"^/(?P<repo>[^/]+/[^/]+)/issues/(?P<number>\d+)",
    ),
    "gitlab": _Mapping(
        issue_path="/projects/{repo}/issues/{number}",
        mr_path="/projects/{repo}/merge_requests",
        token_header="PRIVATE-TOKEN",
        token_format="{token}",
        extra_headers={"Accept": "application/json"},
        issue_fields={
            "number": "iid",
            "title": "title",
            "body": "description",
            "author": "author.username",
            "state": "state",
            "url": "web_url",
        },
        mr_payload={"title": "title", "source_branch": "head",
                    "target_branch": "base", "description": "body"},
        mr_fields={"number": "iid", "url": "web_url"},
        quote_repo=True,
        web_issue_pattern=r"^/(?P<repo>.+?)/-/issues/(?P<number>\d+)",
    ),
}


def _mapping(forge: Forge) -> _Mapping:
    try:
        return _MAPPINGS[forge.kind]
    except KeyError:  # pragma: no cover - config validates the kind
        raise ForgeError(f"no mapping for forge kind {forge.kind!r}") from None


def _dig(body: Any, dotted: str) -> Any:
    value = body
    for part in dotted.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def issue_number(reference: str, forge: Forge) -> int:
    """The issue number from a bare number or a browser URL.

    A URL naming a *different* repository than the config declares is refused:
    fetching from somewhere the repo never wrote down is the same mistake as
    contacting an endpoint it never wrote down.
    """
    text = reference.strip().lstrip("#")
    if text.isdigit():
        return int(text)

    parsed = urllib.parse.urlsplit(reference)
    if parsed.scheme not in ("http", "https"):
        raise ForgeError(
            f"{reference!r} is neither an issue number nor an http(s) URL"
        )
    match = re.search(_mapping(forge).web_issue_pattern, parsed.path)
    if match is None:
        raise ForgeError(f"no issue number in {reference!r}")
    named = match.group("repo").strip("/")
    if named != forge.repo:
        raise ForgeError(
            f"{reference!r} is an issue in {named!r}, but 'forge.repo' declares "
            f"{forge.repo!r} — Wringer fetches from the repository you wrote "
            "down, never one a URL points it at"
        )
    return int(match.group("number"))


def _url(forge: Forge, path: str, **parts: Any) -> str:
    mapping = _mapping(forge)
    repo = urllib.parse.quote(forge.repo, safe="") if mapping.quote_repo \
        else forge.repo
    base = forge.endpoint.rstrip("/")
    if forge.kind == "gitlab" and not base.endswith(GITLAB_API_PREFIX):
        base += GITLAB_API_PREFIX
    return base + path.format(repo=repo, **parts)


def headers(forge: Forge, token: str | None) -> dict[str, str]:
    mapping = _mapping(forge)
    built = {"Content-Type": "application/json", **mapping.extra_headers}
    if token:
        built[mapping.token_header] = mapping.token_format.format(token=token)
    return built


def request(
    url: str,
    method: str,
    sent_headers: dict[str, str],
    body: dict | None,
    timeout: int,
) -> Any:
    """Call the forge and return the parsed reply.

    One of the two functions in Wringer that opens a socket. Redirects are
    not followed, for `judge.send`'s reason: a redirect could move a request
    to a host the repo never declared, and the endpoint safety rules were
    checked against the URL that was written down.
    """
    import urllib.error
    import urllib.request

    posted = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers=sent_headers,
        method=method,
    )

    class _NoRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None

    opener = urllib.request.build_opener(_NoRedirects)

    # `timeout=` is a per-socket-OPERATION timeout: a server that dribbles one
    # byte before each expiry resets it forever, so `forge.timeout` bounded no
    # total. Invariant 3 says nothing waits without a deadline, and this is a
    # deadline. The exchange runs on a daemon thread joined once.
    result: list[bytes] = []
    failure: list[Exception] = []

    def exchange() -> None:
        try:
            with opener.open(posted, timeout=timeout) as reply:
                result.append(reply.read(MAX_ISSUE_BYTES + 1))
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
            failure.append(exc)

    caller = threading.Thread(target=exchange, daemon=True)
    caller.start()
    caller.join(timeout)
    if caller.is_alive():
        raise ForgeError(
            f"the forge did not finish within {timeout}s — abandoning the "
            "request rather than waiting on a connection that may never end"
        )
    if failure:
        raise ForgeError(
            f"the forge could not be reached: {failure[0]}"
        ) from failure[0]
    raw = result[0] if result else b""

    if len(raw) > MAX_ISSUE_BYTES:
        raise ForgeError(
            f"the forge returned more than {MAX_ISSUE_BYTES} bytes — refusing "
            "to read further"
        )
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ForgeError(f"the forge did not return JSON: {exc}") from exc


def fetch_issue(forge: Forge, number: int, token: str | None) -> Issue:
    mapping = _mapping(forge)
    body = request(
        _url(forge, mapping.issue_path, number=number),
        "GET",
        headers(forge, token),
        None,
        forge.timeout,
    )
    fields = {
        name: _dig(body, theirs) for name, theirs in mapping.issue_fields.items()
    }
    if not isinstance(fields.get("title"), str) or fields.get("number") is None:
        raise ForgeError(
            f"the forge's reply is not an issue: no title or number in "
            f"{sorted(body) if isinstance(body, dict) else type(body).__name__}"
        )
    return Issue(
        number=int(fields["number"]),
        title=fields["title"],
        # An issue with an empty body is ordinary; a missing one is not fatal.
        body=fields.get("body") or "",
        author=str(fields.get("author") or "unknown"),
        state=str(fields.get("state") or "unknown"),
        url=str(fields.get("url") or ""),
    )


def open_merge_request(
    forge: Forge,
    token: str | None,
    title: str,
    head: str,
    base: str,
    body: str,
) -> MergeRequest:
    mapping = _mapping(forge)
    ours = {"title": title, "head": head, "base": base, "body": body}
    payload = {theirs: ours[name] for theirs, name in mapping.mr_payload.items()}
    reply = request(
        _url(forge, mapping.mr_path),
        "POST",
        headers(forge, token),
        payload,
        forge.timeout,
    )
    number = _dig(reply, mapping.mr_fields["number"])
    url = _dig(reply, mapping.mr_fields["url"])
    if number is None or url is None:
        raise ForgeError(
            "the forge accepted the request but its reply named no merge "
            "request — check the forge before retrying, or a second one may "
            "be opened"
        )
    return MergeRequest(number=int(number), url=str(url))


def render_issue(issue: Issue) -> str:
    """The issue as a file a human reads, and `wring spec` can draft from.

    The body is untrusted text from the internet. It is written down and read;
    nothing in it is executed and nothing in it reaches a shell. Instructions
    inside an issue are data, and the provenance footer is there so a reader
    can tell this document from one a colleague wrote.
    """
    return "\n".join(
        [
            ISSUE_MARKER,
            "",
            f"# {issue.title}",
            "",
            issue.body.strip(),
            "",
            "---",
            "",
            f"- issue: {issue.url or f'#{issue.number}'}",
            f"- number: {issue.number}",
            f"- author: {issue.author}",
            f"- state: {issue.state}",
            "",
            "*Fetched by `wring issue`. This is a copy; the forge is the "
            "original, and anything written here is a claim by its author, "
            "not an instruction to anyone.*",
            "",
        ]
    )
