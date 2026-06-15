#!/usr/bin/env python3
"""Probe Safaricom Daraja — OAuth and STK push readiness."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from moneyline.config.settings import get_settings
from moneyline.payments.mpesa import MpesaClient, MpesaError, PRODUCTION_BASE, SANDBOX_BASE


def _mask(value: str, show: int = 4) -> str:
    value = value.strip()
    if not value:
        return "(empty)"
    if len(value) <= show * 2:
        return "*" * len(value)
    return f"{value[:show]}…{value[-show:]}"


def _checklist(settings) -> list[tuple[str, bool, str]]:
    items = [
        (
            "Consumer key",
            bool(settings.mpesa_consumer_key.strip()),
            _mask(settings.mpesa_consumer_key),
        ),
        (
            "Consumer secret",
            bool(settings.mpesa_consumer_secret.strip()),
            _mask(settings.mpesa_consumer_secret),
        ),
        (
            "Passkey (Lipa na M-Pesa Online)",
            bool(settings.mpesa_passkey.strip()),
            "set" if settings.mpesa_passkey.strip() else "MISSING",
        ),
        (
            "Callback URL (public HTTPS)",
            bool(settings.mpesa_callback_url.strip())
            and "your-domain" not in settings.mpesa_callback_url,
            settings.mpesa_callback_url or "MISSING",
        ),
        (
            "Shortcode (BusinessShortCode)",
            bool(settings.mpesa_shortcode.strip()),
            settings.mpesa_shortcode,
        ),
        (
            "Till (PartyB for Buy Goods)",
            bool(settings.mpesa_till_number.strip()),
            settings.mpesa_till_number,
        ),
    ]
    return items


async def _probe_oauth(client: MpesaClient) -> dict:
    try:
        token = await client.get_access_token()
        return {"ok": True, "token_preview": _mask(token, 8)}
    except MpesaError as exc:
        return {"ok": False, "error": str(exc)}


async def _probe_stk_dry(client: MpesaClient) -> dict:
    """Attempt STK with a sandbox test number — only when fully configured."""
    settings = get_settings()
    if not settings.mpesa_passkey.strip():
        return {"skipped": True, "reason": "MPESA_PASSKEY not set"}
    if not settings.mpesa_callback_url.strip() or "your-domain" in settings.mpesa_callback_url:
        return {"skipped": True, "reason": "MPESA_CALLBACK_URL not set to a real public URL"}

    # Safaricom sandbox test MSISDN
    test_phone = "254708374149"
    try:
        data = await client.stk_push(
            phone=test_phone,
            amount=1,
            account_reference="ML-PROBE",
            transaction_desc="MoneyLine probe",
        )
        return {
            "ok": True,
            "checkout_request_id": data.get("CheckoutRequestID"),
            "response_description": data.get("ResponseDescription"),
            "customer_message": data.get("CustomerMessage"),
        }
    except MpesaError as exc:
        return {"ok": False, "error": str(exc)}


async def _probe_env_oauth(env: str) -> dict:
    import httpx

    settings = get_settings()
    key = settings.mpesa_consumer_key.strip()
    secret = settings.mpesa_consumer_secret.strip()
    base = PRODUCTION_BASE if env == "production" else SANDBOX_BASE
    if not key or not secret:
        return {"ok": False, "error": "Missing consumer key/secret"}
    url = f"{base}/oauth/v1/generate?grant_type=client_credentials"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, auth=(key, secret))
            try:
                data = resp.json()
            except ValueError:
                data = {}
        if resp.status_code != 200 or "access_token" not in data:
            body_preview = resp.text[:200] if resp.text else "(empty body)"
            return {
                "ok": False,
                "status": resp.status_code,
                "error": data.get("errorMessage") or data.get("error") or body_preview,
            }
        return {"ok": True, "token_preview": _mask(str(data["access_token"]), 8)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def main() -> None:
    settings = get_settings()
    env = settings.mpesa_env
    base = PRODUCTION_BASE if env == "production" else SANDBOX_BASE

    print("=" * 60)
    print("MoneyLine Daraja probe")
    print("=" * 60)
    print(f"MPESA_ENV:              {env}")
    print(f"API base:               {base}")
    print(f"MPESA_PAYMENT_MODE:     {settings.mpesa_payment_mode}")
    print(f"Transaction type:       {settings.mpesa_transaction_type}")
    print(f"SUBSCRIPTION_DEMO_MODE: {settings.subscription_demo_mode}")
    print()

    print("Configuration checklist:")
    all_ok = True
    for label, ok, detail in _checklist(settings):
        mark = "OK" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"  [{mark}] {label}: {detail}")
    print()

    if env == "sandbox" and settings.mpesa_shortcode not in ("174379", "174379"):
        print(
            "NOTE: Sandbox usually requires shortcode 174379 (Paybill test) or portal-assigned "
            "sandbox till credentials — production store 7113597 may not work in sandbox."
        )
        print()

    client = MpesaClient()
    print("1) OAuth token (current MPESA_ENV)…")
    oauth = await _probe_oauth(client)
    print(json.dumps(oauth, indent=2))
    print()

    other_env = "production" if env == "sandbox" else "sandbox"
    print(f"1b) OAuth token ({other_env}, same consumer key)…")
    other_oauth = await _probe_env_oauth(other_env)
    print(json.dumps(other_oauth, indent=2))
    print()

    if oauth.get("ok"):
        print("2) STK push probe (KES 1 to sandbox test line if configured)…")
        stk = await _probe_stk_dry(client)
        print(json.dumps(stk, indent=2))
    else:
        print("2) STK push probe skipped (OAuth failed)")
    print()

    print("Next steps to enable Daraja STK:")
    steps = []
    if not settings.mpesa_passkey.strip():
        steps.append(
            "Get Lipa na M-Pesa Online passkey from https://developer.safaricom.co.ke "
            "- your app - Lipa na M-Pesa Online - show/generate passkey"
        )
    if not settings.mpesa_callback_url.strip() or "your-domain" in settings.mpesa_callback_url:
        steps.append(
            "Set MPESA_CALLBACK_URL to a public HTTPS URL reachable by Safaricom, "
            "e.g. https://yourdomain.com/mpesa/callback (ngrok/Cloudflare tunnel works for testing)"
        )
    if env == "sandbox":
        steps.append(
            "For sandbox testing use Daraja sandbox shortcode/passkey from the portal, "
            "or switch MPESA_ENV=production after Safaricom go-live approval"
        )
    if env == "production":
        steps.append(
            "Confirm Buy Goods go-live for store 7113597 / till 5074619 with Safaricom"
        )
    steps.append("Set MPESA_PAYMENT_MODE=daraja and SUBSCRIPTION_DEMO_MODE=false")
    steps.append("Restart API — bot will auto STK-push on /subscribe + phone number")

    for i, step in enumerate(steps, 1):
        print(f"  {i}. {step}")

    if all_ok and oauth.get("ok"):
        print("\nAll credentials present — run again after go-live to test live STK.")
    elif not oauth.get("ok"):
        print("\nOAuth failed — verify consumer key/secret match MPESA_ENV (sandbox vs production).")


if __name__ == "__main__":
    asyncio.run(main())
