from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from moneyline.constants import DB_PATH
from moneyline.subscriptions.models import SubscriberRecord, SubscriptionPlan


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _row_to_subscriber(row: sqlite3.Row) -> SubscriberRecord:
    plan = SubscriptionPlan(row["plan"]) if row["plan"] else None
    return SubscriberRecord(
        id=int(row["id"]),
        telegram_chat_id=str(row["telegram_chat_id"]),
        telegram_username=row["telegram_username"],
        phone=row["phone"],
        plan=plan,
        status=str(row["status"]),
        expires_at=_parse_dt(row["expires_at"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class SubscriptionRepository:
    def __init__(self, db_path=DB_PATH) -> None:
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS subscribers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_chat_id TEXT NOT NULL UNIQUE,
                    telegram_username TEXT,
                    phone TEXT,
                    plan TEXT,
                    status TEXT NOT NULL DEFAULT 'awaiting_phone',
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mpesa_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    checkout_request_id TEXT UNIQUE,
                    merchant_request_id TEXT,
                    telegram_chat_id TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    amount REAL NOT NULL,
                    phone TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    mpesa_receipt TEXT,
                    result_code INTEGER,
                    result_desc TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_subscribers_status
                    ON subscribers(status, expires_at);
                """
            )

    def upsert_awaiting_phone(
        self,
        *,
        telegram_chat_id: str,
        telegram_username: str | None,
        plan: SubscriptionPlan,
    ) -> SubscriberRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO subscribers (
                    telegram_chat_id, telegram_username, plan, status, created_at, updated_at
                ) VALUES (?, ?, ?, 'awaiting_phone', ?, ?)
                ON CONFLICT(telegram_chat_id) DO UPDATE SET
                    telegram_username=excluded.telegram_username,
                    plan=excluded.plan,
                    status='awaiting_phone',
                    updated_at=excluded.updated_at
                """,
                (telegram_chat_id, telegram_username, plan.value, now, now),
            )
            row = conn.execute(
                "SELECT * FROM subscribers WHERE telegram_chat_id = ?",
                (telegram_chat_id,),
            ).fetchone()
        return _row_to_subscriber(row)

    def set_pending_payment(
        self,
        *,
        telegram_chat_id: str,
        phone: str,
        plan: SubscriptionPlan,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE subscribers
                SET phone = ?, plan = ?, status = 'pending_payment', updated_at = ?
                WHERE telegram_chat_id = ?
                """,
                (phone, plan.value, now, telegram_chat_id),
            )

    def create_transaction(
        self,
        *,
        checkout_request_id: str,
        merchant_request_id: str,
        telegram_chat_id: str,
        plan: SubscriptionPlan,
        amount: int,
        phone: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mpesa_transactions (
                    checkout_request_id, merchant_request_id, telegram_chat_id,
                    plan, amount, phone, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    checkout_request_id,
                    merchant_request_id,
                    telegram_chat_id,
                    plan.value,
                    float(amount),
                    phone,
                    now,
                ),
            )

    def get_transaction_by_checkout(self, checkout_request_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mpesa_transactions WHERE checkout_request_id = ?",
                (checkout_request_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_pending_transaction_for_chat(self, telegram_chat_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM mpesa_transactions
                WHERE telegram_chat_id = ? AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (telegram_chat_id,),
            ).fetchone()
        return dict(row) if row else None

    def complete_transaction(
        self,
        *,
        checkout_request_id: str,
        result_code: int,
        result_desc: str,
        mpesa_receipt: str | None,
        status: str,
    ) -> dict | None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE mpesa_transactions
                SET status = ?, result_code = ?, result_desc = ?,
                    mpesa_receipt = ?, completed_at = ?
                WHERE checkout_request_id = ?
                """,
                (status, result_code, result_desc, mpesa_receipt, now, checkout_request_id),
            )
            row = conn.execute(
                "SELECT * FROM mpesa_transactions WHERE checkout_request_id = ?",
                (checkout_request_id,),
            ).fetchone()
        return dict(row) if row else None

    def activate_subscriber(
        self,
        *,
        telegram_chat_id: str,
        plan: SubscriptionPlan,
        phone: str,
        expires_at: datetime,
    ) -> SubscriberRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE subscribers
                SET phone = ?, plan = ?, status = 'active',
                    expires_at = ?, updated_at = ?
                WHERE telegram_chat_id = ?
                """,
                (phone, plan.value, expires_at.isoformat(), now, telegram_chat_id),
            )
            row = conn.execute(
                "SELECT * FROM subscribers WHERE telegram_chat_id = ?",
                (telegram_chat_id,),
            ).fetchone()
        return _row_to_subscriber(row)

    def cancel_subscriber(self, telegram_chat_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE subscribers
                SET status = 'cancelled', updated_at = ?
                WHERE telegram_chat_id = ?
                """,
                (now, telegram_chat_id),
            )

    def terminate_subscriber(self, telegram_chat_id: str) -> SubscriberRecord | None:
        """Revoke access immediately — cancelled status and expiry set to now."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE subscribers
                SET status = 'cancelled', expires_at = ?, updated_at = ?
                WHERE telegram_chat_id = ?
                """,
                (now_iso, now_iso, telegram_chat_id),
            )
            row = conn.execute(
                "SELECT * FROM subscribers WHERE telegram_chat_id = ?",
                (telegram_chat_id,),
            ).fetchone()
        return _row_to_subscriber(row) if row else None

    def get_subscriber(self, telegram_chat_id: str) -> SubscriberRecord | None:
        self.expire_due_subscribers()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM subscribers WHERE telegram_chat_id = ?",
                (telegram_chat_id,),
            ).fetchone()
        return _row_to_subscriber(row) if row else None

    def expire_due_subscribers(self) -> list[str]:
        """Mark active subscribers as expired once past expires_at."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT telegram_chat_id FROM subscribers
                WHERE status = 'active'
                  AND expires_at IS NOT NULL
                  AND expires_at <= ?
                """,
                (now,),
            ).fetchall()
            if rows:
                conn.execute(
                    """
                    UPDATE subscribers
                    SET status = 'expired', updated_at = ?
                    WHERE status = 'active'
                      AND expires_at IS NOT NULL
                      AND expires_at <= ?
                    """,
                    (now, now),
                )
        return [str(row["telegram_chat_id"]) for row in rows]

    def list_active_subscribers(self) -> list[SubscriberRecord]:
        self.expire_due_subscribers()
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM subscribers
                WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at > ?
                ORDER BY expires_at ASC
                """,
                (now,),
            ).fetchall()
        return [_row_to_subscriber(row) for row in rows]

    def subscription_stats(self) -> dict:
        self.expire_due_subscribers()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

        with self._connect() as conn:
            active_count = conn.execute(
                """
                SELECT COUNT(*) FROM subscribers
                WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at > ?
                """,
                (now_iso,),
            ).fetchone()[0]
            expired_count = conn.execute(
                "SELECT COUNT(*) FROM subscribers WHERE status = 'expired'"
            ).fetchone()[0]
            pending_count = conn.execute(
                """
                SELECT COUNT(*) FROM subscribers
                WHERE status IN ('awaiting_phone', 'pending_payment')
                """
            ).fetchone()[0]
            total_subscribers = conn.execute(
                "SELECT COUNT(*) FROM subscribers"
            ).fetchone()[0]
            weekly_active = conn.execute(
                """
                SELECT COUNT(*) FROM subscribers
                WHERE status = 'active' AND plan = 'weekly'
                  AND expires_at IS NOT NULL AND expires_at > ?
                """,
                (now_iso,),
            ).fetchone()[0]
            monthly_active = conn.execute(
                """
                SELECT COUNT(*) FROM subscribers
                WHERE status = 'active' AND plan = 'monthly'
                  AND expires_at IS NOT NULL AND expires_at > ?
                """,
                (now_iso,),
            ).fetchone()[0]
            total_income = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM mpesa_transactions WHERE status = 'success'"
            ).fetchone()[0]
            income_today = conn.execute(
                """
                SELECT COALESCE(SUM(amount), 0) FROM mpesa_transactions
                WHERE status = 'success' AND completed_at >= ?
                """,
                (day_start,),
            ).fetchone()[0]
            income_month = conn.execute(
                """
                SELECT COALESCE(SUM(amount), 0) FROM mpesa_transactions
                WHERE status = 'success' AND completed_at >= ?
                """,
                (month_start,),
            ).fetchone()[0]
            successful_payments = conn.execute(
                "SELECT COUNT(*) FROM mpesa_transactions WHERE status = 'success'"
            ).fetchone()[0]

        return {
            "active_count": int(active_count),
            "expired_count": int(expired_count),
            "pending_count": int(pending_count),
            "total_subscribers": int(total_subscribers),
            "total_income_kes": float(total_income),
            "income_today_kes": float(income_today),
            "income_this_month_kes": float(income_month),
            "weekly_active": int(weekly_active),
            "monthly_active": int(monthly_active),
            "successful_payments": int(successful_payments),
            "generated_at": now,
        }

    def list_recent_payments(self, limit: int = 25) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM mpesa_transactions
                ORDER BY COALESCE(completed_at, created_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_subscribers(self, limit: int = 50) -> list[SubscriberRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM subscribers ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_subscriber(row) for row in rows]
