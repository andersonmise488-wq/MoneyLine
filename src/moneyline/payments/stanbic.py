"""Stanbic Bank Kenya Connect API — M-Pesa STK checkout."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from moneyline.config.settings import get_settings

logger = logging.getLogger(__name__)

SANDBOX_API_BASE = "https://sandbox.connect.stanbicbank.co.ke/api/sandbox"
PRODUCTION_API_BASE = "https://connect.stanbicbank.co.ke/api/production"


class StanbicError(RuntimeError):
    pass


def _pick(data: dict[str, Any], *keys: str) -> Any:
    lower = {str(k).lower(): v for k, v in data.items()}
    for key in keys:
        if key in data:
            return data[key]
        if key.lower() in lower:
            return lower[key.lower()]
    return None


def _is_success_status(data: dict[str, Any]) -> bool:
    status = str(_pick(data, "status", "Status") or "").strip().lower()
    return status in {"success", "ok", "completed", "accepted"}


def normalize_stk_response(data: dict[str, Any]) -> dict[str, Any]:
    """Map Stanbic / M-Pesa STK initiate responses to a common shape."""
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    checkout = _pick(
        data,
        "CheckoutRequestID",
        "checkoutRequestId",
        "checkout_request_id",
        "dbsReferenceId",
        "dbs_reference_id",
    )
    if checkout is None and nested:
        checkout = _pick(
            nested,
            "CheckoutRequestID",
            "checkoutRequestId",
            "checkout_request_id",
            "dbsReferenceId",
            "dbs_reference_id",
        )
    merchant = _pick(data, "MerchantRequestID", "merchantRequestId", "merchant_request_id")
    if merchant is None and nested:
        merchant = _pick(nested, "MerchantRequestID", "merchantRequestId", "merchant_request_id")
    description = _pick(
        data,
        "responseMessage",
        "ResponseDescription",
        "responseDescription",
        "CustomerMessage",
        "customer_message",
        "message",
    )
    if description is None and nested:
        description = _pick(
            nested,
            "responseMessage",
            "ResponseDescription",
            "responseDescription",
            "CustomerMessage",
            "customer_message",
            "message",
        )
    if not checkout:
        if _is_success_status(data):
            raise StanbicError(
                "STK push accepted by Stanbic but no transaction reference was returned. "
                "Check your phone for the M-Pesa prompt."
            )
        raise StanbicError(
            _pick(data, "errorMessage", "message", "responseMessage") or str(data)
        )
    return {
        "CheckoutRequestID": str(checkout),
        "MerchantRequestID": str(merchant or checkout),
        "ResponseDescription": str(description or "STK push accepted"),
        "dbsReferenceId": str(_pick(data, "dbsReferenceId") or checkout),
    }


def parse_stk_callback(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize Stanbic or legacy M-Pesa callback payloads."""
    body = payload.get("Body", {})
    callback = body.get("stkCallback", {}) if isinstance(body, dict) else {}
    if callback:
        checkout_request_id = str(callback.get("CheckoutRequestID", ""))
        result_code = int(callback.get("ResultCode", -1))
        result_desc = str(callback.get("ResultDesc", ""))
        mpesa_receipt = None
        phone = None
        if result_code == 0:
            metadata = callback.get("CallbackMetadata", {}).get("Item", [])
            for item in metadata:
                name = item.get("Name")
                value = item.get("Value")
                if name == "MpesaReceiptNumber":
                    mpesa_receipt = str(value)
                elif name == "PhoneNumber":
                    phone = str(value)
        return {
            "checkout_request_id": checkout_request_id,
            "result_code": result_code,
            "result_desc": result_desc,
            "mpesa_receipt": mpesa_receipt,
            "phone": phone,
        }

    checkout_request_id = str(
        _pick(
            payload,
            "checkout_request_id",
            "CheckoutRequestID",
            "checkoutRequestId",
            "dbsReferenceId",
            "dbs_reference_id",
        )
        or ""
    )
    result_code_raw = _pick(payload, "result_code", "ResultCode")
    if result_code_raw is None:
        status = str(_pick(payload, "status", "Status") or "").strip().lower()
        if status in {"success", "completed", "ok"}:
            result_code_raw = 0
        elif status in {"failed", "error", "cancelled"}:
            result_code_raw = 1
    result_code = int(result_code_raw if result_code_raw is not None else -1)
    result_desc = str(
        _pick(payload, "result_desc", "ResultDesc", "failure_reason", "responseMessage")
        or ""
    )
    mpesa_receipt = _pick(
        payload,
        "mpesa_receipt_number",
        "mpesaReceiptNumber",
        "MpesaReceiptNumber",
    )
    phone = _pick(payload, "phone", "phoneNumber", "PhoneNumber")
    return {
        "checkout_request_id": checkout_request_id,
        "result_code": result_code,
        "result_desc": result_desc,
        "mpesa_receipt": str(mpesa_receipt) if mpesa_receipt is not None else None,
        "phone": str(phone) if phone is not None else None,
    }


class StanbicClient:
    """Stanbic Connect M-Pesa checkout (STK push)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.api_base = (
            PRODUCTION_API_BASE
            if self.settings.stanbic_env.strip().lower() == "production"
            else SANDBOX_API_BASE
        )

    def token_url(self) -> str:
        override = self.settings.stanbic_token_url.strip()
        return override or f"{self.api_base}/auth/oauth2/token"

    def stk_url(self) -> str:
        override = self.settings.stanbic_stk_url.strip()
        return override or f"{self.api_base}/mpesa-checkout"

    async def get_access_token(self) -> str:
        client_id = self.settings.stanbic_client_id.strip()
        client_secret = self.settings.stanbic_client_secret.strip()
        if not client_id or not client_secret:
            raise StanbicError("STANBIC_CLIENT_ID and STANBIC_CLIENT_SECRET are required")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                self.token_url(),
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "client_credentials",
                    "scope": "payments",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            data = resp.json() if resp.content else {}

        if resp.status_code >= 400 or "access_token" not in data:
            detail = data.get("error_description") or data.get("message") or resp.text
            if "not subscribed" in str(detail).lower():
                detail += (
                    " — subscribe your app to STK PUSH – M-PESA CHECKOUT on "
                    "sandbox.stanbicbank.co.ke and use that product's token URL."
                )
            raise StanbicError(detail)
        return str(data["access_token"])

    async def stk_push(
        self,
        *,
        phone: str,
        amount: int,
        account_reference: str,
    ) -> dict[str, Any]:
        bill_account = self.settings.stanbic_bill_account_ref.strip()
        if not bill_account:
            raise StanbicError("STANBIC_BILL_ACCOUNT_REF is required")

        token = await self.get_access_token()
        payload: dict[str, Any] = {
            "dbsReferenceId": account_reference,
            "billAccountRef": bill_account,
            "amount": str(amount),
            "mobileNumber": phone,
        }
        callback_url = self.settings.stanbic_callback_url.strip()
        if callback_url and "your-domain" not in callback_url:
            payload["callbackUrl"] = callback_url

        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                self.stk_url(),
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            if not resp.content:
                raise StanbicError(f"Empty STK response (HTTP {resp.status_code})")
            data = resp.json()

        if resp.status_code not in (200, 201):
            raise StanbicError(data.get("message") or data.get("error") or resp.text)

        return normalize_stk_response(data if isinstance(data, dict) else {"raw": data})
