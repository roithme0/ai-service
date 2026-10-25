"""Shared HTTP dependencies and error handling."""

from typing import Annotated

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.identity import ApplicationIdentity, IDENTITY_HEADER_PATTERN
from app.core.models import (
    HttpErrorResponse,
    RequestValidationErrorResponse,
    ValidationDetail,
)

ApplicationUserHeader = Annotated[
    str,
    Header(
        alias="X-Application-User",
        pattern=IDENTITY_HEADER_PATTERN,
        description="Unverified identity: encodeURIComponent(issuer):encodeURIComponent(subject).",
    ),
]


def require_application_user(
    application_user: ApplicationUserHeader, request: Request
) -> ApplicationIdentity:
    try:
        if len(request.headers.getlist("X-Application-User")) != 1:
            raise ValueError("Exactly one identity assertion is required.")
        return ApplicationIdentity.from_header(application_user)
    except ValueError:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("header", "X-Application-User"),
                    "msg": "Invalid issuer/subject assertion.",
                    "input": application_user,
                }
            ]
        ) from None


def register_error_handlers(application: FastAPI) -> None:
    application.exception_handler(StarletteHTTPException)(handle_http_exception)
    application.exception_handler(RequestValidationError)(handle_request_validation)
    application.exception_handler(Exception)(handle_unexpected_exception)


async def handle_http_exception(
    _request: Request, error: StarletteHTTPException
) -> JSONResponse:
    if error.status_code == 404:
        body = HttpErrorResponse(detail="Not Found", kind="not_found")
    elif error.status_code == 405:
        body = HttpErrorResponse(detail="Method Not Allowed", kind="method_not_allowed")
    elif error.status_code >= 500:
        body = HttpErrorResponse(detail="Internal Server Error", kind="internal_error")
    else:
        detail = (
            error.detail
            if isinstance(error.detail, str) and error.detail
            else "HTTP error"
        )
        body = HttpErrorResponse(detail=detail, kind="http_error")
    return JSONResponse(
        status_code=error.status_code,
        content=body.model_dump(mode="json", exclude_none=True),
        headers=error.headers,
    )


async def handle_request_validation(
    _request: Request, error: RequestValidationError
) -> JSONResponse:
    body = RequestValidationErrorResponse(
        detail=[
            ValidationDetail(
                loc=tuple(issue["loc"]), msg=issue["msg"], type=issue["type"]
            )
            for issue in error.errors()
        ],
        kind="request_validation",
    )
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))


async def handle_unexpected_exception(
    _request: Request, _error: Exception
) -> JSONResponse:
    body = HttpErrorResponse(detail="Internal Server Error", kind="internal_error")
    return JSONResponse(
        status_code=500, content=body.model_dump(mode="json", exclude_none=True)
    )
