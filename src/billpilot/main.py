"""FastAPI mock BSS and the billing copilot.

The paths follow TM Forum resource names so the agent can call them as tools.
This process is a learning mock: it is not a certified or conformant implementation.
"""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from billpilot import __version__
from billpilot.agent.tracing import tracing_configured
from billpilot.api.agent_routes import router as agent_router
from billpilot.api.auth_routes import router as auth_router
from billpilot.api.routes import audit_router, router
from billpilot.config import Settings, get_settings
from billpilot.events import NullPublisher
from billpilot.logging import configure_logging, request_id_var
from billpilot.ui import mount_ui

DESCRIPTION = """
Learning mock of a telecom BSS, shaped like TM Forum Open APIs
(TMF678, TMF635, TMF620, TMF676, TMF637, TMF621, and a TMF654-style balance).

This is not a certified or conformant TM Forum implementation. It serves synthetic
INR billing data so an assistant can explain bills, raise disputes and propose
credits. Money and service changes stay pending until a different role approves them.

The browser signs in at `POST /auth/login`. Role and scope are loaded from the
users table. `X-API-Key` still works for the CLI and for service calls: the
customer key sees one customer, the CSR key sees accounts assigned to that CSR,
and the ops key can read across accounts and approve adjustments.

`POST /agent/chat` is the copilot. It calls these APIs as the same principal.
It can propose a credit and cannot approve one. Set `LLM_BACKEND=api` to use a
hosted model.
"""

logger = logging.getLogger("billpilot.access")

_ERROR_CODES = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "invalid",
    429: "rate_limited",
}


def error_body(status: int, message: str, request_id: str | None) -> dict:
    return {
        "code": _ERROR_CODES.get(status, "error"),
        "message": message,
        "requestId": request_id,
    }


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        status = 500
        response: Response | None = None
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            principal = getattr(request.state, "principal", None)
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": duration_ms,
                    "actor_role": None if principal is None else principal.role,
                },
            )
            if response is not None:
                response.headers["X-Request-Id"] = request_id
                rate_limit = getattr(request.state, "rate_limit", None)
                if rate_limit is not None:
                    limit, remaining = rate_limit
                    response.headers["X-RateLimit-Limit"] = str(limit)
                    response.headers["X-RateLimit-Remaining"] = str(remaining)
                if status == 429:
                    response.headers["Retry-After"] = "60"
            request_id_var.reset(token)


def _index_knowledge(settings: Settings) -> None:
    from billpilot.agent.embeddings import build_embedder
    from billpilot.agent.knowledge import ensure_index
    from billpilot.db import get_session_factory

    session = get_session_factory()()
    try:
        ensure_index(session, build_embedder(settings))
    finally:
        session.close()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _index_knowledge(app.state.settings)
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="BillPilot mock BSS",
        version=__version__,
        description=DESCRIPTION,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=_lifespan,
    )
    app.state.settings = settings
    app.state.publisher = NullPublisher()
    from billpilot.api.security import RateLimiter

    app.state.limiter = RateLimiter(
        {
            "customer": settings.rate_limit_customer_per_minute,
            "csr": settings.rate_limit_csr_per_minute,
            "ops": settings.rate_limit_ops_per_minute,
        }
    )
    from billpilot.auth.throttle import FailureLimiter

    app.state.login_limiter = FailureLimiter(
        settings.login_failure_limit,
        settings.login_failure_window_seconds,
    )
    app.add_middleware(RequestLogMiddleware)
    app.include_router(router, prefix="/tmf-api")
    app.include_router(audit_router)
    app.include_router(agent_router)
    app.include_router(auth_router)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.status_code, message, getattr(request.state, "request_id", None)),
        )

    @app.get("/health", tags=["Health"])
    def health() -> dict:
        current = app.state.settings
        demo = current.llm_backend != "api" or not current.llm_api_key.strip()
        return {
            "status": "ok",
            "demoMode": demo,
            "llmBackend": current.llm_backend,
            "tracing": tracing_configured(current),
        }

    if not mount_ui(app):

        @app.get("/", include_in_schema=False)
        def root() -> dict:
            return {
                "service": "billpilot-mock-bss",
                "docs": "/docs",
                "health": "/health",
                "note": "Learning mock. Not a certified TM Forum implementation.",
            }

    return app


app = create_app()
