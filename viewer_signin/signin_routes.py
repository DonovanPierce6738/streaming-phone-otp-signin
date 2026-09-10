"""The decisions: who gets an SMS, who gets a session, who gets to upload."""

from __future__ import annotations

from typing import Any

from .asset_queue import AssetQueue
from .captcha_shield import CaptchaShield, InfraiError
from .models import (
    ApiResponse,
    BadRequest,
    IngestAssetRequest,
    SendCodeRequest,
    VerifyCodeRequest,
)
from .otp_vault import CodeRejected, OtpVault, ResendTooSoon

REJECT_STATUS = {
    "code_incorrect": 401,
    "code_expired": 410,
    "no_code_pending": 404,
    "device_mismatch": 409,
    "too_many_attempts": 429,
}


class SigninRoutes:
    def __init__(self, shield: CaptchaShield, vault: OtpVault, assets: AssetQueue) -> None:
        self.shield = shield
        self.vault = vault
        self.assets = assets

    def send_code(self, payload: dict[str, Any]) -> ApiResponse:
        try:
            request = SendCodeRequest.parse(payload)
        except BadRequest as exc:
            return ApiResponse(400, {"error": str(exc)})

        try:
            result = self.shield.verify(
                request.captcha_token,
                widget_record_id=request.widget_record_id,
                action=f"signin_{request.purpose}",
                ip=request.client_ip,
            )
        except InfraiError as exc:
            # A challenge the shield turned down is the caller's answer, not our failure.
            return ApiResponse(403, {"error": "captcha_rejected", "reason": exc.code})

        try:
            self.vault.issue(request.phone, request.device_id)
        except ResendTooSoon as exc:
            return ApiResponse(429, {"error": "resend_too_soon", "retry_after": exc.retry_after})

        return ApiResponse(202, {"sent": True, "phone": request.phone, "captcha_score": result.get("score")})

    def verify_code(self, payload: dict[str, Any]) -> ApiResponse:
        try:
            request = VerifyCodeRequest.parse(payload)
        except BadRequest as exc:
            return ApiResponse(400, {"error": str(exc)})
        try:
            session_id = self.vault.redeem(request.phone, request.code, request.device_id)
        except CodeRejected as exc:
            return ApiResponse(REJECT_STATUS[exc.reason], {"error": exc.reason})
        return ApiResponse(200, {"session_id": session_id, "phone": request.phone})

    def ingest_asset(self, payload: dict[str, Any]) -> ApiResponse:
        try:
            request = IngestAssetRequest.parse(payload)
        except BadRequest as exc:
            return ApiResponse(400, {"error": str(exc)})
        phone = self.vault.phone_for_session(request.session_id)
        if phone is None:
            return ApiResponse(401, {"error": "session_unknown"})
        asset = self.assets.ingest(phone, request.title, request.source_key, request.renditions)
        return ApiResponse(201, {"asset_id": asset.asset_id, "state": asset.state, "title": asset.title})

    def deliver_next(self) -> ApiResponse:
        asset = self.assets.run_next_job()
        if asset is None:
            return ApiResponse(204, {})
        return ApiResponse(
            200,
            {"asset_id": asset.asset_id, "state": asset.state, "playlists": asset.delivered},
        )
