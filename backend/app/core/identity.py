"""Unverified issuer/subject assertions shared by HTTP and MCP boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

_COMPONENT = r"(?:[A-Za-z0-9_.!~*'()-]|%[0-9A-Fa-f]{2})+"
IDENTITY_HEADER_PATTERN = f"^{_COMPONENT}:{_COMPONENT}$"
_ENCODING_SAFE = "~!*'()"


@dataclass(frozen=True)
class ApplicationIdentity:
    issuer: str
    subject: str

    def __post_init__(self) -> None:
        if not self.issuer or not self.subject:
            raise ValueError("Identity issuer and subject must not be empty.")

    @classmethod
    def from_header(cls, value: str) -> ApplicationIdentity:
        if re.fullmatch(IDENTITY_HEADER_PATTERN, value) is None:
            raise ValueError("Invalid issuer/subject assertion.")
        issuer, subject = (unquote(part, errors="strict") for part in value.split(":"))
        return cls(issuer=issuer, subject=subject)

    def to_header(self) -> str:
        return f"{quote(self.issuer, safe=_ENCODING_SAFE)}:{quote(self.subject, safe=_ENCODING_SAFE)}"
