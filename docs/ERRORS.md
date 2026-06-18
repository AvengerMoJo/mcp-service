# Error Catalog

`mcp-service` exposes two parallel error contracts depending on the endpoint
surface. All errors are JSON; clients should branch on `error` (for OAuth) or
`error.code` (for JSON-RPC), not on string-matching `error_description`.

---

## 1. OAuth / HTTP error envelope (RFC 6749 §5.2)

Returned by `POST /oauth/register`, `POST /oauth/token`, and any 4xx/5xx
response on `/mcp` or `/oauth` when auth is required.

```json
{
  "error": "invalid_token",
  "error_description": "Token has expired",
  "error_uri": "https://example.com/docs/errors#invalid_token",
  "state": "abc123"
}
```

Every response carries a `Content-Type: application/json; charset=utf-8`
header. Every 401 response carries a `WWW-Authenticate: Bearer ...` header
per RFC 6750 §3.

### 1.1 Catalog

| `error`                    | HTTP | When it happens                                                  |
|----------------------------|------|------------------------------------------------------------------|
| `invalid_request`          | 400  | Malformed body, missing parameter, unsupported `code_challenge_method`. |
| `invalid_client`           | 401  | Client authentication failed (e.g. unknown `client_id`).         |
| `invalid_grant`            | 400  | Authorization code is expired, used, or has a mismatching PKCE verifier / redirect URI. |
| `invalid_scope`            | 400  | Requested scope is outside `OAUTH_SUPPORTED_SCOPES`.             |
| `invalid_token`            | 401  | Bearer token is missing, expired, or malformed.                  |
| `unauthorized_client`      | 403  | Client is not allowed to use this grant type.                    |
| `unsupported_grant_type`   | 400  | `grant_type` parameter is not `authorization_code` or `refresh_token`. |
| `unsupported_response_type`| 400  | `response_type` is not `code` (returned via redirect).           |
| `access_denied`            | 400  | Resource owner denied consent (returned via redirect).           |
| `insufficient_scope`       | 403  | Token does not carry the scope required by the resource.        |
| `server_error`             | 500  | AS is misconfigured, signing key missing, or 501 Not Implemented when OAuth AS is disabled. |
| `temporarily_unavailable`  | 503  | AS is overloaded or under maintenance.                           |
| `oauth_disabled`           | 401  | Service-level guard returned when `OAUTH_ENABLED=false`.         |

### 1.2 `WWW-Authenticate` header

401 responses include a `WWW-Authenticate: Bearer ...` header of the form:

```
WWW-Authenticate: Bearer realm="mcp_service", error="invalid_token", error_description="Token has expired"
```

The `realm` is taken from `OAUTH_AUDIENCE` when set, otherwise defaults to
`mcp_service`.

---

## 2. JSON-RPC 2.0 error envelope

Returned by `POST /mcp` and `POST /oauth` (the dispatch layer). Per
[JSON-RPC 2.0 §6](https://www.jsonrpc.org/specification#error_object):

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32603,
    "message": "Internal error",
    "data": "stacktrace or extra context"
  }
}
```

### 2.1 Catalog

| Code     | Name                | HTTP wrapper | When                                                              |
|----------|---------------------|--------------|-------------------------------------------------------------------|
| `-32700` | Parse error         | 400          | Body is not valid JSON.                                           |
| `-32600` | Invalid Request     | 400          | Body is not a JSON-RPC 2.0 object (missing `jsonrpc`, `method`).  |
| `-32601` | Method not found    | 200          | The MCP handler returned a method-not-found error.                |
| `-32602` | Invalid params      | 200          | Reserved for handler-issued parameter validation errors.          |
| `-32603` | Internal error      | 500          | Handler raised an uncaught exception; `data` carries the message. |
| `-32000` | Server error        | 500          | Reserved for application-defined server errors.                   |
| `-32001` | Auth required       | 401          | Reserved — handler may emit this when scope check fails.          |
| `-32002` | Forbidden           | 403          | Reserved — handler may emit this for authorization failures.      |
| `-32003` | Rate limited        | 429          | Reserved — handler may emit this when throttling.                 |

For a notification (`"id"` absent from the request) the server returns
**HTTP 204** with no body, per JSON-RPC 2.0 §4.1.

---

## 3. Unhandled-exception envelope

Routes registered through `install_error_handlers` (called by `create_app`)
return OAuth-style envelopes for:

- `404 Not Found` →
  `{"error": "invalid_request", "error_description": "Not found"}`
- `405 Method Not Allowed` →
  `{"error": "invalid_request", "error_description": "Method PUT not allowed"}`
- `422 Validation Error` →
  `{"error": "invalid_request", "error_description": "Request validation failed: ..."}`

---

## 4. Example error handling in a client

```python
import httpx

resp = httpx.post("https://mcp.example.com/mcp", json={
    "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}
}, headers={"Authorization": "Bearer xxx"})

if resp.status_code == 401:
    challenge = resp.headers.get("WWW-Authenticate", "")
    # surface "Bearer error=invalid_token, error_description=..."
    raise PermissionError(challenge)

body = resp.json()
if "error" in body:                # JSON-RPC error
    raise RuntimeError(body["error"]["message"])
```
