"""Tests for Stanbic payment helpers."""

from moneyline.payments.stanbic import normalize_stk_response, parse_stk_callback


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
