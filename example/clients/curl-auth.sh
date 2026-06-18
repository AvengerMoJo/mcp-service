#!/usr/bin/env bash
#
# Full OAuth 2.1 + PKCE dance against a running mcp-service, then a single
# JSON-RPC 2.0 /mcp call. Tested with bash 4+ and curl 7.80+.
#
# Usage:
#   MCP_URL=http://localhost:8000 \
#     ./curl-auth.sh
#
# Env vars (with defaults):
#   MCP_URL         base URL of the running mcp-service (no trailing slash)
#   REDIRECT_URI    callback URL registered for the dynamic client
#                   (default: http://localhost:9876/callback)
#   SCOPE           scope to request (default: "mcp:read mcp:write")
#
# What this does:
#   1. Registers a dynamic OAuth client.
#   2. Generates a PKCE verifier + S256 challenge.
#   3. Builds the /oauth/authorize URL.
#   4. Exchanges the auth code for tokens at /oauth/token.
#   5. Calls /mcp with the access token.

set -euo pipefail

MCP_URL="${MCP_URL:-http://localhost:8000}"
REDIRECT_URI="${REDIRECT_URI:-http://localhost:9876/callback}"
SCOPE="${SCOPE:-mcp:read mcp:write}"

if ! command -v python3 >/dev/null; then
  echo "python3 is required to generate PKCE parameters." >&2
  exit 1
fi

echo "▶ Registering dynamic client at ${MCP_URL}/oauth/register ..."
CLIENT_RESPONSE=$(curl -fsS -X POST "${MCP_URL}/oauth/register" \
  -H 'Content-Type: application/json' \
  -d "{\"client_name\":\"curl-demo\",\"redirect_uris\":[\"${REDIRECT_URI}\"]}")
CLIENT_ID=$(echo "${CLIENT_RESPONSE}" | python3 -c "import sys, json; print(json.load(sys.stdin)['client_id'])")
echo "  client_id = ${CLIENT_ID}"

# ── PKCE ──────────────────────────────────────────────────────────────────────
read VERIFIER CHALLENGE STATE < <(python3 - <<'PY'
import secrets, hashlib, base64
verifier = secrets.token_urlsafe(64)
challenge = base64.urlsafe_b64encode(
    hashlib.sha256(verifier.encode()).digest()
).decode().rstrip("=")
state = secrets.token_urlsafe(16)
print(verifier, challenge, state)
PY
)

echo "▶ Authorize URL:"
AUTH_URL="${MCP_URL}/oauth/authorize?response_type=code&client_id=${CLIENT_ID}&redirect_uri=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "${REDIRECT_URI}")&state=${STATE}&code_challenge=${CHALLENGE}&code_challenge_method=S256&scope=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "${SCOPE}")"
echo "  ${AUTH_URL}"
echo
echo "  Visit this URL in a browser (or open it programmatically)."
echo "  After consent the server redirects to:"
echo "    ${REDIRECT_URI}?code=...&state=${STATE}"
echo

# The rest of the flow assumes you've captured the `code` from the redirect.
# Either paste it interactively or set AUTH_CODE in the environment.
if [[ -z "${AUTH_CODE:-}" ]]; then
  read -rp "Paste the `code` from the redirect URL: " AUTH_CODE
fi

echo "▶ Exchanging code for tokens ..."
TOKEN_RESPONSE=$(curl -fsS -X POST "${MCP_URL}/oauth/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode "grant_type=authorization_code" \
  --data-urlencode "code=${AUTH_CODE}" \
  --data-urlencode "redirect_uri=${REDIRECT_URI}" \
  --data-urlencode "code_verifier=${VERIFIER}")
echo "  ${TOKEN_RESPONSE}"

ACCESS_TOKEN=$(echo "${TOKEN_RESPONSE}" | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

echo "▶ Calling /mcp with the access token ..."
curl -fsS -X POST "${MCP_URL}/mcp" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
echo
