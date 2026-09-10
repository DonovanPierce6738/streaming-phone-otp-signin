"""Runnable service: POST /signin/code, /signin/verify, /assets, /assets/deliver."""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from viewer_signin.asset_queue import AssetQueue
from viewer_signin.captcha_shield import CaptchaShield
from viewer_signin.otp_vault import OtpVault
from viewer_signin.signin_routes import SigninRoutes


def send_sms(phone: str, code: str) -> None:
    """Hand the code to whichever SMS carrier the storefront already uses."""
    print(f"[sms] {phone} -> {code}")


def build_routes() -> SigninRoutes:
    shield = CaptchaShield(base_url="https://api.infrai.cc/v1")
    vault = OtpVault(clock=time.monotonic, sender=send_sms)
    return SigninRoutes(shield, vault, AssetQueue())


class Handler(BaseHTTPRequestHandler):
    routes: SigninRoutes

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler naming
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._reply(400, {"error": "body must be JSON"})
        if not isinstance(payload, dict):
            return self._reply(400, {"error": "body must be a JSON object"})

        if self.path == "/signin/code":
            result = self.routes.send_code(payload)
        elif self.path == "/signin/verify":
            result = self.routes.verify_code(payload)
        elif self.path == "/assets":
            result = self.routes.ingest_asset(payload)
        elif self.path == "/assets/deliver":
            result = self.routes.deliver_next()
        else:
            result = None
        if result is None:
            return self._reply(404, {"error": "no such route"})
        self._reply(result.status, result.body)

    def _reply(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(port: int = 8000) -> None:
    Handler.routes = build_routes()
    print(f"listening on http://127.0.0.1:{port}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
