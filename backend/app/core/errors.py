"""Structured API errors: {"error": {"code", "message", "details"}, "request_id"}."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None, details: Any = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class NotAuthenticated(AppError):
    status_code, code = 401, "not_authenticated"


class Forbidden(AppError):
    status_code, code = 403, "forbidden"


class NotFound(AppError):
    status_code, code = 404, "not_found"


class Conflict(AppError):
    status_code, code = 409, "conflict"


class InvalidState(AppError):
    status_code, code = 409, "invalid_state"


class ValidationFailed(AppError):
    status_code, code = 422, "validation_error"


class UrlNotAllowed(AppError):
    status_code, code = 422, "url_not_allowed"


class SupabaseNotConfigured(AppError):
    status_code, code = 503, "supabase_not_configured"

    def __init__(self) -> None:
        super().__init__(
            "Supabase is not configured on the backend. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY "
            "(see docs/setup.md).",
        )


class EmbeddingUnavailable(AppError):
    status_code, code = 503, "embedding_unavailable"


class UpstreamError(AppError):
    status_code, code = 502, "upstream_error"


class DuplicateError(Exception):
    """Raised by stores when a unique constraint is violated."""


def _body(request: Request, code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "details": details},
        "request_id": getattr(request.state, "request_id", None),
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(_body(request, exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(_body(request, "validation_error", "Request validation failed", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 401: "not_authenticated", 403: "forbidden"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(_body(request, code, str(exc.detail)), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover - safety net
        import logging

        logging.getLogger("app").exception("unhandled error request_id=%s", getattr(request.state, "request_id", None))
        return JSONResponse(_body(request, "internal_error", "Internal server error"), status_code=500)
