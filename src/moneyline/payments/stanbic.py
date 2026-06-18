"""Stanbic Bank Kenya Connect API — M-Pesa STK checkout (Swagger 1.0.0)."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from moneyline.config.settings import get_settings

logger = logging.getLogger(__name__)

# Official Connect hosts (see STK PUSH M-PESA CHECKOUT API Swagger)
SANDBOX_HOST = "https://sandbox.connect.stanbicbank.co.ke"
PRODUCTION_HOST = "https://connect.stanbicbank.co.ke"
SANDBOX_TOKEN_URL = f"{SANDBOX_HOST}/api/sandbox/auth/oauth2/token"
SANDBOX_STK_URL = f"{SANDBOX_HOST}/api/sandbox/mpesa-checkout"
PRODUCTION_TOKEN_URL = f"{PRODUCTION_HOST}/api/production/auth/oauth2/token"
PRODUCTION_STK_URL = f"{PRODUCTION_HOST}/api/production/mpesa-checkout"

# Swagger: dbsReferenceId example REW21331DR5F1
_DBS_REF_PATTERN = re.compile(r"^[A-Za-z0-9]+$")


class StanbicError(RuntimeError):
    pass


def format_stk_amount(amount: int | float) -> str:
    """Swagger amount is a string decimal, e.g. \"10.00\"."""
    return f"{float(amount):.2f}"


def normalize_dbs_reference_id(reference: str) -> str:
    """Stanbic STKPushRequest: alphanumeric unique reference per request."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", reference.strip())
    if not cleaned:
        raise StanbicError("Payment reference is empty after sanitization")
    if len(cleaned) > 32:
        cleaned = cleaned[:32]
    if not _DBS_REF_PATTERN.match(cleaned):
        raise StanbicError("Payment reference must be alphanumeric (Stanbic dbsReferenceId)")
    return cleaned


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


def _raise_if_error_payload(data: dict[str, Any]) -> None:
    """Swagger errorMessage: responseCode + responseMessage."""
    response_code = _pick(data, "responseCode", "ResponseCode")
    if response_code is not None and not _is_success_status(data):
        message = _pick(data, "responseMessage", "statusMessage", "message") or "STK request failed"
        raise StanbicError(f"{message} (code {response_code})")
    if _pick(data, "responseMessage") and not _is_success_status(data):
        raise StanbicError(str(_pick(data, "responseMessage")))


def normalize_stk_response(data: dict[str, Any]) -> dict[str, Any]:
    """Map STKPushResponse to internal checkout fields."""
    _raise_if_error_payload(data)

    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    checkout = _pick(
        data,
        "dbsReferenceId",
        "dbs_reference_id",
        "CheckoutRequestID",
        "checkoutRequestId",
        "checkout_request_id",
    )
    if checkout is None and nested:
        checkout = _pick(
            nested,
            "dbsReferenceId",
            "dbs_reference_id",
            "CheckoutRequestID",
            "checkoutRequestId",
            "checkout_request_id",
        )
    merchant = _pick(data, "MerchantRequestID", "merchantRequestId", "merchant_request_id")
    if merchant is None and nested:
        merchant = _pick(nested, "MerchantRequestID", "merchantRequestId", "merchant_request_id")

    # Swagger success field is statusMessage; some responses use responseMessage.
    description = _pick(
        data,
        "statusMessage",
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
            "statusMessage",
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
                "STK push accepted by Stanbic but no dbsReferenceId was returned. "
                "Check your phone for the M-Pesa prompt."
            )
        raise StanbicError(
            _pick(data, "errorMessage", "message", "responseMessage", "statusMessage") or str(data)
        )

    return {
        "CheckoutRequestID": str(checkout),
        "MerchantRequestID": str(merchant or checkout),
        "ResponseDescription": str(description or "STK push accepted"),
        "dbsReferenceId": str(_pick(data, "dbsReferenceId") or checkout),
        "status": str(_pick(data, "status", "Status") or "Success"),
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
            "dbsReferenceId",
            "dbs_reference_id",
            "checkout_request_id",
            "CheckoutRequestID",
            "checkoutRequestId",
        )
        or ""
    )
    result_code_raw = _pick(payload, "result_code", "ResultCode", "responseCode")
    if result_code_raw is None:
        status = str(_pick(payload, "status", "Status") or "").strip().lower()
        if status in {"success", "completed", "ok"}:
            result_code_raw = 0
        elif status in {"failed", "error", "cancelled"}:
            result_code_raw = 1
    result_code = int(result_code_raw if result_code_raw is not None else -1)
    result_desc = str(
        _pick(
            payload,
            "statusMessage",
            "result_desc",
            "ResultDesc",
            "failure_reason",
            "responseMessage",
        )
        or ""
    )
    mpesa_receipt = _pick(
        payload,
        "mpesa_receipt_number",
        "mpesaReceiptNumber",
        "MpesaReceiptNumber",
    )
    phone = _pick(payload, "phone", "phoneNumber", "PhoneNumber", "mobileNumber")
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
        self.is_production = self.settings.stanbic_env.strip().lower() == "production"

    def token_url(self) -> str:
        override = self.settings.stanbic_token_url.strip()
        if override:
            return override
        return PRODUCTION_TOKEN_URL if self.is_production else SANDBOX_TOKEN_URL

    def stk_url(self) -> str:
        override = self.settings.stanbic_stk_url.strip()
        if override:
            return override
        return PRODUCTION_STK_URL if self.is_production else SANDBOX_STK_URL

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
                    "sandbox.stanbicbank.co.ke (scope: payments)."
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

        dbs_ref = normalize_dbs_reference_id(account_reference)
        token = await self.get_access_token()

        # STKPushRequest (Swagger): only these four fields are defined.
        body: dict[str, str] = {
            "dbsReferenceId": dbs_ref,
            "billAccountRef": bill_account,
            "amount": format_stk_amount(amount),
            "mobileNumber": phone,
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Auth": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(self.stk_url(), json=body, headers=headers)
            if not resp.content:
                raise StanbicError(f"Empty STK response (HTTP {resp.status_code})")
            data = resp.json()

        if resp.status_code not in (200, 201):
            if isinstance(data, dict):
                _raise_if_error_payload(data)
            raise StanbicError(data.get("message") or data.get("error") or resp.text)

        return normalize_stk_response(data if isinstance(data, dict) else {"raw": data})
