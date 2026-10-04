# Signed httpOnly session cookie

## Decision

The browser signs in at `POST /auth/login`. The response sets two cookies:

- `bp_session` is httpOnly, `SameSite=Lax`, and `Secure` when the request is HTTPS (including `X-Forwarded-Proto` on Render). It holds an HMAC-SHA256 token: user id, expiry (8 hours), and a CSRF secret. It does not hold the role.
- `bp_csrf` is readable by the page so the script can copy it into `X-CSRF-Token`. The server compares that header to the secret inside the signed session, not to the cookie by itself. A foreign `Origin` is rejected.

Every later request loads the user row and takes role, customer number, and CSR code from that row. A role in the JSON body is ignored. API keys still map to a principal for the CLI, the eval harness, and in-process tool calls. The frontend bundle does not contain them. Tool calls made for a signed-in user forward the session cookie and the CSRF header.

Failed sign-ins are counted per username and per client IP inside this process (8 failures, 15 minutes). Login, logout, a bad password, and a lockout each append an `audit_log` row. The password check uses Argon2id.

## Alternatives

- A JWT in `localStorage` or in an `Authorization` header. The page would have to store the token where script can read it, and a refresh would need that copy. The UI and the API are one origin, so a cookie is the smaller moving part.
- A server-side session table. Right for a multi-instance host that must revoke a session immediately. This deploy is one free instance. The signature and the expiry are enough, and a changed `SESSION_SECRET` invalidates every cookie.
- CSRF protection by `SameSite=Lax` alone. That blocks the common cross-site POST. The header check stays so a form on another site cannot submit a write even if a browser ignores `SameSite`.

## Why

The product UI and the API share a process and an origin. An httpOnly cookie is not readable by script, so a copied page cannot lift the session out of `document.cookie`. Role and scope stay on the server. API keys remain the seam for `billpilot ask` and for curl, which is what [0005](0005-rbac-personas.md) set up, and they are no longer shipped to the browser.
