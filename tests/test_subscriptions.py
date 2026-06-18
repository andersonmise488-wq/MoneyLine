from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from moneyline.alerts.telegram import resolve_alert_targets
from moneyline.subscriptions.models import SubscriptionPlan
from moneyline.subscriptions.plans import extend_expiry, normalize_phone
from moneyline.subscriptions.service import SubscriptionService
from moneyline.storage.subscriptions import SubscriptionRepository


def test_normalize_phone_local_format() -> None:
    assert normalize_phone("0712345678") == "254712345678"


def test_normalize_phone_international_format() -> None:
    assert normalize_phone("254712345678") == "254712345678"


def test_normalize_phone_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        normalize_phone("12345")


def test_extend_expiry_from_now() -> None:
    before = datetime.now(timezone.utc)
    expiry = extend_expiry(None, SubscriptionPlan.WEEKLY)
    assert expiry >= before + timedelta(days=7) - timedelta(seconds=2)


def test_extend_expiry_stacks_on_active_subscription() -> None:
    current = datetime.now(timezone.utc) + timedelta(days=5)
    expiry = extend_expiry(current, SubscriptionPlan.WEEKLY)
    assert expiry == current + timedelta(days=7)


@pytest.mark.asyncio
async def test_stk_callback_activates_subscriber(tmp_path) -> None:
    db_path = tmp_path / "subs.db"
    repo = SubscriptionRepository(db_path=db_path)
    repo.ensure_schema()
    service = SubscriptionService(repo=repo, stanbic=None)

    chat_id = "123456"
    service.begin_subscription(
        telegram_chat_id=chat_id,
        telegram_username="tester",
        plan=SubscriptionPlan.WEEKLY,
    )
    repo.set_pending_payment(
        telegram_chat_id=chat_id,
        phone="254712345678",
        plan=SubscriptionPlan.WEEKLY,
    )
    repo.create_transaction(
        checkout_request_id="ws_CO_123",
        merchant_request_id="mr_123",
        telegram_chat_id=chat_id,
        plan=SubscriptionPlan.WEEKLY,
        amount=400,
        phone="254712345678",
    )

    payload = {
        "Body": {
            "stkCallback": {
                "CheckoutRequestID": "ws_CO_123",
                "ResultCode": 0,
                "ResultDesc": "The service request is processed successfully.",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "Amount", "Value": 400},
                        {"Name": "MpesaReceiptNumber", "Value": "QAB123"},
                        {"Name": "PhoneNumber", "Value": 254712345678},
                    ]
                },
            }
        }
    }

    subscriber = await service.handle_stk_callback(payload)
    assert subscriber is not None
    assert subscriber.status == "active"
    assert subscriber.phone == "254712345678"
    assert subscriber.expires_at is not None

    active = service.list_active_subscribers()
    assert len(active) == 1
    assert active[0].telegram_chat_id == chat_id


