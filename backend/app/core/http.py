"""Shared HTTP boundary dependencies."""

from typing import Annotated

from fastapi import Header, Request
from fastapi.exceptions import RequestValidationError

from app.core.identity import ApplicationIdentity, IDENTITY_HEADER_PATTERN

ApplicationUserHeader = Annotated[
    str,
    Header(
        alias="X-Application-User", pattern=IDENTITY_HEADER_PATTERN,
        description="Unverified identity: encodeURIComponent(issuer):encodeURIComponent(subject).",
    ),
]


def require_application_user(application_user: ApplicationUserHeader, request: Request) -> ApplicationIdentity:
    try:
        if len(request.headers.getlist("X-Application-User")) != 1:
            raise ValueError("Exactly one identity assertion is required.")
        return ApplicationIdentity.from_header(application_user)
    except ValueError:
        raise RequestValidationError([{
            "type": "value_error", "loc": ("header", "X-Application-User"),
            "msg": "Invalid issuer/subject assertion.", "input": application_user,
        }]) from None
