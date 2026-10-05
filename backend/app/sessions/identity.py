"""Trusted application identity at the conversation HTTP boundary."""

from typing import Annotated

from fastapi import Header

ApplicationUserHeader = Annotated[
    str,
    Header(alias="X-Application-User", pattern=r"^[^\s:]+:[^\s:]+$"),
]


def require_application_user(application_user: ApplicationUserHeader) -> str:
    return application_user
