"""Global exception handlers — convert domain exceptions to typed responses.

Without these, FastAPI returns generic 500s. With them, callers get:
    {"error": "rate_limit", "detail": "...", "request_id": "..."}
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.tools.github.exceptions import (
    AuthError,
    GitHubError,
    NotFoundError,
    RateLimitError,
)
from app.tools.voyage_client import VoyageError

log = structlog.get_logger(__name__)


def _payload(error: str, detail: str | None, request: Request) -> dict:
    return {
        "error": error,
        "detail": detail,
        "request_id": request.headers.get("x-request-id"),
    }


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError):
        return JSONResponse(content=_payload("not_found", str(exc), request), status_code=404)

    @app.exception_handler(AuthError)
    async def _auth(request: Request, exc: AuthError):
        return JSONResponse(content=_payload("github_auth", str(exc), request), status_code=401)

    @app.exception_handler(RateLimitError)
    async def _rate_limit(request: Request, exc: RateLimitError):
        return JSONResponse(content=_payload("rate_limit", str(exc), request), status_code=429)

    @app.exception_handler(GitHubError)
    async def _github_other(request: Request, exc: GitHubError):
        return JSONResponse(content=_payload("github_upstream", str(exc), request), status_code=502)

    @app.exception_handler(VoyageError)
    async def _voyage(request: Request, exc: VoyageError):
        return JSONResponse(content=_payload("embedding_upstream", str(exc), request), status_code=502)

    @app.exception_handler(ValueError)
    async def _value(request: Request, exc: ValueError):
        return JSONResponse(content=_payload("bad_request", str(exc), request), status_code=400)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        # FastAPI's default formatting is fine but we wrap it in our envelope.
        return JSONResponse(
            content=_payload("validation_error", str(exc.errors()), request),
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def _fallback(request: Request, exc: Exception):
        log.exception("unhandled_exception", path=request.url.path)
        return JSONResponse(
            content=_payload("internal_error", "An unexpected error occurred", request),
            status_code=500,
        )
