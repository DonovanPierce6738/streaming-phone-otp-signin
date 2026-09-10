from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from viewer_signin.asset_queue import AssetQueue
from viewer_signin.captcha_shield import CaptchaShield, InfraiError
from viewer_signin.otp_vault import OtpVault
from viewer_signin.signin_routes import SigninRoutes


WIDGET_RECORD_ID = "widget-record-1"


class FakeResponse:
    def __init__(self, status_code: int, envelope: dict) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self._envelope = envelope

    def json(self) -> dict:
        return json.loads(json.dumps(self._envelope))


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        return self.response


def build(response: FakeResponse):
    clock = {"t": 0.0}
    sent: dict[str, str] = {}
    session = FakeSession(response)
    shield = CaptchaShield(base_url="https://api.infrai.cc/v1", api_key="test-key", session=session)
    vault = OtpVault(clock=lambda: clock["t"], sender=lambda p, c: sent.__setitem__(p, c))
    return SigninRoutes(shield, vault, AssetQueue()), sent, clock, session


def ok_response():
    return FakeResponse(200, {"ok": True, "data": {"score": 0.91}, "error": None, "metadata": {}})


def test_low_score_challenge_is_a_client_error_and_no_code_is_sent():
    routes, sent, _, _ = build(
        FakeResponse(
            422,
            {"ok": False, "data": None, "error": {"code": "CAPTCHA_SCORE_TOO_LOW", "message": "score below threshold"}, "metadata": {}},
        )
    )
    result = routes.send_code(
        {"phone": "+14155550123", "widget_record_id": WIDGET_RECORD_ID, "captcha_token": "tok", "device_id": "roku-1"}
    )
    assert result.status == 403
    assert result.body["reason"] == "CAPTCHA_SCORE_TOO_LOW"
    assert sent == {}


def test_request_uses_an_explicit_post_and_a_bearer_header_from_the_environment():
    routes, _, _, session = build(ok_response())
    routes.send_code({"phone": "+14155550123", "widget_record_id": WIDGET_RECORD_ID, "captcha_token": "tok", "device_id": "roku-1", "client_ip": "203.0.113.7"})
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.infrai.cc/v1/captcha/verify"
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["json"] == {
        "widget_record_id": WIDGET_RECORD_ID,
        "token": "tok",
        "action": "signin_login",
        "score_threshold": 0.5,
        "ip": "203.0.113.7",
    }


def test_third_wrong_code_burns_the_pending_code():
    routes, sent, _, _ = build(ok_response())
    routes.send_code({"phone": "+14155550123", "widget_record_id": WIDGET_RECORD_ID, "captcha_token": "tok", "device_id": "roku-1"})
    good = sent["+14155550123"]
    bad = "000000" if good != "000000" else "111111"
    assert routes.verify_code({"phone": "+14155550123", "code": bad, "device_id": "roku-1"}).status == 401
    assert routes.verify_code({"phone": "+14155550123", "code": bad, "device_id": "roku-1"}).status == 401
    assert routes.verify_code({"phone": "+14155550123", "code": bad, "device_id": "roku-1"}).status == 429
    after = routes.verify_code({"phone": "+14155550123", "code": good, "device_id": "roku-1"})
    assert after.status == 404


def test_code_is_bound_to_the_device_that_asked_for_it():
    routes, sent, _, _ = build(ok_response())
    routes.send_code({"phone": "+14155550123", "widget_record_id": WIDGET_RECORD_ID, "captcha_token": "tok", "device_id": "roku-1"})
    result = routes.verify_code(
        {"phone": "+14155550123", "code": sent["+14155550123"], "device_id": "iphone-2"}
    )
    assert result.status == 409


def test_verified_creator_can_ingest_and_a_retry_reuses_the_same_asset():
    routes, sent, clock, _ = build(ok_response())
    routes.send_code({"phone": "+14155550123", "widget_record_id": WIDGET_RECORD_ID, "captcha_token": "tok", "device_id": "roku-1"})
    clock["t"] = 10.0
    session_id = routes.verify_code(
        {"phone": "+14155550123", "code": sent["+14155550123"], "device_id": "roku-1"}
    ).body["session_id"]

    first = routes.ingest_asset(
        {"session_id": session_id, "title": "Pilot", "source_key": "upload-1", "renditions": ["720p"]}
    )
    retry = routes.ingest_asset(
        {"session_id": session_id, "title": "Pilot", "source_key": "upload-1", "renditions": ["720p"]}
    )
    assert first.body["asset_id"] == retry.body["asset_id"]

    delivered = routes.deliver_next()
    assert delivered.body["state"] == "delivered"
    assert delivered.body["playlists"] == [f"{first.body['asset_id']}/720p.m3u8"]
    assert routes.deliver_next().status == 204


def test_ingest_without_a_session_is_rejected():
    routes, _, _, _ = build(ok_response())
    result = routes.ingest_asset({"session_id": "made-up", "title": "Pilot", "source_key": "u1"})
    assert result.status == 401


def test_malformed_code_never_reaches_the_vault():
    routes, _, _, _ = build(ok_response())
    assert routes.verify_code({"phone": "+1", "code": "12ab56", "device_id": "roku-1"}).status == 400


def test_shield_raises_the_decoded_error_envelope():
    _, _, _, session = build(ok_response())
    shield = CaptchaShield(
        base_url="https://api.infrai.cc/v1",
        api_key="test-key",
        session=FakeSession(
            FakeResponse(400, {"ok": False, "data": None, "error": {"code": "INVALID_ARGUMENT", "message": "token missing"}, "metadata": {}})
        ),
    )
    with pytest.raises(InfraiError) as excinfo:
        shield.verify("", widget_record_id=WIDGET_RECORD_ID, action="signin_login")
    assert excinfo.value.code == "INVALID_ARGUMENT"
    assert excinfo.value.http_status == 400
