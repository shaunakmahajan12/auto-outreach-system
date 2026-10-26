"""Allowlisted read-only Tsenta MCP transport shared by the app and the inspection CLI."""

import json
import os
import urllib.parse
import urllib.request


ORIGIN = "https://api.autojobs.me"
RESOURCE = ORIGIN + "/api/v1/mcp"


def validate_read(name, args):
    """Fail closed: neither arbitrary MCP tools nor arbitrary arguments are allowed."""
    if not isinstance(args, dict):
        raise ValueError("Arguments must be an object")
    if name == "list-applications":
        if set(args) - {"filter", "page", "limit", "includeCounts"}:
            raise ValueError("Unexpected list argument")
        if args.get("filter", "all") not in {
            "all",
            "submitted",
            "in_flight",
            "needs",
            "failed",
            "skipped",
        }:
            raise ValueError("Invalid filter")
        for field, maximum in (("page", 10000), ("limit", 100)):
            value = args.get(field, 1)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Invalid pagination")
        if type(args.get("includeCounts", True)) is not bool:
            raise ValueError("Invalid count flag")
    elif name == "get-application-status":
        if set(args) - {"applicationId", "include"}:
            raise ValueError("Unexpected status argument")
        value = args.get("applicationId")
        if not isinstance(value, str) or not 1 <= len(value) <= 256:
            raise ValueError("Invalid application id")
        include = args.get("include", [])
        if not isinstance(include, list) or any(
            v not in ("optimizedProfile", "resumePdfUrl") for v in include
        ):
            raise ValueError("Unsupported inclusion")
    else:
        raise ValueError("Tool is not in the read-only allowlist")


def private_json(path, value):
    # Refuse symlinks; set permissions before writing personal data.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(value, handle, indent=2)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Unexpected HTTP redirect; stopped without forwarding credentials")


def request(url, data=None, headers=None, form=False):
    if urllib.parse.urlsplit(url).netloc != "api.autojobs.me" or not url.startswith("https://"):
        raise RuntimeError("Unexpected endpoint origin")
    hdr = {"User-Agent": "ApplicationOutreachAssistant/0.1 (MCP capability inspection)"}
    hdr.update(headers or {})
    if data is not None:
        hdr["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        data = (urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
    req = urllib.request.Request(url, data=data, headers=hdr)
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=30) as response:
        # Bounded responses, including SSE messages from Streamable HTTP.
        if "text/event-stream" in response.headers.get("Content-Type", ""):
            size = 0
            chunks = []
            while True:
                line = response.readline(1_000_001)
                size += len(line)
                if size > 4_000_000:
                    raise RuntimeError("Response exceeds inspection limit")
                if line.startswith(b"data:"):
                    chunks.append(line[5:].strip())
                if not line.strip() and chunks:
                    return json.loads(b"\n".join(chunks)), dict(response.headers)
                if not line:
                    raise RuntimeError("MCP stream ended without a response")
        raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise RuntimeError("Response exceeds inspection limit")
        return (json.loads(raw) if raw else None), dict(response.headers)
