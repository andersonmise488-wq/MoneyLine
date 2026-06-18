from __future__ import annotations

import logging
from datetime import datetime, timezone

from moneyline.config.settings import get_settings
from moneyline.payments.stanbic import StanbicClient, StanbicError, parse_stk_callback
from moneyline.storage.subscriptions import SubscriptionRepository
from moneyline.subscriptions.dashboard import write_dashboard_file
from moneyline.subscriptions.models import SubscriberRecord, SubscriptionPlan
from moneyline.subscriptions.plans import extend_expiry, normalize_phone, plan_amount, plan_label
from moneyline.subscriptions.stats import DashboardData, SubscriptionStats
from moneyline.timezone import format_eat

logger = logging.getLogger(__name__)


class SubscriptionService:
    def __init__(
        self,
        repo: SubscriptionRepository | None = None,
        stanbic: StanbicClient | None = None,
    ) -> None:
        self.repo = repo or SubscriptionRepository()
        self.stanbic = stanbic or StanbicClient()
        self.repo.ensure_schema()

    def get_subscriber(self, telegram_chat_id: str) -> SubscriberRecord | None:
        return self.repo.get_subscriber(telegram_chat_id)

    def list_active_subscribers(self) -> list[SubscriberRecord]:
        return self.repo.list_active_subscribers()

    def list_subscribers(self, limit: int = 50) -> list[SubscriberRecord]:
        return self.repo.list_subscribers(limit=limit)

    def expire_due_subscribers(self) -> list[str]:
        return self.repo.expire_due_subscribers()

    async def notify_expired_subscribers(self) -> int:
        from moneyline.bot.telegram_bot import notify_payment_success

        chat_ids = self.expire_due_subscribers()
        for chat_id in chat_ids:
            await notify_payment_success(
                chat_id,
                (
                    "<b>Subscription expired</b>\n"
                    "You will no longer receive MoneyLine arb alerts.\n"
                    "Use /subscribe weekly or /subscribe monthly to renew."
                ),
            )
        return len(chat_ids)

    def dashboard_data(self) -> DashboardData:
        raw = self.repo.subscription_stats()
        stats = SubscriptionStats(**raw)
        return DashboardData(
            stats=stats,
            active_subscribers=self.repo.list_active_subscribers(),
            recent_payments=self.repo.list_recent_payments(),
            recent_subscribers=self.repo.list_subscribers(limit=20),
        )

    def write_dashboard(self, output=None):
        return write_dashboard_file(self.dashboard_data(), output=output)

    def begin_subscription(
        self,
        *,
        telegram_chat_id: str,
        telegram_username: str | None,
        plan: SubscriptionPlan,
    ) -> SubscriberRecord:
        return self.repo.upsert_awaiting_phone(
            telegram_chat_id=telegram_chat_id,
            telegram_username=telegram_username,
            plan=plan,
        )

    async def initiate_stk_push(
        self,
        *,
        telegram_chat_id: str,
        phone_raw: str,
        plan: SubscriptionPlan,
    ) -> dict:
        phone = normalize_phone(phone_raw)
        amount = plan_amount(plan)
        settings = get_settings()

        if settings.auto_activate_subscriptions():
            return await self.activate_demo_subscription(
                telegram_chat_id=telegram_chat_id,
                phone=phone,
                plan=plan,
            )

        if settings.uses_manual_stk():
            return await self.initiate_manual_stk(
                telegram_chat_id=telegram_chat_id,
                phone=phone,
                plan=plan,
            )

        if not settings.uses_stanbic_stk():
            raise StanbicError(
                "Stanbic payments are not configured. Set STANBIC_PAYMENT_MODE=manual "
                "or complete Stanbic Connect setup."
            )

        self.repo.set_pending_payment(
            telegram_chat_id=telegram_chat_id,
            phone=phone,
            plan=plan,
        )

        reference = f"ML-{plan.value[:3].upper()}-{telegram_chat_id}"
        response = await self.stanbic.stk_push(
            phone=phone,
            amount=amount,
            account_reference=reference,
        )

        checkout_request_id = str(response["CheckoutRequestID"])
        merchant_request_id = str(response["MerchantRequestID"])
        self.repo.create_transaction(
            checkout_request_id=checkout_request_id,
            merchant_request_id=merchant_request_id,
            telegram_chat_id=telegram_chat_id,
            plan=plan,
            amount=amount,
            phone=phone,
        )
        return response

    async def initiate_manual_stk(
        self,
        *,
        telegram_chat_id: str,
        phone: str,
        plan: SubscriptionPlan,
    ) -> dict:
        """Queue manual payment confirmation — no Stanbic API call."""
        amount = plan_amount(plan)
        checkout_request_id = (
            f"MANUAL-{telegram_chat_id}-{int(datetime.now(timezone.utc).timestamp())}"
        )

        self.repo.set_pending_payment(
            telegram_chat_id=telegram_chat_id,
            phone=phone,
            plan=plan,
        )
        self.repo.create_transaction(
            checkout_request_id=checkout_request_id,
            merchant_request_id="MANUAL-STK",
            telegram_chat_id=telegram_chat_id,
            plan=plan,
            amount=amount,
            phone=phone,
        )
        logger.info("Manual STK queued for chat %s phone %s", telegram_chat_id, phone)
        return {
            "CheckoutRequestID": checkout_request_id,
            "manual": True,
            "phone": phone,
            "amount": amount,
            "plan": plan.value,
        }

    async def activate_manual_payment(
        self,
        *,
        telegram_chat_id: str,
        mpesa_receipt: str | None = None,
    ) -> SubscriberRecord:
        """Activate subscription after till STK push is confirmed by admin."""
        txn = self.repo.get_pending_transaction_for_chat(telegram_chat_id)
        if not txn:
            raise ValueError(f"No pending payment for chat {telegram_chat_id}")

        receipt = (mpesa_receipt or "MANUAL").strip()
        self.repo.complete_transaction(
            checkout_request_id=str(txn["checkout_request_id"]),
            result_code=0,
            result_desc="Manual till STK confirmed",
            mpesa_receipt=receipt,
            status="success",
        )

        plan = SubscriptionPlan(txn["plan"])
        phone = str(txn["phone"])
        existing = self.repo.get_subscriber(telegram_chat_id)
        expires_at = extend_expiry(existing.expires_at if existing else None, plan)
        subscriber = self.repo.activate_subscriber(
            telegram_chat_id=telegram_chat_id,
            plan=plan,
            phone=phone,
            expires_at=expires_at,
        )
        logger.info(
            "Manual payment activated for chat %s receipt %s",
            telegram_chat_id,
            receipt,
        )
        return subscriber

    async def activate_demo_subscription(
        self,
        *,
        telegram_chat_id: str,
        phone: str,
        plan: SubscriptionPlan,
    ) -> dict:
        """Simulate a successful payment while Stanbic go-live is pending."""
        amount = plan_amount(plan)
        checkout_request_id = f"DEMO-{telegram_chat_id}-{int(datetime.now(timezone.utc).timestamp())}"

        self.repo.set_pending_payment(
            telegram_chat_id=telegram_chat_id,
            phone=phone,
            plan=plan,
        )
        self.repo.create_transaction(
            checkout_request_id=checkout_request_id,
            merchant_request_id="DEMO",
            telegram_chat_id=telegram_chat_id,
            plan=plan,
            amount=amount,
            phone=phone,
        )
        self.repo.complete_transaction(
            checkout_request_id=checkout_request_id,
            result_code=0,
            result_desc="Demo payment (no charge)",
            mpesa_receipt="DEMO",
            status="success",
        )

        existing = self.repo.get_subscriber(telegram_chat_id)
        expires_at = extend_expiry(existing.expires_at if existing else None, plan)
        self.repo.activate_subscriber(
            telegram_chat_id=telegram_chat_id,
            plan=plan,
            phone=phone,
            expires_at=expires_at,
        )
        logger.info("Auto-activated subscription for chat %s (billing pending)", telegram_chat_id)
        return {"CheckoutRequestID": checkout_request_id, "demo": True, "auto": True}

    async def handle_stk_callback(self, payload: dict) -> SubscriberRecord | None:
        parsed = parse_stk_callback(payload)
        checkout_request_id = parsed["checkout_request_id"]
        result_code = int(parsed["result_code"])
        result_desc = str(parsed["result_desc"] or "")

        txn = self.repo.get_transaction_by_checkout(checkout_request_id)
        if not txn:
            logger.warning("Unknown payment checkout request: %s", checkout_request_id)
            return None

        mpesa_receipt = parsed.get("mpesa_receipt")
        phone = txn["phone"]
        if parsed.get("phone"):
            phone = normalize_phone(str(parsed["phone"]))

        status = "success" if result_code == 0 else "failed"
        self.repo.complete_transaction(
            checkout_request_id=checkout_request_id,
            result_code=result_code,
            result_desc=result_desc,
            mpesa_receipt=mpesa_receipt,
            status=status,
        )

        if result_code != 0:
            return None

        plan = SubscriptionPlan(txn["plan"])
        existing = self.repo.get_subscriber(txn["telegram_chat_id"])
        expires_at = extend_expiry(
            existing.expires_at if existing else None,
            plan,
        )
        return self.repo.activate_subscriber(
            telegram_chat_id=txn["telegram_chat_id"],
            plan=plan,
            phone=phone,
            expires_at=expires_at,
        )

    def cancel(self, telegram_chat_id: str) -> None:
        self.repo.cancel_subscriber(telegram_chat_id)

    async def terminate(
        self,
        telegram_chat_id: str,
        *,
        notify: bool = True,
    ) -> SubscriberRecord | None:
        """Admin revoke — disconnect subscriber from alerts immediately."""
        subscriber = self.repo.terminate_subscriber(telegram_chat_id)
        if subscriber is None:
            return None
        if notify:
            from moneyline.bot.telegram_bot import notify_payment_success

            await notify_payment_success(
                telegram_chat_id,
                (
                    "<b>Subscription disconnected</b>\n"
                    "Your MoneyLine alerts have been turned off.\n"
                    "Use /subscribe weekly or /subscribe monthly to rejoin."
                ),
            )
        return subscriber

    @staticmethod
    def subscriber_payload(subscriber: SubscriberRecord) -> dict:
        return {
            "id": subscriber.id,
            "telegram_chat_id": subscriber.telegram_chat_id,
            "telegram_username": subscriber.telegram_username,
            "phone": subscriber.phone,
            "plan": subscriber.plan.value if subscriber.plan else None,
            "status": subscriber.status,
            "expires_at": subscriber.expires_at.isoformat() if subscriber.expires_at else None,
            "created_at": subscriber.created_at.isoformat(),
            "updated_at": subscriber.updated_at.isoformat(),
        }

    def status_message(self, subscriber: SubscriberRecord | None) -> str:
        if subscriber is None:
            return (
                "You do not have a MoneyLine subscription yet.\n"
                "Use /subscribe weekly or /subscribe monthly to get arb alerts."
            )

        if subscriber.status == "expired":
            return (
                "Status: Expired\n"
                "Use /subscribe weekly or /subscribe monthly to renew."
            )

        if subscriber.status == "active" and subscriber.expires_at:
            if subscriber.expires_at > datetime.now(timezone.utc):
                expiry = format_eat(subscriber.expires_at)
                plan = plan_label(subscriber.plan) if subscriber.plan else "Unknown"
                return (
                    f"Status: Active\n"
                    f"Plan: {plan}\n"
                    f"Expires: {expiry}\n"
                    f"Phone: {subscriber.phone or '-'}"
                )

        if subscriber.status == "pending_payment":
            return "Payment pending. Complete the M-Pesa prompt on your phone."

        if subscriber.status == "awaiting_phone":
            return "Send your M-Pesa number (07XX...) to continue checkout."

        return (
            f"Status: {subscriber.status}\n"
            "Use /subscribe weekly or /subscribe monthly to renew."
        )
