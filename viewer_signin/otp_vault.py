"""Issue and redeem the six digits, with the counters that keep a code single-use."""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from typing import Callable, Optional

CODE_TTL_SECONDS = 300
RESEND_COOLDOWN_SECONDS = 30
MAX_ATTEMPTS = 3


@dataclass
class PendingCode:
    code: str
    phone: str
    device_id: str
    issued_at: float
    attempts: int = 0


class OtpVault:
    """In-memory store. Swap the dict for Redis and the behaviour is unchanged."""

    def __init__(self, clock: Callable[[], float], sender: Callable[[str, str], None]) -> None:
        self._clock = clock
        self._sender = sender
        self._pending: dict[str, PendingCode] = {}
        self._sessions: dict[str, str] = {}

    def issue(self, phone: str, device_id: str) -> str:
        now = self._clock()
        existing = self._pending.get(phone)
        if existing and now - existing.issued_at < RESEND_COOLDOWN_SECONDS:
            raise ResendTooSoon(int(RESEND_COOLDOWN_SECONDS - (now - existing.issued_at)))
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._pending[phone] = PendingCode(code=code, phone=phone, device_id=device_id, issued_at=now)
        self._sender(phone, code)
        return code

    def redeem(self, phone: str, code: str, device_id: str) -> str:
        pending = self._pending.get(phone)
        if pending is None:
            raise CodeRejected("no_code_pending")
        if self._clock() - pending.issued_at > CODE_TTL_SECONDS:
            del self._pending[phone]
            raise CodeRejected("code_expired")
        if pending.device_id != device_id:
            del self._pending[phone]
            raise CodeRejected("device_mismatch")
        pending.attempts += 1
        if not hmac.compare_digest(pending.code, code):
            if pending.attempts >= MAX_ATTEMPTS:
                del self._pending[phone]
                raise CodeRejected("too_many_attempts")
            raise CodeRejected("code_incorrect")
        del self._pending[phone]
        session_id = secrets.token_urlsafe(18)
        self._sessions[session_id] = phone
        return session_id

    def phone_for_session(self, session_id: str) -> Optional[str]:
        return self._sessions.get(session_id)


class ResendTooSoon(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("resend cooldown active")
        self.retry_after = retry_after


class CodeRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
