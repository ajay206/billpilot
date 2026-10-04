"""API-key personas and a single-process rate limit.

Keys map to a role. The customer key is bound to one customer number and the CSR
key to one CSR code, so a leaked customer key cannot browse other accounts.
"""

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from billpilot.config import Settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

PUBLIC_PATHS = {"/", "/health", "/openapi.json"}


@dataclass(frozen=True)
class Principal:
    role: str
    actor_id: str
    customer_number: str | None = None
    csr_code: str | None = None


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


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/redoc")


def get_principal(
    request: Request,
    api_key: Annotated[str | None, Security(api_key_header)] = None,
) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        principal = principal_for_key(request.app.state.settings, api_key)
        request.state.principal = principal
    allowed, limit, remaining = request.app.state.limiter.check(principal.actor_id, principal.role)
    request.state.rate_limit = (limit, remaining)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")
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
