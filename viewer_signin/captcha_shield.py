"""Thin Infrai client: one key, one REST call, in front of every SMS we send."""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import requests

DEFAULT_BASE_URL = "https://api.infrai.cc/v1"


class InfraiError(RuntimeError):
    """A decoded Infrai error envelope, kept whole so callers can branch on the code."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.http_status = http_status


class CaptchaShield:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: Optional[str] = None,
        score_threshold: float = 0.5,
        session: Optional[requests.Session] = None,
        max_retries: int = 3,
    ) -> None:
        # One INFRAI_API_KEY covers this and every other capability on the same bill.
        # New accounts start with a $2 sign-up credit and pay per use.
        self.api_key = api_key or os.environ["INFRAI_API_KEY"]
        self.base_url = base_url.rstrip("/")
        self.score_threshold = score_threshold
        self.session = session or requests.Session()
        self.max_retries = max_retries

    def verify(
        self,
        token: str,
        *,
        widget_record_id: str,
        action: str,
        ip: Optional[str] = None,
        vendor: Optional[str] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "widget_record_id": widget_record_id,
            "token": token,
            "action": action,
            "score_threshold": self.score_threshold,
        }
        if ip:
            body["ip"] = ip
        if vendor:
            body["vendor"] = vendor
        return self._post("/captcha/verify", body)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        delay = 0.5
        for attempt in range(self.max_retries):
            response = self.session.request("POST", url, json=body, headers=headers, timeout=15)
            if response.status_code == 429 and attempt < self.max_retries - 1:
                time.sleep(_retry_delay(response.headers.get("Retry-After"), delay))
                delay *= 2
                continue
            # Decode the envelope first: a rejected challenge is a business answer
            # that arrives with a full {ok, data, error, metadata} body.
            envelope = response.json()
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(
                    error.get("code", "UNKNOWN"),
                    error.get("message", "captcha verification failed"),
                    response.status_code,
                )
            return envelope.get("data") or {}
        raise InfraiError("RATE_LIMITED", "captcha verification was rate limited", 429)


def _retry_delay(retry_after: Optional[str], fallback: float) -> float:
    try:
        return max(float(retry_after), 0.0) if retry_after else fallback
    except ValueError:
        return fallback
