"""Typed request/response models for the sign-in and asset endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


class BadRequest(ValueError):
    """A request body that we refuse before any work happens."""


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BadRequest(f"'{key}' is required and must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class SendCodeRequest:
    """POST /signin/code — ask for an SMS code for one phone number."""

    phone: str
    widget_record_id: str
    captcha_token: str
    device_id: str
    client_ip: Optional[str] = None
    purpose: Literal["login", "creator_upload"] = "login"

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> "SendCodeRequest":
        purpose = payload.get("purpose", "login")
        if purpose not in ("login", "creator_upload"):
            raise BadRequest("'purpose' must be 'login' or 'creator_upload'")
        client_ip = payload.get("client_ip")
        if client_ip is not None and not isinstance(client_ip, str):
            raise BadRequest("'client_ip' must be a string when present")
        return cls(
            phone=_require_str(payload, "phone"),
            widget_record_id=_require_str(payload, "widget_record_id"),
            captcha_token=_require_str(payload, "captcha_token"),
            device_id=_require_str(payload, "device_id"),
            client_ip=client_ip,
            purpose=purpose,
        )


@dataclass(frozen=True)
class VerifyCodeRequest:
    """POST /signin/verify — trade the six digits for a session."""

    phone: str
    code: str
    device_id: str

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> "VerifyCodeRequest":
        code = _require_str(payload, "code")
        if not code.isdigit() or len(code) != 6:
            raise BadRequest("'code' must be six digits")
        return cls(
            phone=_require_str(payload, "phone"),
            code=code,
            device_id=_require_str(payload, "device_id"),
        )


@dataclass(frozen=True)
class IngestAssetRequest:
    """POST /assets — a creator hands us one master file to process."""

    session_id: str
    title: str
    source_key: str
    renditions: tuple[str, ...] = ("1080p", "720p")

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> "IngestAssetRequest":
        renditions = payload.get("renditions", ["1080p", "720p"])
        if not isinstance(renditions, list) or not all(isinstance(r, str) for r in renditions):
            raise BadRequest("'renditions' must be a list of strings")
        if not renditions:
            raise BadRequest("'renditions' must name at least one output")
        return cls(
            session_id=_require_str(payload, "session_id"),
            title=_require_str(payload, "title"),
            source_key=_require_str(payload, "source_key"),
            renditions=tuple(renditions),
        )


@dataclass(frozen=True)
class ApiResponse:
    """What our own HTTP layer sends back to the app."""

    status: int
    body: dict[str, Any] = field(default_factory=dict)
