// Node.js (>= 18) OAuth 2.1 + PKCE client for mcp-service.
// No external deps — uses the built-in `fetch` and the global `crypto`.
//
// Usage:
//   node js-integration.mjs             # talks to http://localhost:8000
//   MCP_URL=https://mcp.example.com node js-integration.mjs
//
// The script:
//   1. Registers a dynamic OAuth client.
//   2. Generates a PKCE verifier + S256 challenge.
//   3. Opens the browser to the consent URL.
//   4. Listens on http://localhost:9876/callback for the redirect.
//   5. Exchanges the auth code for tokens.
//   6. Calls /mcp with `tools/list`.

import http from "node:http";
import { URL } from "node:url";
import open from "node:child_process";
import crypto from "node:crypto";

const MCP_URL = process.env.MCP_URL || "http://localhost:8000";
const REDIRECT_PORT = Number(process.env.REDIRECT_PORT || 9876);
const REDIRECT_URI = `http://localhost:${REDIRECT_PORT}/callback`;
const SCOPE = process.env.SCOPE || "mcp:read mcp:write";

const b64url = (buf) =>
  buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

function pkce() {
  const verifier = b64url(crypto.randomBytes(48));
  const challenge = b64url(crypto.createHash("sha256").update(verifier).digest());
  return { verifier, challenge };
}

function randomState() {
  return b64url(crypto.randomBytes(16));
}

async function postForm(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(body).toString(),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST ${url} → ${res.status}: ${text}`);
  }
  return res.json();
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST ${url} → ${res.status}: ${text}`);
  }
  return res.json();
}

function waitForCode(expectedState) {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url, `http://localhost:${REDIRECT_PORT}`);
      if (url.pathname !== "/callback") {
        res.statusCode = 404;
        return res.end();
      }
      const code = url.searchParams.get("code");
      const state = url.searchParams.get("state");
      res.setHeader("Content-Type", "text/html");
      res.end(
        "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>" +
          "<h2>Authorization complete</h2>" +
          "<p>You can close this tab and return to the terminal.</p>" +
          "</body></html>",
      );
      server.close();
      if (state !== expectedState) {
        return reject(new Error(`state mismatch: got ${state}, want ${expectedState}`));
      }
      resolve(code);
    });
    server.listen(REDIRECT_PORT, "127.0.0.1", () => {
      console.log(`✓ callback listener on ${REDIRECT_URI}`);
    });
  });
}

async function main() {
  console.log(`→ talking to ${MCP_URL}`);

  const reg = await postJson(`${MCP_URL}/oauth/register`, {
    client_name: "js-integration-demo",
    redirect_uris: [REDIRECT_URI],
  });
  const clientId = reg.client_id;
  console.log(`✓ registered client_id = ${clientId}`);

  const { verifier, challenge } = pkce();
  const state = randomState();

  const authorizeUrl = new URL(`${MCP_URL}/oauth/authorize`);
  authorizeUrl.search = new URLSearchParams({
    response_type: "code",
    client_id: clientId,
    redirect_uri: REDIRECT_URI,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
    scope: SCOPE,
  }).toString();

  console.log(`→ opening browser to:\n  ${authorizeUrl.href}`);
  await new Promise((resolve, reject) => {
    open.exec(`xdg-open "${authorizeUrl.href}"`, (err) =>
      err ? reject(err) : resolve(),
    );
  });

  const code = await waitForCode(state);
  console.log(`✓ received code = ${code.slice(0, 12)}…`);

  const tokens = await postForm(`${MCP_URL}/oauth/token`, {
    grant_type: "authorization_code",
    code,
    redirect_uri: REDIRECT_URI,
    code_verifier: verifier,
  });
  console.log(`✓ got access_token (expires_in=${tokens.expires_in}s)`);

  const toolsRes = await fetch(`${MCP_URL}/mcp`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${tokens.access_token}`,
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "tools/list",
      params: {},
    }),
  });
  const tools = await toolsRes.json();
  console.log("✓ /mcp tools/list response:");
  console.log(JSON.stringify(tools, null, 2));
}

main().catch((err) => {
  console.error("✗", err.message);
  process.exit(1);
});
