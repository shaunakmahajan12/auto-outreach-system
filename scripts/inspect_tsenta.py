"""Milestone 1: OAuth inspection with optional allowlisted application reads.

Uses the public discovery documents advertised by Tsenta's MCP server.
Tokens stay in memory and are discarded on exit. No dependencies.
"""
import argparse
import base64
import hashlib
import http.server
import json
import os
from pathlib import Path
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.tsenta_transport import ORIGIN, RESOURCE, validate_read, private_json, NoRedirect, request  # noqa: E402,F401


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-applications", action="store_true", help="Read one history page, then accept allowlisted read commands on stdin")
    options = parser.parse_args()
    os.umask(0o077)
    protected, _ = request(ORIGIN + "/.well-known/oauth-protected-resource/api/v1/mcp")
    if protected.get("resource") != RESOURCE or ORIGIN not in protected.get("authorization_servers", []):
        raise RuntimeError("Unexpected protected resource metadata")
    metadata, _ = request(ORIGIN + "/.well-known/oauth-authorization-server")
    if metadata.get("issuer") != ORIGIN or "S256" not in metadata.get("code_challenge_methods_supported", []):
        raise RuntimeError("Unsupported OAuth metadata")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    result = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # OAuth codes and state must never enter access logs.

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            valid = parsed.path == "/callback" and secrets.compare_digest(query.get("state", [""])[0], state)
            if not valid:
                self.send_response(400)
                self.end_headers()
                return
            if "code" in query:
                result["code"] = query["code"][0]
            else:
                result["error"] = True
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(b"Authorization response received. You can close this tab and return to Codex.")

    with http.server.HTTPServer(("127.0.0.1", 0), Callback) as server:
        redirect = "http://127.0.0.1:%s/callback" % server.server_port
        registration, _ = request(metadata["registration_endpoint"], {
            "client_name": "Application Outreach Assistant — capability inspection",
            "redirect_uris": [redirect], "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code"], "response_types": ["code"],
        })
        auth_url = metadata["authorization_endpoint"] + "?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": registration["client_id"],
            "redirect_uri": redirect, "state": state, "code_challenge": challenge,
            "code_challenge_method": "S256", "resource": RESOURCE,
        })
        print("Sign in through Tsenta and approve this inspection client:\n" + auth_url, flush=True)
        server.timeout = 1
        deadline = time.monotonic() + 600
        while not result and time.monotonic() < deadline:
            server.handle_request()
        if "code" not in result:
            raise RuntimeError("Authorization declined or timed out; no account data accessed")
    token, _ = request(metadata["token_endpoint"], {
        "grant_type": "authorization_code", "code": result.pop("code"),
        "client_id": registration["client_id"], "redirect_uri": redirect,
        "code_verifier": verifier, "resource": RESOURCE,
    }, form=True)
    headers = {"Authorization": "Bearer " + token["access_token"], "Accept": "application/json, text/event-stream"}
    initialized, response_headers = request(RESOURCE, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "outreach-capability-check", "version": "0.1.0"}},
    }, headers)
    if "error" in initialized:
        raise RuntimeError("MCP initialization failed; response not logged")
    for key, value in response_headers.items():
        if key.lower() == "mcp-session-id":
            headers["Mcp-Session-Id"] = value
    headers["MCP-Protocol-Version"] = initialized["result"]["protocolVersion"]
    request(RESOURCE, {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers)
    tools = []
    cursor = None
    seen = set()
    for page in range(100):
        response, _ = request(RESOURCE, {"jsonrpc": "2.0", "id": page + 2,
            "method": "tools/list", "params": {"cursor": cursor} if cursor else {}}, headers)
        if "error" in response:
            raise RuntimeError("Tool discovery failed; response not logged")
        tools.extend(response["result"].get("tools", []))
        cursor = response["result"].get("nextCursor")
        if not cursor:
            break
        if cursor in seen:
            raise RuntimeError("Repeated tool-list cursor")
        seen.add(cursor)
    else:
        raise RuntimeError("Tool-list page limit exceeded")
    output = Path(__file__).resolve().parents[1] / ".local" / "tsenta-tools.json"
    output.parent.mkdir(mode=0o700, exist_ok=True)
    private_json(output, {"tools": tools})
    print("Tool schemas saved privately to .local/tsenta-tools.json. No tools were invoked.", flush=True)
    if options.read_applications:
        discovered = {t["name"]: t for t in tools}
        sequence = 0

        def read_tool(name, arguments):
            nonlocal sequence
            validate_read(name, arguments)
            if discovered.get(name, {}).get("annotations", {}).get("readOnlyHint") is not True:
                raise RuntimeError("Expected read-only capability is unavailable")
            sequence += 1
            response, returned_headers = request(RESOURCE, {
                "jsonrpc": "2.0", "id": 1000 + sequence, "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }, headers)
            destination = output.parent / ("tsenta-read-%03d.json" % sequence)
            # Retain only rate-related headers, never cookies or session credentials.
            limits = {k: v for k, v in returned_headers.items()
                      if k.lower().startswith(("ratelimit", "x-ratelimit")) or k.lower() == "retry-after"}
            private_json(destination, {"tool": name, "arguments": arguments,
                                      "response": response, "rateHeaders": limits})
            print("Read response saved privately to %s" % destination.name, flush=True)

        read_tool("list-applications", {"filter": "all", "page": 1, "limit": 10, "includeCounts": True})
        print("Inspection session remains open. Enter an allowlisted JSON read command, or 'exit'. Tokens stay in memory.", flush=True)
        for line in sys.stdin:
            if line.strip() == "exit":
                break
            try:
                command = json.loads(line)
                read_tool(command["name"], command["arguments"])
            except (ValueError, KeyError, TypeError):
                print("Invalid read command; no request sent.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        print("Tsenta returned HTTP %s at %s. Response body omitted to protect credentials." % (exc.code, urllib.parse.urlsplit(exc.url).path))
        raise SystemExit(1)
    except (OSError, ValueError, KeyError, RuntimeError):
        print("Inspection stopped: network, authorization, or protocol validation failed. No sensitive response logged.")
        raise SystemExit(1)
