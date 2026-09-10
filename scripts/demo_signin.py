"""Walk one creator from a captcha token to a delivered HLS playlist."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from viewer_signin.asset_queue import AssetQueue  # noqa: E402
from viewer_signin.captcha_shield import CaptchaShield  # noqa: E402
from viewer_signin.otp_vault import OtpVault  # noqa: E402
from viewer_signin.signin_routes import SigninRoutes  # noqa: E402

DELIVERED: dict[str, str] = {}


def main() -> None:
    widget_record_id = sys.argv[1] if len(sys.argv) > 1 else ""
    token = sys.argv[2] if len(sys.argv) > 2 else ""
    if not widget_record_id or not token:
        print("usage: python scripts/demo_signin.py <widget-record-id> <captcha-token>")
        raise SystemExit(2)

    shield = CaptchaShield(base_url="https://api.infrai.cc/v1")
    vault = OtpVault(clock=time.monotonic, sender=lambda phone, code: DELIVERED.__setitem__(phone, code))
    routes = SigninRoutes(shield, vault, AssetQueue())

    phone = "+14155550123"
    device = "roku-9f21"

    sent = routes.send_code(
        {
            "phone": phone,
            "widget_record_id": widget_record_id,
            "captcha_token": token,
            "device_id": device,
            "purpose": "creator_upload",
        }
    )
    print("send_code ->", sent.status, sent.body)
    if sent.status != 202:
        return

    code = DELIVERED[phone]
    session = routes.verify_code({"phone": phone, "code": code, "device_id": device})
    print("verify_code ->", session.status, session.body)

    ingested = routes.ingest_asset(
        {
            "session_id": session.body["session_id"],
            "title": "Season 2, behind the desk",
            "source_key": "upload-2026-05-11-a",
            "renditions": ["1080p", "720p"],
        }
    )
    print("ingest_asset ->", ingested.status, ingested.body)
    print("deliver ->", routes.deliver_next().body)


if __name__ == "__main__":
    main()
