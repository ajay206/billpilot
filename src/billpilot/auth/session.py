"""HMAC-signed session token. The browser stores it in an httpOnly cookie.

The token carries the user id, an expiry, and a CSRF secret. Role and scope
are not in the token. The server loads those from the users row.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any

SESSION_COOKIE = "bp_session"
CSRF_COOKIE = "bp_csrf"
SESSION_TTL_DEFAULT = 8 * 60 * 60


def sign_session(user_id: str, csrf: str, secret: str, ttl_seconds: int, now: int | None = None) -> str:
    issued = int(time.time()) if now is None else now
    payload = {"uid": user_id, "csrf": csrf, "exp": issued + ttl_seconds}
    return _pack(payload, secret)


def read_session(token: str | None, secret: str, now: int | None = None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    body, signature = token.rsplit(".", 1)
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        payload = json.loads(raw.decode())
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    uid = payload.get("uid")
    csrf = payload.get("csrf")
    if not isinstance(exp, int) or not isinstance(uid, str) or not isinstance(csrf, str):
        return None
    current = int(time.time()) if now is None else now
    if exp <= current:
        return None
    return payload


def _pack(payload: dict, secret: str) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"
