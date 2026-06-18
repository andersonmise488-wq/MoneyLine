"""Telegram bot for MoneyLine subscriptions."""

from __future__ import annotations

import logging
import re

from moneyline.alerts.telegram import TelegramAlertError, send_message
from moneyline.config.settings import get_admin_chat_ids, get_settings
from moneyline.payments.stanbic import StanbicError
from moneyline.subscriptions.models import SubscriptionPlan
from moneyline.subscriptions.plans import display_phone, normalize_phone, plan_amount, plan_label
from moneyline.subscriptions.service import SubscriptionService
from moneyline.timezone import format_eat

logger = logging.getLogger(__name__)

PLAN_PATTERN = re.compile(r"^/subscribe(?:@\w+)?(?:\s+(weekly|monthly))?$", re.I)
PHONE_PATTERN = re.compile(r"^[\d+\s-]{9,15}$")
PAID_PATTERN = re.compile(
    r"^/(?:paid|activate)(?:@\w+)?\s+(\d+)(?:\s+(\S+))?$",
    re.I,
)


class TelegramBot:
    def __init__(self, service: SubscriptionService | None = None) -> None:
        self.service = service or SubscriptionService()
        self.settings = get_settings()
        self._offset = 0
        self._expire_check_counter = 0

    async def run_forever(self) -> None:
        from moneyline.alerts.telegram import _api_url

        token = self.settings.telegram_bot_token.strip()
        if not token:
            raise TelegramAlertError("TELEGRAM_BOT_TOKEN is not set")

        url = _api_url("getUpdates", token)
        logger.info("MoneyLine Telegram bot polling started")

        import asyncio

        import httpx

        backoff_seconds = 5.0
        async with httpx.AsyncClient(timeout=35.0) as client:
            while True:
                try:
                    resp = await client.get(
                        url,
                        params={"offset": self._offset, "timeout": 25},
                    )
                    data = resp.json()
                    backoff_seconds = 5.0
                except (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException) as exc:
                    logger.warning(
                        "Telegram polling interrupted (%s), retrying in %.0fs",
                        exc,
                        backoff_seconds,
                    )
                    await asyncio.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, 60.0)
                    continue

                if resp.status_code != 200 or not data.get("ok"):
                    logger.error("getUpdates failed: %s", data.get("description", resp.text))
                    await asyncio.sleep(backoff_seconds)
                    continue

                for update in data.get("result", []):
                    self._offset = max(self._offset, int(update["update_id"]) + 1)
                    await self._handle_update(update)

                self._expire_check_counter += 1
                if self._expire_check_counter >= 12:
                    self._expire_check_counter = 0
                    try:
                        expired = await self.service.notify_expired_subscribers()
                        if expired:
                            logger.info("Expired %s subscription(s)", expired)
                    except Exception as exc:
                        logger.warning("Expiry check failed: %s", exc)

    def _is_admin(self, chat_id: str) -> bool:
        return chat_id in get_admin_chat_ids()

    async def _handle_update(self, update: dict) -> None:
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None or not text:
            return

        chat_id_str = str(chat_id)
        username = chat.get("username")

        try:
            if PAID_PATTERN.match(text):
                if not self._is_admin(chat_id_str):
                    await self._reply(chat_id_str, "Admin only command.")
                    return
                await self._handle_paid(chat_id_str, text)
            elif text.startswith("/start"):
                await self._reply(chat_id_str, self._welcome())
            elif text.startswith("/help"):
                await self._reply(chat_id_str, self._help(chat_id_str))
            elif text.startswith("/status"):
                sub = self.service.get_subscriber(chat_id_str)
                await self._reply(chat_id_str, self.service.status_message(sub))
            elif text.startswith("/stop") or text.startswith("/cancel"):
                self.service.cancel(chat_id_str)
                await self._reply(
                    chat_id_str,
                    "Subscription cancelled. You will not receive paid alerts.",
                )
            elif PLAN_PATTERN.match(text):
                plan_name = PLAN_PATTERN.match(text).group(1) or "monthly"
                plan = SubscriptionPlan(plan_name.lower())
                self.service.begin_subscription(
                    telegram_chat_id=chat_id_str,
                    telegram_username=username,
                    plan=plan,
                )
                await self._reply(
                    chat_id_str,
                    self._subscribe_prompt(plan),
                )
            elif PHONE_PATTERN.match(text):
                await self._handle_phone(chat_id_str, text, username=username)
            else:
                await self._reply(chat_id_str, self._help(chat_id_str))
        except Exception as exc:
            logger.exception("Bot handler error: %s", exc)
            await self._reply(chat_id_str, f"Sorry, something went wrong: {exc}")

    async def _handle_paid(self, admin_chat_id: str, text: str) -> None:
        match = PAID_PATTERN.match(text)
        if not match:
            await self._reply(admin_chat_id, "Usage: /paid CHAT_ID M-PESA_RECEIPT")
            return

        customer_chat_id = match.group(1)
        receipt = match.group(2)

        try:
            subscriber = await self.service.activate_manual_payment(
                telegram_chat_id=customer_chat_id,
                mpesa_receipt=receipt,
            )
        except ValueError as exc:
            await self._reply(admin_chat_id, str(exc))
            return

        plan = plan_label(subscriber.plan) if subscriber.plan else "Subscription"
        expiry = format_eat(subscriber.expires_at) if subscriber.expires_at else "unknown"
        await self._reply(
            admin_chat_id,
            (
                f"<b>Activated</b> chat {customer_chat_id}\n"
                f"Plan: {plan}\n"
                f"Until: {expiry}\n"
                f"Receipt: {receipt or 'MANUAL'}"
            ),
        )
        await notify_payment_success(
            customer_chat_id,
            (
                f"<b>Payment confirmed</b>\n"
                f"Plan: {plan}\n"
                f"Active until: {expiry}\n"
                "You will now receive MoneyLine arb alerts."
            ),
        )

    async def _notify_admins_manual_stk(
        self,
        *,
        customer_chat_id: str,
        username: str | None,
        phone: str,
        plan: SubscriptionPlan,
    ) -> None:
        settings = get_settings()
        account = settings.stanbic_bill_account_ref.strip() or "your Stanbic account"
        local_phone = display_phone(phone)
        user_label = f"@{username}" if username else "no username"

        text = (
            "<b>📲 STK PUSH REQUIRED</b>\n"
            f"Push M-Pesa STK to Stanbic account <b>{account}</b>\n\n"
            f"<b>Phone:</b> {local_phone} ({phone})\n"
            f"<b>Amount:</b> KES {plan_amount(plan):,}\n"
            f"<b>Plan:</b> {plan_label(plan)}\n"
            f"<b>Customer:</b> {user_label} · chat <code>{customer_chat_id}</code>\n\n"
            "After the customer pays, confirm:\n"
            f"<code>/paid {customer_chat_id} RECEIPT_CODE</code>"
        )

        targets = get_admin_chat_ids()
        if not targets:
            logger.warning("No admin chat IDs for manual STK notification")
            return

        for target in targets:
            try:
                await send_message(text, chat_id=target, parse_mode="HTML")
            except TelegramAlertError as exc:
                logger.error("Manual STK admin alert failed for %s: %s", target, exc)

    async def _handle_phone(
        self,
        chat_id: str,
        text: str,
        *,
        username: str | None = None,
    ) -> None:
        sub = self.service.get_subscriber(chat_id)
        if sub is None or sub.status not in {"awaiting_phone", "pending_payment"}:
            await self._reply(chat_id, "Choose a plan first: /subscribe weekly or /subscribe monthly")
            return

        plan = sub.plan or SubscriptionPlan.MONTHLY
        try:
            phone = normalize_phone(text)
        except ValueError as exc:
            await self._reply(chat_id, str(exc))
            return

        try:
            result = await self.service.initiate_stk_push(
                telegram_chat_id=chat_id,
                phone_raw=phone,
                plan=plan,
            )
        except StanbicError as exc:
            await self._reply(chat_id, f"Payment setup failed: {exc}")
            return
        except ValueError as exc:
            await self._reply(chat_id, str(exc))
            return

        if result.get("demo") or result.get("auto"):
            sub = self.service.get_subscriber(chat_id)
            expiry = format_eat(sub.expires_at) if sub and sub.expires_at else "unknown"
            await self._reply(
                chat_id,
                (
                    f"<b>Subscription active</b>\n"
                    f"Plan: {plan_label(plan)}\n"
                    f"Active until: {expiry}\n"
                    "You will now receive MoneyLine arb alerts.\n"
                    "Use /status anytime to check your plan."
                ),
            )
            return

        if result.get("manual"):
            local_phone = display_phone(phone)
            await self._notify_admins_manual_stk(
                customer_chat_id=chat_id,
                username=username,
                phone=phone,
                plan=plan,
            )
            await self._reply(
                chat_id,
                (
                    f"<b>Payment request received</b>\n"
                    f"Plan: {plan_label(plan)} · KES {plan_amount(plan):,}\n\n"
                    f"You will receive an M-Pesa prompt on <b>{local_phone}</b> shortly.\n"
                    "Enter your PIN when it appears.\n\n"
                    "Use /status to check activation after paying."
                ),
            )
            return

        await self._reply(
            chat_id,
            (
                f"M-Pesa STK push sent to {display_phone(phone)} for "
                f"{plan_label(plan)} plan (KES {plan_amount(plan):,}).\n"
                "Enter your M-Pesa PIN on your phone to complete payment.\n"
                "Use /status to check activation."
            ),
        )

    async def _reply(self, chat_id: str, text: str) -> None:
        await send_message(text, chat_id=chat_id, parse_mode="HTML")

    def _welcome(self) -> str:
        settings = get_settings()
        if settings.auto_activate_subscriptions():
            pay_note = (
                "\n\nSend /subscribe, then your M-Pesa number — "
                "alerts start immediately."
            )
        elif settings.uses_stanbic_stk():
            pay_note = "\n\nPay via M-Pesa STK push (Stanbic) after sending your number."
        elif settings.uses_manual_stk():
            pay_note = (
                "\n\nAn admin will confirm your M-Pesa payment after you send your number."
            )
        else:
            pay_note = "\n\nContact admin to complete subscription setup."

        return (
            "<b>Welcome to MoneyLine</b>\n\n"
            "Cross-bookmaker arbitrage alerts for Kenyan sportsbooks.\n\n"
            f"Weekly: KES {settings.subscription_weekly_kes:,}\n"
            f"Monthly: KES {settings.subscription_monthly_kes:,}\n\n"
            "Commands:\n"
            "/subscribe weekly\n"
            "/subscribe monthly\n"
            "/status\n"
            "/stop"
            f"{pay_note}"
        )

    def _help(self, chat_id: str) -> str:
        lines = [
            "<b>MoneyLine commands</b>",
            "/subscribe weekly — weekly plan",
            "/subscribe monthly — monthly plan",
            "/status — check your subscription",
            "/stop — cancel alerts",
            "",
            "After /subscribe, send your M-Pesa number like 0712345678.",
        ]
        if self._is_admin(chat_id):
            lines.extend(
                [
                    "",
                    "<b>Admin</b>",
                    "/paid CHAT_ID RECEIPT — confirm manual payment",
                ]
            )
        return "\n".join(lines)

    def _subscribe_prompt(self, plan: SubscriptionPlan) -> str:
        return (
            f"You selected the <b>{plan_label(plan)}</b> plan "
            f"(KES {plan_amount(plan):,}).\n"
            "Reply with your M-Pesa number (07XXXXXXXX or 2547XXXXXXXX)."
        )


async def notify_payment_success(chat_id: str, message: str) -> None:
    await send_message(message, chat_id=chat_id, parse_mode="HTML")
