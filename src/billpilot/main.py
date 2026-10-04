"""FastAPI mock BSS.

The paths follow TM Forum resource names so a later agent can call them as tools.
This process is a learning mock: it is not a certified or conformant implementation.
"""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from billpilot import __version__
from billpilot.api.routes import audit_router, router
from billpilot.config import Settings, get_settings
from billpilot.events import NullPublisher
from billpilot.logging import configure_logging, request_id_var

DESCRIPTION = """
Learning mock of a telecom BSS, shaped like TM Forum Open APIs
(TMF678, TMF635, TMF620, TMF676, TMF637, TMF621, and a TMF654-style balance).

This is not a certified or conformant TM Forum implementation. It serves synthetic
INR billing data so an assistant can explain bills, raise disputes and propose
credits. Money and service changes stay pending until a different role approves them.

Send `X-API-Key`. The customer key sees one customer, the CSR key sees accounts
assigned to that CSR, and the ops key can read across accounts and approve adjustments.
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="BillPilot mock BSS",
        version=__version__,
        description=DESCRIPTION,
        docs_url="/docs",
        redoc_url="/redoc",
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
    app.add_middleware(RequestLogMiddleware)
    app.include_router(router, prefix="/tmf-api")
    app.include_router(audit_router)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.status_code, message, getattr(request.state, "request_id", None)),
        )

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "service": "billpilot-mock-bss",
            "docs": "/docs",
            "health": "/health",
            "note": "Learning mock. Not a certified TM Forum implementation.",
        }

    @app.get("/health", tags=["Health"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
