"""Sign-in, the current session, and sign-out.

The browser receives an httpOnly session cookie. Role and scope come from the
users row on each request. Failed attempts are rate limited and audited.
"""

import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from billpilot.api.audit import append_audit
from billpilot.api.security import Principal, get_principal, request_is_https
from billpilot.auth.demo import DEMO_USERS
from billpilot.auth.passwords import dummy_hash, verify_password
from billpilot.auth.session import CSRF_COOKIE, SESSION_COOKIE, sign_session
from billpilot.auth.throttle import FailureLimiter
from billpilot.db import get_session
from billpilot.models import User

router = APIRouter(prefix="/auth", tags=["Auth"])

# Unknown-user audit rows still need a UUID. This one is not a user.
_ANONYMOUS = uuid.UUID(int=0)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class SessionView(BaseModel):
    username: str
    displayName: str
    role: str
    customerNumber: str | None = None
    csrCode: str | None = None
    expiresAt: str
    csrfToken: str


class DemoAccountView(BaseModel):
    username: str
    displayName: str
    role: str
    password: str
    scope: str
    demoOnly: bool = True


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client is None:
        return "unknown"
    return request.client.host or "unknown"


def _limiter(request: Request) -> FailureLimiter:
    return request.app.state.login_limiter


def _audit_auth(
    session: Session,
    request: Request,
    *,
    role: str,
    actor_id: str,
    action: str,
    resource_id: uuid.UUID,
    payload: dict,
) -> None:
    append_audit(
        session,
        role=role,
        actor_id=actor_id[:64],
        request_id=request.state.request_id,
        action=action,
        resource_type="session",
        resource_id=resource_id,
        account_id=None,
        payload=payload,
    )
    session.commit()


def _view(user: User, csrf: str, exp: int) -> SessionView:
    return SessionView(
        username=user.username,
        displayName=user.display_name,
        role=user.role,
        customerNumber=user.customer_number,
        csrCode=user.csr_code,
        expiresAt=datetime.fromtimestamp(exp, UTC).isoformat(),
        csrfToken=csrf,
    )


def _set_session_cookies(response: Response, request: Request, token: str, csrf: str) -> None:
    settings = request.app.state.settings
    secure = request_is_https(request)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    # Readable so the page can copy it into X-CSRF-Token. The check is against
    # the value inside the signed session, not against this cookie alone.
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        httponly=False,
        secure=secure,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )


def _clear_session_cookies(response: Response, request: Request) -> None:
    secure = request_is_https(request)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=secure, httponly=False, samesite="lax")


@router.get("/demo-accounts", response_model=list[DemoAccountView])
def demo_accounts() -> list[DemoAccountView]:
    """Published demo identities. The passwords are synthetic and documented."""
    return [
        DemoAccountView(
            username=item.username,
            displayName=item.display_name,
            role=item.role,
            password=item.password,
            scope=item.scope,
        )
        for item in DEMO_USERS
    ]


@router.post("/login", response_model=SessionView)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> SessionView:
    username = body.username.strip().lower()
    ip = _client_ip(request)
    limiter = _limiter(request)
    user_key = f"user:{username}"
    ip_key = f"ip:{ip}"
    if limiter.blocked(user_key) or limiter.blocked(ip_key):
        _audit_auth(
            session,
            request,
            role="system",
            actor_id=f"login:{username}"[:64],
            action="auth.login_rate_limited",
            resource_id=_ANONYMOUS,
            payload={"username": username, "reason": "rate_limited"},
        )
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")

    user = session.scalar(select(User).where(User.username == username))
    # Always verify a hash, so a missing user is not obviously faster.
    hashed = user.password_hash if user is not None else dummy_hash()
    if user is None or not verify_password(body.password, hashed):
        limiter.record(user_key)
        limiter.record(ip_key)
        _audit_auth(
            session,
            request,
            role="system",
            actor_id=(f"user:{username}" if user is not None else "anonymous")[:64],
            action="auth.login_failed",
            resource_id=user.id if user is not None else _ANONYMOUS,
            payload={"username": username, "reason": "bad_password" if user is not None else "unknown_user"},
        )
        raise HTTPException(status_code=401, detail="Unknown username or password.")

    limiter.reset(user_key)
    csrf = secrets.token_urlsafe(32)
    settings = request.app.state.settings
    now = int(datetime.now(UTC).timestamp())
    token = sign_session(str(user.id), csrf, settings.session_secret, settings.session_ttl_seconds, now=now)
    exp = now + settings.session_ttl_seconds
    _set_session_cookies(response, request, token, csrf)
    _audit_auth(
        session,
        request,
        role=user.role,
        actor_id=f"user:{user.username}",
        action="auth.login",
        resource_id=user.id,
        payload={"username": user.username, "role": user.role},
    )
    return _view(user, csrf, exp)


@router.get("/me", response_model=SessionView)
def me(
    request: Request,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> SessionView:
    if principal.auth != "session" or principal.username is None:
        raise HTTPException(status_code=401, detail="Sign in required.")
    user = session.scalar(select(User).where(User.username == principal.username))
    if user is None:
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.")
    csrf = request.state.session_csrf
    exp = int(request.state.session_exp)
    return _view(user, csrf, exp)


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> None:
    if principal.auth != "session" or principal.username is None:
        raise HTTPException(status_code=401, detail="Sign in required.")
    user = session.scalar(select(User).where(User.username == principal.username))
    resource_id = user.id if user is not None else _ANONYMOUS
    _audit_auth(
        session,
        request,
        role=principal.role,
        actor_id=principal.actor_id,
        action="auth.logout",
        resource_id=resource_id,
        payload={"username": principal.username},
    )
    _clear_session_cookies(response, request)
