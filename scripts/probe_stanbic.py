"""Probe Stanbic Connect API credentials (OAuth token)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from moneyline.config.settings import get_settings
from moneyline.payments.stanbic import StanbicClient, StanbicError


def _mask(value: str) -> str:
    value = value.strip()
    if len(value) <= 8:
        return "***" if value else "MISSING"
    return f"{value[:4]}...{value[-4:]}"


def main() -> None:
    settings = get_settings()
    env = settings.stanbic_env.strip().lower()
    client = StanbicClient()

    print("=== Stanbic Connect probe ===")
    print(f"STANBIC_ENV:              {env}")
    print(f"STK endpoint (Swagger):    {client.stk_url()}")
    print(f"STANBIC_PAYMENT_MODE:     {settings.stanbic_payment_mode}")
    print(f"Client ID:                {_mask(settings.stanbic_client_id)}")
    print(f"Client secret:            {'set' if settings.stanbic_client_secret.strip() else 'MISSING'}")
    print(f"Bill account:             {settings.stanbic_bill_account_ref or 'MISSING'}")
    print(f"Callback URL:             {settings.stanbic_callback_url or 'MISSING'}")
    print(f"Billing mode:             {settings.billing_mode()}")
    print()

    if not settings.stanbic_client_id.strip() or not settings.stanbic_client_secret.strip():
        print("Set STANBIC_CLIENT_ID and STANBIC_CLIENT_SECRET from the Stanbic developer portal.")
        sys.exit(1)

    print(f"Token URL: {client.token_url()}")
    print("Requesting OAuth token…")

    async def _run() -> None:
        try:
            token = await client.get_access_token()
            print(f"OK — access token received ({len(token)} chars)")
        except StanbicError as exc:
            print(f"FAILED — {exc}")
            sys.exit(1)

    asyncio.run(_run())

    if not settings.stanbic_bill_account_ref.strip():
        print("\nNext: set STANBIC_BILL_ACCOUNT_REF (Stanbic account that receives payments).")
    if not settings.stanbic_callback_url.strip() or "your-domain" in settings.stanbic_callback_url:
        print(
            "\nNext: set STANBIC_CALLBACK_URL to a public HTTPS URL, "
            "e.g. https://yourdomain.com/stanbic/callback"
        )
    print(
        "\nIf OAuth fails with 'not subscribed', open sandbox.stanbicbank.co.ke -> Apps -> "
        "subscribe to Send Money - Sandbox / STK PUSH - M-PESA CHECKOUT."
    )
    if settings.subscription_demo_mode:
        print("\nNote: SUBSCRIPTION_DEMO_MODE=true — subscriptions auto-activate without charging.")
    elif settings.stanbic_configured():
        print("\nStanbic looks ready. Set SUBSCRIPTION_DEMO_MODE=false for live STK charges.")


if __name__ == "__main__":
    main()
