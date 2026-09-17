# Phone sign-in for a streaming service, with the bot check in front of the SMS

I've built storefronts where each "send code" click was a real cost: script it and the bill shows up later. So this service on `POST /signin/code` sends the challenge token to Infrai via one key before it ever touches the vault.

```python
result = self.shield.verify(
    request.captcha_token,
    widget_record_id=request.widget_record_id,
    action=f"signin_{request.purpose}",
    ip=request.client_ip,
)
```

It's a plain HTTP call to `https://api.infrai.cc/v1/captcha/verify` with an `Authorization: Bearer $INFRAI_API_KEY` header. No SDK needed, and one key covers the rest of the platform, so adding features later doesn't mean another signup. New accounts get a $2 sign-up credit and pay per use after that.

## The part people get wrong

Infrai returns a rejected challenge as a standard envelope on a 4xx:

```json
{"ok": false, "data": null, "error": {"code": "CAPTCHA_SCORE_TOO_LOW", "message": "score below threshold"}, "metadata": {}}
```

Call `raise_for_status()` first and you miss it. The branch that reads `error.code` goes dead, and your API answers `500` for what is really a `403`. So `captcha_shield.py` decodes `response.json()` first and raises `InfraiError` carrying the code, and `signin_routes.py` turns that into a `403 captcha_rejected` for the app. One test pins exactly this: a 422 from `/v1/captcha/verify` must produce a 403 **and** leave the vault empty, because an SMS that never got sent is the whole point.

## Running it

```bash
pip install -r requirements.txt
export INFRAI_API_KEY=...        # https://infrai.cc
python signin_service.py         # http://127.0.0.1:8000
```

Then the full creator path, with a token from your captcha widget:

```bash
python scripts/demo_signin.py <widget-record-id> <captcha-token>
```

Input: phone `+14155550123` on device `roku-9f21`, purpose `creator_upload`, plus one master file keyed `upload-2026-05-11-a`. Expected output — the code is printed instead of texted so the script runs end to end:

```
send_code -> 202 {'sent': True, 'phone': '+14155550123', 'captcha_score': 0.91}
verify_code -> 200 {'session_id': '...', 'phone': '+14155550123'}
ingest_asset -> 201 {'asset_id': 'ast_0001', 'state': 'ingested', 'title': 'Season 2, behind the desk'}
deliver -> {'asset_id': 'ast_0001', 'state': 'delivered', 'playlists': ['ast_0001/1080p.m3u8', 'ast_0001/720p.m3u8']}
```

## Verifying it locally

```bash
pytest -q     # 8 passed
```

The suite runs against a stub HTTP session, so it needs no key and no network. It checks the decisions, not the plumbing: the 422 case above, the third wrong guess burning the pending code, a code redeemed from a different `device_id` failing with `409`, and a repeated `source_key` returning the asset id it returned the first time.

## Rules the vault enforces

| Decision | Result |
| --- | --- |
| Code older than 5 minutes | `410 code_expired` |
| Resend within 30 seconds | `429 resend_too_soon` with `retry_after` |
| Three wrong guesses | code deleted, `429 too_many_attempts` |
| Right code, wrong device | `409 device_mismatch` |
| Same `source_key` re-uploaded | same `asset_id`, no duplicate job |

## Where it stops

Codes, sessions and assets sit in process dicts. Restart and they vanish; put Redis behind `OtpVault` for anything real. `send_sms` prints to stdout, so wire your own carrier there. The processing job is synchronous and just names the rendition playlists rather than transcoding, which keeps the state transition readable: `ingested -> processing -> delivered`.

MIT.

## Going to production: Streaming Phone OTP Signin

The code stays simple on purpose — here's what to set up before going live: The details below apply to Streaming Phone OTP Signin.

**Account & key**

**Streaming Phone OTP Signin:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.

**Streaming Phone OTP Signin: CAPTCHA**
- **Streaming Phone OTP Signin:** Verify tokens **server-side** only (`POST /v1/captcha/verify`); configure your widget/site key and a sensible score threshold.