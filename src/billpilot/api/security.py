"""API-key personas, signed browser sessions, and a single-process rate limit.

Keys map to a role for the CLI and for in-process tool calls. The browser does
not send a key. A session cookie names a user id; role and scope are loaded
from the users table. A client-supplied role is never read.
"""

import hmac
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from billpilot.auth.session import read_session
from billpilot.config import Settings
from billpilot.db import get_session
from billpilot.models import User

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

PUBLIC_PATHS = {"/", "/health", "/openapi.json"}
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Principal:
    role: str
    actor_id: str
    customer_number: str | None = None
    csr_code: str | None = None
    username: str | None = None
    display_name: str | None = None
    auth: str = "api_key"


class RateLimiter:
    """Fixed one-minute window, counted per actor inside this process."""

    def __init__(self, limits_per_minute: dict[str, int]) -> None:
        self.limits = limits_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, actor_id: str, role: str) -> tuple[bool, int, int]:
        limit = self.limits[role]
        now = time.monotonic()
        hits = self._hits[actor_id]
        while hits and now - hits[0] >= 60:
            hits.popleft()
        if len(hits) >= limit:
            return False, limit, 0
        hits.append(now)
        return True, limit, limit - len(hits)


def principal_for_key(settings: Settings, api_key: str | None) -> Principal:
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key.")
    if api_key == settings.api_key_customer:
        return Principal(
            role="customer",
            actor_id=f"customer:{settings.customer_number}",
            customer_number=settings.customer_number,
        )
    if api_key == settings.api_key_csr:
        return Principal(
            role="csr",
            actor_id=f"csr:{settings.csr_code}",
            csr_code=settings.csr_code,
        )
    if api_key == settings.api_key_ops:
        return Principal(role="ops", actor_id="ops")
    raise HTTPException(status_code=401, detail="Unknown API key.")


def principal_for_user(user: User) -> Principal:
    return Principal(
        role=user.role,
        actor_id=f"user:{user.username}",
        customer_number=user.customer_number,
        csr_code=user.csr_code,
        username=user.username,
        display_name=user.display_name,
        auth="session",
    )


def external_origin(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-proto", "")
    proto = forwarded.split(",")[0].strip() if forwarded else request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host.split(',')[0].strip()}"


def request_is_https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded.split(",")[0].strip().lower() == "https":
        return True
    return request.url.scheme == "https"


def claims_from_request(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get("bp_session")
    if not token:
        return None
    return read_session(token, request.app.state.settings.session_secret)


def principal_from_cookie(request: Request, session: Session) -> Principal:
    claims = claims_from_request(request)
    if claims is None:
        raise HTTPException(status_code=401, detail="Sign in required.")
    try:
        user_id = uuid.UUID(claims["uid"])
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.") from exc
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.")
    request.state.session_csrf = claims["csrf"]
    request.state.session_exp = claims["exp"]
    return principal_for_user(user)


def enforce_csrf(request: Request) -> None:
    """Cookie sessions must echo the CSRF secret on writes. API keys are not cookies."""
    if request.method in _SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != external_origin(request).rstrip("/"):
        raise HTTPException(status_code=403, detail="Cross-site request blocked.")
    sent = request.headers.get("x-csrf-token") or ""
    expected = getattr(request.state, "session_csrf", "")
    if not sent or not expected or not hmac.compare_digest(sent, expected):
        raise HTTPException(status_code=403, detail="Missing or invalid CSRF token.")


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/redoc")


def get_principal(
    request: Request,
    api_key: Annotated[str | None, Security(api_key_header)] = None,
    session: Session = Depends(get_session),
) -> Principal:
    if api_key:
        principal = principal_for_key(request.app.state.settings, api_key)
    else:
        principal = principal_from_cookie(request, session)
        enforce_csrf(request)
    allowed, limit, remaining = request.app.state.limiter.check(principal.actor_id, principal.role)
    request.state.rate_limit = (limit, remaining)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")
    request.state.principal = principal
    return principal


def require_roles(*roles: str):
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"The {principal.role} role cannot perform this action.",
            )
        return principal

    return dependency
