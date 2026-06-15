from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone

import httpx

from moneyline.config.settings import get_settings

logger = logging.getLogger(__name__)

SANDBOX_BASE = "https://sandbox.safaricom.co.ke"
PRODUCTION_BASE = "https://api.safaricom.co.ke"


class MpesaError(RuntimeError):
    pass


class MpesaClient:
    """Safaricom Daraja Lipa na M-Pesa Online (STK Push)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = PRODUCTION_BASE if self.settings.mpesa_env == "production" else SANDBOX_BASE

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    def _password(self, timestamp: str) -> str:
        raw = f"{self.settings.mpesa_shortcode}{self.settings.mpesa_passkey}{timestamp}"
        return base64.b64encode(raw.encode()).decode()

    async def get_access_token(self) -> str:
        key = self.settings.mpesa_consumer_key.strip()
        secret = self.settings.mpesa_consumer_secret.strip()
        if not key or not secret:
            raise MpesaError("MPESA_CONSUMER_KEY and MPESA_CONSUMER_SECRET are required")

        url = f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, auth=(key, secret))
            data = resp.json()

        if resp.status_code != 200 or "access_token" not in data:
            raise MpesaError(data.get("errorMessage") or data.get("error") or resp.text)
        return str(data["access_token"])

    async def stk_push(
        self,
        *,
        phone: str,
        amount: int,
        account_reference: str,
        transaction_desc: str,
    ) -> dict:
        callback_url = self.settings.mpesa_callback_url.strip()
        shortcode = self.settings.mpesa_shortcode.strip()
        till_number = self.settings.mpesa_till_number.strip()
        if not callback_url:
            raise MpesaError("MPESA_CALLBACK_URL is required for STK push")
        if not shortcode or not self.settings.mpesa_passkey.strip():
            raise MpesaError("MPESA_SHORTCODE and MPESA_PASSKEY are required")
        if not till_number:
            raise MpesaError("MPESA_TILL_NUMBER is required for Buy Goods STK push")

        party_b = till_number
        token = await self.get_access_token()
        timestamp = self._timestamp()
        payload = {
            "BusinessShortCode": shortcode,
            "Password": self._password(timestamp),
            "Timestamp": timestamp,
            "TransactionType": self.settings.mpesa_transaction_type,
            "Amount": int(amount),
            "PartyA": phone,
            "PartyB": party_b,
            "PhoneNumber": phone,
            "CallBackURL": callback_url,
            "AccountReference": account_reference[:12],
            "TransactionDesc": transaction_desc[:13],
        }

        url = f"{self.base_url}/mpesa/stkpush/v1/processrequest"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            data = resp.json()

        if resp.status_code != 200:
            raise MpesaError(data.get("errorMessage") or resp.text)

        if str(data.get("ResponseCode", "")) != "0":
            raise MpesaError(data.get("ResponseDescription") or "STK push rejected")

        logger.info("STK push initiated for %s amount %s", phone, amount)
        return data
