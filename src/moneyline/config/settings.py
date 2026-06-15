from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from moneyline.constants import PROJECT_ROOT


class Settings(BaseSettings):
    """Runtime settings loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_admin_chat_ids: str = ""

    mpesa_env: str = "production"
    mpesa_consumer_key: str = ""
    mpesa_consumer_secret: str = ""
    mpesa_shortcode: str = "7113597"
    mpesa_till_number: str = "5074619"
    mpesa_passkey: str = ""
    mpesa_callback_url: str = ""
    mpesa_transaction_type: str = "CustomerBuyGoodsOnline"
    # daraja = Lipa na M-Pesa Online API | manual = till STK + admin /paid (fallback)
    mpesa_payment_mode: str = "daraja"

    subscription_weekly_kes: int = 400
    subscription_monthly_kes: int = 1200
    subscriber_alerts_enabled: bool = True
    subscription_demo_mode: bool = False

    web_admin_password: str = ""
    web_public_max_margin_pct: float = 3.0
    web_scan_min_margin_pct: float = 0.0
    web_scan_max_events: int = 0  # 0 = all events in the 72h window
    web_scan_max_markets: int = 0  # 0 = fetch markets for all collected events
    web_scan_interval_minutes: int = 2
    web_scan_poll_seconds: int = 30
    scan_auto_alerts_enabled: bool = True
    alert_min_margin_pct: float = 5.0
    alert_dedup_minutes: int = 60
    # Collection: match fixtures before market fetch; cache markets between cycles
    match_first_markets: bool = True
    market_fetch_concurrency: int = 50
    raw_cache_ttl_seconds: int = 0  # 0 = refetch markets every scan cycle
    odds_staleness_seconds: int = 0  # 0 = no odds-age filter within a scan
    book_circuit_breaker_failures: int = 3
    # Optional bearer token required for admin WS "scan" command (production)
    web_admin_token: str = ""
    web_allowed_origins: str = ""
    telegram_bot_username: str = "THorseKe_bot"

    def telegram_bot_link(self) -> str:
        username = self.telegram_bot_username.strip().lstrip("@")
        return f"https://t.me/{username}" if username else ""

    def mpesa_configured(self) -> bool:
        return bool(
            self.mpesa_consumer_key.strip()
            and self.mpesa_consumer_secret.strip()
            and self.mpesa_passkey.strip()
            and self.mpesa_callback_url.strip()
            and "your-domain" not in self.mpesa_callback_url
        )

    def uses_daraja_stk(self) -> bool:
        return self.mpesa_payment_mode.strip().lower() == "daraja" and self.mpesa_configured()

    def uses_manual_stk(self) -> bool:
        return self.mpesa_payment_mode.strip().lower() == "manual"

    def auto_activate_subscriptions(self) -> bool:
        """Instant subscribe while Daraja go-live / passkey / callback are pending."""
        if self.subscription_demo_mode:
            return True
        if self.mpesa_payment_mode.strip().lower() == "daraja" and not self.mpesa_configured():
            return True
        return False

    def billing_mode(self) -> str:
        if self.auto_activate_subscriptions():
            return "auto_activate"
        if self.uses_daraja_stk():
            return "daraja_stk"
        if self.uses_manual_stk():
            return "manual_stk"
        return "unconfigured"

    def telegram_chat_ids(self) -> list[str]:
        """Parse one or more chat IDs (comma-separated) from TELEGRAM_CHAT_ID."""
        return [part.strip() for part in self.telegram_chat_id.split(",") if part.strip()]

    def admin_chat_ids(self) -> list[str]:
        raw = self.telegram_admin_chat_ids.strip() or self.telegram_chat_id
        return [part.strip() for part in raw.split(",") if part.strip()]

    def allowed_origins(self) -> list[str]:
        return [part.strip() for part in self.web_allowed_origins.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_telegram_chat_ids(chat_id: str | None = None) -> list[str]:
    if chat_id:
        return [chat_id.strip()]
    return get_settings().telegram_chat_ids()


def get_admin_chat_ids() -> list[str]:
    return get_settings().admin_chat_ids()
