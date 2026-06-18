"""Tests for Stanbic payment helpers."""

import pytest

from moneyline.payments.stanbic import (
    format_stk_amount,
    normalize_dbs_reference_id,
    normalize_stk_response,
    parse_stk_callback,
    StanbicError,
)


def test_format_stk_amount() -> None:
    assert format_stk_amount(400) == "400.00"
    assert format_stk_amount(1200) == "1200.00"


def test_normalize_dbs_reference_id_strips_non_alnum() -> None:
    assert normalize_dbs_reference_id("ML-MON--1003860766281") == "MLMON1003860766281"


def test_normalize_stk_response_swagger_success() -> None:
    data = {
        "dbsReferenceId": "REW21331DR5F1",
        "status": "Success",
        "statusMessage": "Request processed successfully",
    }
    out = normalize_stk_response(data)
    assert out["CheckoutRequestID"] == "REW21331DR5F1"
    assert out["ResponseDescription"] == "Request processed successfully"
    assert out["status"] == "Success"


def test_normalize_stk_response_legacy_response_message() -> None:
    data = {
        "dbsReferenceId": "MLMON1003860766281",
        "status": "Success",
        "responseMessage": "Request processed successfully",
    }
    out = normalize_stk_response(data)
    assert out["CheckoutRequestID"] == "MLMON1003860766281"


def test_normalize_stk_response_error_message() -> None:
    with pytest.raises(StanbicError, match="Invalid mobile number"):
        normalize_stk_response(
            {
                "dbsReferenceId": "REW21331DR5F1",
                "responseCode": "2001",
                "responseMessage": "Invalid mobile number",
            }
        )


def test_parse_stk_callback_stanbic_status_success() -> None:
    parsed = parse_stk_callback(
        {
            "dbsReferenceId": "MLMON1003860766281",
            "status": "Success",
            "statusMessage": "Payment completed",
            "mpesa_receipt_number": "ABC123",
        }
    )
    assert parsed["checkout_request_id"] == "MLMON1003860766281"
    assert parsed["result_code"] == 0
    assert parsed["mpesa_receipt"] == "ABC123"


def test_normalize_stk_response_nested() -> None:
    data = {
        "data": {
            "checkout_request_id": "ws_CO_abc",
            "merchant_request_id": "mr_abc",
            "customer_message": "Success. Request accepted for processing",
        }
    }
    out = normalize_stk_response(data)
    assert out["CheckoutRequestID"] == "ws_CO_abc"
    assert out["MerchantRequestID"] == "mr_abc"


def test_parse_stk_callback_daraja_shape() -> None:
    payload = {
        "Body": {
            "stkCallback": {
                "CheckoutRequestID": "ws_CO_1",
                "ResultCode": 0,
                "ResultDesc": "OK",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "MpesaReceiptNumber", "Value": "R123"},
                        {"Name": "PhoneNumber", "Value": 254712345678},
                    ]
                },
            }
        }
    }
    parsed = parse_stk_callback(payload)
    assert parsed["checkout_request_id"] == "ws_CO_1"
    assert parsed["result_code"] == 0
    assert parsed["mpesa_receipt"] == "R123"


def test_parse_stk_callback_flat_shape() -> None:
    parsed = parse_stk_callback(
        {
            "checkout_request_id": "ws_CO_2",
            "result_code": 0,
            "result_desc": "OK",
            "mpesa_receipt_number": "R456",
        }
    )
    assert parsed["checkout_request_id"] == "ws_CO_2"
    assert parsed["mpesa_receipt"] == "R456"
