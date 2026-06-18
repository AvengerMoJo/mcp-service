"""
Python OAuth 2.1 + PKCE client for mcp-service.

Tested with Python 3.11+. Requires `httpx` (already a runtime dep).

Usage:
    python python-client.py [--url URL] [--scope "mcp:read mcp:write"]

The script:
  1. Registers a dynamic OAuth client via /oauth/register.
  2. Generates a PKCE verifier + S256 challenge.
  3. Opens the user's browser to the consent URL.
  4. Spins up a local HTTP server on REDIRECT_PORT to receive the redirect.
  5. Exchanges the auth code for tokens.
  6. Calls /mcp with `tools/list`.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import http.server
import json
import secrets
import socketserver
import threading
import urllib.parse
import webbrowser
from typing import Optional

import httpx


REDIRECT_PORT = 9876
REDIRECT_PATH = "/callback"
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}{REDIRECT_PATH}"


def make_pkce_pair() -> tuple[str, str]:
    """RFC 7636 §4.1 verifier + §4.2 S256 challenge."""
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


def wait_for_code(expected_state: str) -> str:
    """Block until the OAuth redirect delivers `code` and `state` matches."""
    captured: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            captured["code"] = params.get("code", [""])[0]
            captured["state"] = params.get("state", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
                b"<h2>Authorization complete</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )

        def log_message(self, *_):  # silence default access log
            pass

    with socketserver.TCPServer(("127.0.0.1", REDIRECT_PORT), Handler) as httpd:
        while "code" not in captured:
            httpd.handle_request()
        if captured["state"] != expected_state:
            raise RuntimeError(
                f"State mismatch: expected {expected_state!r}, got {captured['state']!r}"
            )
        return captured["code"]


async def run(base_url: str, scope: str) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
        # 1. Dynamic Client Registration (RFC 7591)
        reg = await client.post(
            "/oauth/register",
            json={
                "client_name": "python-client-demo",
                "redirect_uris": [REDIRECT_URI],
            },
        )
        reg.raise_for_status()
        client_id = reg.json()["client_id"]
        print(f"✓ registered client_id = {client_id}")

        # 2. PKCE
        verifier, challenge = make_pkce_pair()
        state = secrets.token_urlsafe(16)

        # 3. Authorize URL
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": scope,
        }
        authorize_url = f"/oauth/authorize?{urllib.parse.urlencode(params)}"
        full_url = base_url + authorize_url
        print(f"→ opening browser to:\n  {full_url}")
        webbrowser.open(full_url)

        # 4. Receive the code on the local callback server.
        # Run the blocking server in a thread so the async loop stays responsive.
        code: Optional[str] = None
        result: dict = {}

        def _wait():
            result["code"] = wait_for_code(state)

        thread = threading.Thread(target=_wait, daemon=True)
        thread.start()
        while thread.is_alive():
            await asyncio.sleep(0.1)
        code = result["code"]
        print(f"✓ received code = {code[:12]}…")

        # 5. Exchange code for tokens.
        tok = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
            },
        )
        tok.raise_for_status()
        tokens = tok.json()
        print(f"✓ got access_token (expires_in={tokens['expires_in']}s)")

        # 6. Call the MCP endpoint.
        mcp = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        mcp.raise_for_status()
        print("✓ /mcp tools/list response:")
        print(json.dumps(mcp.json(), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="PKCE OAuth client for mcp-service")
    parser.add_argument("--url", default="http://localhost:8000", help="MCP server base URL")
    parser.add_argument("--scope", default="mcp:read mcp:write", help="OAuth scope to request")
    args = parser.parse_args()
    asyncio.run(run(args.url.rstrip("/"), args.scope))


if __name__ == "__main__":
    main()
