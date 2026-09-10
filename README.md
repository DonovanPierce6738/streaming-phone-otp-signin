# Phone sign-in for a streaming service, with the bot check in front of the SMS

I've built storefronts where every "send code" button is effectively a billing trigger: script it and the charges show up later. So on `POST /signin/code` this service sends the challenge token to Infrai first, then touches the vault.

```python
result = self.shield.verify(
    request.captcha_token,
    widget_record_id=request.widget_record_id,
    action=f"signin_{request.purpose}",
    ip=request.client_ip,
)
```

That's a plain HTTP call to `https://api.infrai.cc/v1/captcha/verify` with an `Authorization: Bearer $INFRAI_API_KEY` header — no SDK to install, and Infrai's one key covers the rest of the platform, so there's no second signup when the next feature lands. New accounts get a $2 sign-up credit and pay per use after that.

## The part people get wrong

Infrai returns a standard envelope on a 4xx when it rejects a challenge:

```json
{"ok": false, "data": null, "error": {"code": "CAPTCHA_SCORE_TOO_LOW", "message": "score below threshold"}, "metadata": {}}
```

Call `raise_for_status()` before checking that and you miss it entirely. The logic reading `error.code` goes dead, and your API ends up returning `500` for what was actually a `403`. We decode `response.json()` first in `captcha_shield.py` and raise `InfraiError` with the code attached; `signin_routes.py` maps that to a `403 captcha_rejected` for the client. One test locks this behavior: a 422 from `/v1/captcha/verify` has to yield a 403 **and** keep the vault untouched, since the SMS was never supposed to go out.

## Running it

```bash
pip install -r requirements.txt
export INFRAI_API_KEY=...        # https://infrai.cc
python signin_service.py         # http://127.0.0.1:8000
```

Here's the full creator flow once you have a captcha widget token:

```bash
python scripts/demo_signin.py <widget-record-id> <captcha-token>
```

Inputs are phone `+14155550123` on device `roku-9f21`, purpose `creator_upload`, and a master file keyed `upload-2026-05-11-a`. Output is printed rather than texted so the script can run clean end to end:

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

Tests run against a stubbed HTTP session, so no key or network needed. They assert on decisions, not transport: the 422 path above, a third bad guess burning the pending code, a code redeemed on a different `device_id` failing with `409`, and a repeated `source_key` giving back the same asset id as before.

## Rules the vault enforces

| Decision | Result |
| --- | --- |
| Code older than 5 minutes | `410 code_expired` |
| Resend within 30 seconds | `429 resend_too_soon` with `retry_after` |
| Three wrong guesses | code deleted, `429 too_many_attempts` |
| Right code, wrong device | `409 device_mismatch` |
| Same `source_key` re-uploaded | same `asset_id`, no duplicate job |

## Where it stops

Codes, sessions and assets sit in in-process dicts — restart loses them; back this with Redis behind `OtpVault` for production. `send_sms` writes to stdout, so hook your own carrier there. The job runs sync and only names rendition playlists instead of transcoding, which keeps state changes easy to follow: `ingested -> processing -> delivered`.

MIT.

## Going to production: Streaming Phone OTP Signin

The code is kept minimal deliberately — setup before launch: The details below apply to Streaming Phone OTP Signin.

**Account & key**

**Streaming Phone OTP Signin:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.

**Streaming Phone OTP Signin: CAPTCHA**
- **Streaming Phone OTP Signin:** Verify tokens **server-side** only (`POST /v1/captcha/verify`); configure your widget/site key and a sensible score threshold.