def test_resolve_alert_targets_includes_admin_and_subscribers(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "subs.db"
    repo = SubscriptionRepository(db_path=db_path)
    repo.ensure_schema()

    expires = datetime.now(timezone.utc) + timedelta(days=7)
    repo.upsert_awaiting_phone(
        telegram_chat_id="999",
        telegram_username="sub",
        plan=SubscriptionPlan.MONTHLY,
    )
    repo.activate_subscriber(
        telegram_chat_id="999",
        plan=SubscriptionPlan.MONTHLY,
        phone="254700000000",
        expires_at=expires,
    )

    class FakeSettings:
        subscriber_alerts_enabled = True

        def admin_chat_ids(self) -> list[str]:
            return ["-100admin"]

    monkeypatch.setattr(
        "moneyline.alerts.telegram.get_settings",
        lambda: FakeSettings(),
    )
    monkeypatch.setattr(
        "moneyline.alerts.telegram.get_admin_chat_ids",
        lambda: ["-100admin"],
    )
    monkeypatch.setattr(
        "moneyline.subscriptions.service.SubscriptionService",
        lambda repo=None, stanbic=None: SubscriptionService(
            repo=repo or SubscriptionRepository(db_path=db_path)
        ),
    )

    targets = resolve_alert_targets()
    assert targets == ["999", "-100admin"]


def test_expire_due_subscribers_disconnects_access(tmp_path) -> None:
    db_path = tmp_path / "subs.db"
    repo = SubscriptionRepository(db_path=db_path)
    repo.ensure_schema()

    repo.upsert_awaiting_phone(
        telegram_chat_id="111",
        telegram_username="user1",
        plan=SubscriptionPlan.WEEKLY,
    )
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    repo.activate_subscriber(
        telegram_chat_id="111",
        plan=SubscriptionPlan.WEEKLY,
        phone="254712345678",
        expires_at=past,
    )

    expired_ids = repo.expire_due_subscribers()
    assert expired_ids == ["111"]
    assert repo.list_active_subscribers() == []

    sub = repo.get_subscriber("111")
    assert sub is not None
    assert sub.status == "expired"


def test_dashboard_stats_total_income(tmp_path) -> None:
    db_path = tmp_path / "subs.db"
    repo = SubscriptionRepository(db_path=db_path)
    repo.ensure_schema()
    service = SubscriptionService(repo=repo, stanbic=None)

    repo.upsert_awaiting_phone(
        telegram_chat_id="222",
        telegram_username="paid",
        plan=SubscriptionPlan.MONTHLY,
    )
    repo.create_transaction(
        checkout_request_id="ws_1",
        merchant_request_id="mr_1",
        telegram_chat_id="222",
        plan=SubscriptionPlan.MONTHLY,
        amount=1200,
        phone="254712345678",
    )
    repo.complete_transaction(
        checkout_request_id="ws_1",
        result_code=0,
        result_desc="OK",
        mpesa_receipt="ABC123",
        status="success",
    )

    data = service.dashboard_data()
    assert data.stats.total_income_kes == 1200
    assert data.stats.successful_payments == 1


@pytest.mark.asyncio
async def test_terminate_subscriber_disconnects_access(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "subs.db"
    repo = SubscriptionRepository(db_path=db_path)
    repo.ensure_schema()
    service = SubscriptionService(repo=repo, stanbic=None)

    chat_id = "888"
    service.begin_subscription(
        telegram_chat_id=chat_id,
        telegram_username="revoke_me",
        plan=SubscriptionPlan.WEEKLY,
    )
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    repo.activate_subscriber(
        telegram_chat_id=chat_id,
        plan=SubscriptionPlan.WEEKLY,
        phone="254712345678",
        expires_at=expires,
    )

    async def fake_notify(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "moneyline.bot.telegram_bot.notify_payment_success",
        fake_notify,
    )

    result = await service.terminate(chat_id, notify=True)

    assert result is not None
    assert result.status == "cancelled"
    assert repo.list_active_subscribers() == []
    sub = repo.get_subscriber(chat_id)
    assert sub is not None
    assert sub.status == "cancelled"


def test_write_dashboard_file(tmp_path) -> None:
    db_path = tmp_path / "subs.db"
    repo = SubscriptionRepository(db_path=db_path)
    repo.ensure_schema()
    service = SubscriptionService(repo=repo, stanbic=None)

    out = tmp_path / "dash.html"
    path = service.write_dashboard(output=out)
    assert path.exists()
    html = path.read_text(encoding="utf-8")
    assert "MoneyLine Subscribers" in html
    assert "Total income" in html


async def test_stk_callback_flat_stanbic_format(tmp_path) -> None:
    db_path = tmp_path / "subs.db"
    repo = SubscriptionRepository(db_path=db_path)
    repo.ensure_schema()
    service = SubscriptionService(repo=repo, stanbic=None)

    chat_id = "654321"
    service.begin_subscription(
        telegram_chat_id=chat_id,
        telegram_username="stanbic_user",
        plan=SubscriptionPlan.MONTHLY,
    )
    repo.set_pending_payment(
        telegram_chat_id=chat_id,
        phone="254712345678",
        plan=SubscriptionPlan.MONTHLY,
    )
    repo.create_transaction(
        checkout_request_id="ws_CO_flat",
        merchant_request_id="mr_flat",
        telegram_chat_id=chat_id,
        plan=SubscriptionPlan.MONTHLY,
        amount=1200,
        phone="254712345678",
    )

    payload = {
        "checkout_request_id": "ws_CO_flat",
        "result_code": 0,
        "result_desc": "The service request is processed successfully.",
        "mpesa_receipt_number": "STB123",
        "phone": "254712345678",
    }

    subscriber = await service.handle_stk_callback(payload)
    assert subscriber is not None
    assert subscriber.status == "active"


@pytest.mark.asyncio
async def test_auto_activate_when_stanbic_incomplete(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "subs.db"
    repo = SubscriptionRepository(db_path=db_path)
    repo.ensure_schema()
    service = SubscriptionService(repo=repo, stanbic=None)

    class AutoSettings:
        subscription_demo_mode = False
        stanbic_payment_mode = "stanbic"

        def auto_activate_subscriptions(self) -> bool:
            return True

        def stanbic_configured(self) -> bool:
            return False

        def uses_manual_stk(self) -> bool:
            return False

        def uses_stanbic_stk(self) -> bool:
            return False

    monkeypatch.setattr("moneyline.config.settings.get_settings", lambda: AutoSettings())
    monkeypatch.setattr("moneyline.subscriptions.service.get_settings", lambda: AutoSettings())

    chat_id = "777"
    service.begin_subscription(
        telegram_chat_id=chat_id,
        telegram_username="trial_user",
        plan=SubscriptionPlan.MONTHLY,
    )
    result = await service.initiate_stk_push(
        telegram_chat_id=chat_id,
        phone_raw="0712345678",
        plan=SubscriptionPlan.MONTHLY,
    )

    assert result.get("auto") is True
    sub = service.get_subscriber(chat_id)
    assert sub is not None
    assert sub.status == "active"


@pytest.mark.asyncio
async def test_demo_subscription_activates_without_charge(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "subs.db"
    repo = SubscriptionRepository(db_path=db_path)
    repo.ensure_schema()
    service = SubscriptionService(repo=repo, stanbic=None)

    class DemoSettings:
        subscription_demo_mode = True

        def auto_activate_subscriptions(self) -> bool:
            return True

        def stanbic_configured(self) -> bool:
            return False

    monkeypatch.setattr("moneyline.config.settings.get_settings", lambda: DemoSettings())
    monkeypatch.setattr("moneyline.subscriptions.service.get_settings", lambda: DemoSettings())

    chat_id = "555"
    service.begin_subscription(
        telegram_chat_id=chat_id,
        telegram_username="demo_user",
        plan=SubscriptionPlan.WEEKLY,
    )
    result = await service.initiate_stk_push(
        telegram_chat_id=chat_id,
        phone_raw="0712345678",
        plan=SubscriptionPlan.WEEKLY,
    )

    assert result.get("demo") is True
    sub = service.get_subscriber(chat_id)
    assert sub is not None
    assert sub.status == "active"
    assert sub.phone == "254712345678"
