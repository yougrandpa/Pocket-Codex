from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
    )


def _code_from_status(status_code: int) -> str:
    if status_code == status.HTTP_400_BAD_REQUEST:
        return "BAD_REQUEST"
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return "UNAUTHORIZED"
    if status_code == status.HTTP_403_FORBIDDEN:
        return "FORBIDDEN"
    if status_code == status.HTTP_404_NOT_FOUND:
        return "TASK_NOT_FOUND"
    if status_code == status.HTTP_409_CONFLICT:
        return "INVALID_STATE_TRANSITION"
    if status_code == status.HTTP_501_NOT_IMPLEMENTED:
        return "NOT_IMPLEMENTED"
    return "HTTP_ERROR"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        code = _code_from_status(exc.status_code)
        return _response(
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
            details=None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details=_format_validation_errors(exc.errors()),
        )


def _format_validation_errors(errors: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "field": ".".join(str(item) for item in error.get("loc", [])),
            "message": error.get("msg", "Invalid value"),
        }
        for error in errors
    ]
