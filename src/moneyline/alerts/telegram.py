"""Telegram bot alerts for arbitrage opportunities."""

from __future__ import annotations

import logging
from collections import defaultdict
from html import escape

import httpx

from moneyline.alerts.formatting import format_bet_pick
from moneyline.config.settings import get_admin_chat_ids, get_settings, get_telegram_chat_ids
from moneyline.constants import (
    ALERT_INDIVIDUAL_LIMIT,
    DEFAULT_BANKROLL,
    MARGIN_ALERT_BUCKETS,
    TELEGRAM_MESSAGE_MAX_LENGTH,
)
from moneyline.markets.period import format_line, period_label
from moneyline.models.schemas import ArbitrageOpportunity, Sport
from moneyline.timezone import format_kickoff_eat

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
SEPARATOR = "──────────────────────"

_BOOKMAKER_LABELS: dict[str, str] = {
    "betika": "Betika",
    "odibets": "Odibets",
    "sportpesa": "SportPesa",
    "mozzartbet": "MozzartBet",
    "betpawa": "BetPawa",
    "sportybet": "SportyBet",
    "bangbet": "BangBet",
    "pepeta": "Pepeta",
    "shabiki": "Shabiki",
    "palmsbet": "PalmsBet",
}

_SPORT_EMOJI: dict[Sport, str] = {
    Sport.SOCCER: "⚽",
    Sport.TENNIS: "🎾",
    Sport.BASKETBALL: "🏀",
    Sport.VOLLEYBALL: "🏐",
    Sport.HANDBALL: "🤾",
    Sport.BASEBALL: "⚾",
    Sport.CRICKET: "🏏",
    Sport.ICE_HOCKEY: "🏒",
}


class TelegramAlertError(RuntimeError):
    pass


def _api_url(method: str, token: str) -> str:
    return TELEGRAM_API.format(token=token, method=method)


def telegram_configured() -> bool:
    settings = get_settings()
    return bool(settings.telegram_bot_token.strip() and get_telegram_chat_ids())


def bookmaker_label(slug: str) -> str:
    key = slug.lower().replace(" ", "_")
    return _BOOKMAKER_LABELS.get(key, slug.replace("_", " ").title())


def sport_emoji(sport: Sport) -> str:
    return _SPORT_EMOJI.get(sport, "🎯")


def sport_heading(sport: Sport) -> str:
    label = sport.value.replace("_", " ").title()
    return f"{sport_emoji(sport)} {label}"


def format_currency(amount: float | None) -> str:
    if amount is None:
        return "-"
    return f"KES {amount:,.2f}"


def market_title(opportunity: ArbitrageOpportunity) -> str:
    base = opportunity.market_display.split(" | ", 1)[0].strip()
    return base or opportunity.market_key.replace("_", " ").title()


def league_label(opportunity: ArbitrageOpportunity) -> str:
    if opportunity.competition and opportunity.competition.strip():
        return opportunity.competition.strip()
    return "Unknown Event"


def participants_label(opportunity: ArbitrageOpportunity) -> str:
    return f"{opportunity.home_team} vs {opportunity.away_team}"


def kickoff_label(opportunity: ArbitrageOpportunity) -> str:
    kickoff_date, kickoff_time = format_kickoff_eat(opportunity.start_time)
    return f"{kickoff_date} · {kickoff_time}"


def margin_bucket_label(margin_pct: float) -> str:
    for low, high, label in MARGIN_ALERT_BUCKETS:
        if low <= margin_pct <= high:
            return label
    if margin_pct < MARGIN_ALERT_BUCKETS[0][0]:
        return f"<{MARGIN_ALERT_BUCKETS[0][0]:.1f}%"
    return MARGIN_ALERT_BUCKETS[-1][2]


def group_by_margin_bucket(
    opportunities: list[ArbitrageOpportunity],
) -> dict[str, list[ArbitrageOpportunity]]:
    grouped: dict[str, list[ArbitrageOpportunity]] = defaultdict(list)
    for opp in opportunities:
        grouped[margin_bucket_label(opp.margin_pct)].append(opp)
    return grouped


def _profit_summary(opportunity: ArbitrageOpportunity) -> tuple[float, float, float]:
    stakes = [float(leg["stake"]) for leg in opportunity.legs if leg.get("stake") is not None]
    returns = [float(leg["return"]) for leg in opportunity.legs if leg.get("return") is not None]
    total_stake = sum(stakes) if stakes else DEFAULT_BANKROLL
    guaranteed_return = min(returns) if returns else total_stake * (1 + opportunity.margin_pct / 100)
    profit = guaranteed_return - total_stake
    return total_stake, guaranteed_return, profit


def _market_specifier_lines(opportunity: ArbitrageOpportunity) -> list[str]:
    lines = [
        f"Market:       {market_title(opportunity)}",
        f"Period:       {period_label(opportunity.period)}",
    ]
    line_text = format_line(opportunity.line)
    if line_text != "-":
        lines.append(f"Line:         {line_text}")
    return lines


def _format_bookie_block_plain(opportunity: ArbitrageOpportunity, leg: dict) -> list[str]:
    bookmaker = bookmaker_label(str(leg["bookmaker"]))
    pick = format_bet_pick(opportunity, leg)
    lines = [
        bookmaker,
        f"  {pick}",
        f"  Stake {format_currency(leg.get('stake'))} · Return {format_currency(leg.get('return'))}",
    ]
    url = leg.get("place_bet_url")
    if url:
        lines.append(f"  Place Bet: {url}")
    return lines


def _format_bookie_block_html(opportunity: ArbitrageOpportunity, leg: dict) -> list[str]:
    bookmaker = bookmaker_label(str(leg["bookmaker"]))
    pick = format_bet_pick(opportunity, leg)
    lines = [
        f"<b>{escape(bookmaker)}</b>",
        escape(pick),
        f"Stake {format_currency(leg.get('stake'))} · Return {format_currency(leg.get('return'))}",
    ]
    url = leg.get("place_bet_url")
    if url:
        lines.append(f'<a href="{escape(str(url))}">Place Bet</a>')
    return lines


def _format_bookie_batch_line(opportunity: ArbitrageOpportunity, leg: dict) -> str:
    bookmaker = bookmaker_label(str(leg["bookmaker"]))
    pick = format_bet_pick(opportunity, leg)
    line = (
        f"{bookmaker} · {pick} · "
        f"Stake {format_currency(leg.get('stake'))} · Return {format_currency(leg.get('return'))}"
    )
    url = leg.get("place_bet_url")
    if url:
        line += f' · <a href="{escape(str(url))}">Place Bet</a>'
    return line


def format_arb_message(opportunity: ArbitrageOpportunity) -> str:
    heading = sport_heading(opportunity.sport)
    total_stake, guaranteed_return, profit = _profit_summary(opportunity)

    lines = [
        "🔥 ARB ALERT",
        SEPARATOR,
        heading,
        "",
        f"Event:        {league_label(opportunity)}",
        f"Participants: {participants_label(opportunity)}",
        f"Kickoff:      {kickoff_label(opportunity)}",
        "",
        *_market_specifier_lines(opportunity),
        f"Margin:       {opportunity.margin_pct:.2f}%",
        "",
        SEPARATOR,
    ]

    for leg in opportunity.legs:
        lines.extend(_format_bookie_block_plain(opportunity, leg))
        lines.append("")

    lines.extend(
        [
            SEPARATOR,
            f"Total stake:       {format_currency(total_stake)}",
            f"Guaranteed return: {format_currency(guaranteed_return)}",
            f"Net profit:        {format_currency(profit)} ({opportunity.margin_pct:.2f}%)",
        ]
    )
    return "\n".join(lines)


def format_arb_html(opportunity: ArbitrageOpportunity) -> str:
    heading = sport_heading(opportunity.sport)
    total_stake, guaranteed_return, profit = _profit_summary(opportunity)

    lines = [
        "<b>🔥 ARB ALERT</b>",
        SEPARATOR,
        f"<b>{escape(heading)}</b>",
        "",
        f"<b>Event:</b> {escape(league_label(opportunity))}",
        f"<b>Participants:</b> {escape(participants_label(opportunity))}",
        f"<b>Kickoff:</b> {escape(kickoff_label(opportunity))}",
        "",
    ]

    for spec_line in _market_specifier_lines(opportunity):
        key, _, value = spec_line.partition(":")
        lines.append(f"<b>{escape(key.strip())}:</b> {escape(value.strip())}")

    lines.extend(
        [
            f"<b>Margin:</b> {opportunity.margin_pct:.2f}%",
            "",
            SEPARATOR,
        ]
    )

    for leg in opportunity.legs:
        lines.extend(_format_bookie_block_html(opportunity, leg))
        lines.append("")

    lines.extend(
        [
            SEPARATOR,
            f"<b>Total stake:</b> {format_currency(total_stake)}",
            f"<b>Guaranteed return:</b> {format_currency(guaranteed_return)}",
            f"<b>Net profit:</b> {format_currency(profit)} ({opportunity.margin_pct:.2f}%)",
        ]
    )
    return "\n".join(lines)


def format_batch_summary_html(
    bucket_label: str,
    opportunities: list[ArbitrageOpportunity],
    *,
    part: int = 1,
    parts: int = 1,
) -> str:
    header = f"<b>🔥 ARB ALERT · Batch · Margin {escape(bucket_label)}</b>"
    if parts > 1:
        header += f" <i>(part {part}/{parts})</i>"
    header += f"\n<b>Count:</b> {len(opportunities)}"

    lines = [header, SEPARATOR]

    for index, opp in enumerate(opportunities, start=1):
        sport_label = sport_heading(opp.sport)
        market_bits = [market_title(opp), period_label(opp.period)]
        line_text = format_line(opp.line)
        if line_text != "-":
            market_bits.append(line_text)
        market_summary = " · ".join(market_bits)

        lines.extend(
            [
                f"<b>{index}. {escape(sport_label)}</b>",
                f"<b>Event:</b> {escape(league_label(opp))}",
                f"{escape(participants_label(opp))}",
                f"<b>Kickoff:</b> {escape(kickoff_label(opp))}",
                f"<b>Market:</b> {escape(market_summary)} · <b>Margin {opp.margin_pct:.2f}%</b>",
            ]
        )
        for leg in opp.legs:
            lines.append(_format_bookie_batch_line(opp, leg))
        lines.append("")

    return "\n".join(lines).rstrip()


def _chunk_opportunities(
    bucket_label: str,
    opportunities: list[ArbitrageOpportunity],
) -> list[list[ArbitrageOpportunity]]:
    chunks: list[list[ArbitrageOpportunity]] = []
    current: list[ArbitrageOpportunity] = []

    for opp in opportunities:
        trial = current + [opp]
        text = format_batch_summary_html(bucket_label, trial)
        if len(text) > TELEGRAM_MESSAGE_MAX_LENGTH and current:
            chunks.append(current)
            current = [opp]
        else:
            current = trial

    if current:
        chunks.append(current)
    return chunks


async def send_message(
    text: str,
    *,
    chat_id: str | None = None,
    chat_ids: list[str] | None = None,
    token: str | None = None,
    parse_mode: str = "HTML",
    reply_markup: dict | None = None,
) -> int:
    settings = get_settings()
    token = (token or settings.telegram_bot_token).strip()
    targets = chat_ids if chat_ids is not None else get_telegram_chat_ids(chat_id)

    if not token:
        raise TelegramAlertError("TELEGRAM_BOT_TOKEN is not set")
    if not targets:
        raise TelegramAlertError("TELEGRAM_CHAT_ID is not set")

    url = _api_url("sendMessage", token)
    sent = 0

    async with httpx.AsyncClient(timeout=20.0) as client:
        for target in targets:
            payload: dict = {"chat_id": target, "text": text, "parse_mode": parse_mode}
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            resp = await client.post(url, json=payload)
            data = resp.json()
            if resp.status_code != 200 or not data.get("ok"):
                description = data.get("description", resp.text)
                raise TelegramAlertError(
                    f"Telegram send failed for chat {target}: {description}"
                )
            logger.info("Telegram alert sent to chat %s", target)
            sent += 1

    return sent


async def answer_callback_query(
    callback_query_id: str,
    *,
    text: str | None = None,
    token: str | None = None,
) -> None:
    settings = get_settings()
    token = (token or settings.telegram_bot_token).strip()
    if not token:
        raise TelegramAlertError("TELEGRAM_BOT_TOKEN is not set")

    payload: dict = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text

    url = _api_url("answerCallbackQuery", token)
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(url, json=payload)
        data = resp.json()
        if resp.status_code != 200 or not data.get("ok"):
            description = data.get("description", resp.text)
            raise TelegramAlertError(f"Telegram callback answer failed: {description}")


def resolve_alert_targets(
    chat_id: str | None = None,
    *,
    include_subscribers: bool = True,
) -> list[str]:
    """Resolve Telegram chat IDs for arb alerts (subscribers + admin groups)."""
    if chat_id:
        return [chat_id.strip()]

    settings = get_settings()
    targets: list[str] = []

    if include_subscribers and settings.subscriber_alerts_enabled:
        from moneyline.subscriptions.service import SubscriptionService

        service = SubscriptionService()
        targets.extend(s.telegram_chat_id for s in service.list_active_subscribers())

    targets.extend(get_admin_chat_ids())

    if not targets:
        targets = get_telegram_chat_ids()

    seen: set[str] = set()
    unique: list[str] = []
    for target in targets:
        if target not in seen:
            seen.add(target)
            unique.append(target)
    return unique


async def send_arbitrage_alert(
    opportunity: ArbitrageOpportunity,
    *,
    chat_id: str | None = None,
    chat_ids: list[str] | None = None,
    token: str | None = None,
) -> int:
    targets = chat_ids if chat_ids is not None else resolve_alert_targets(chat_id)
    if not targets:
        logger.warning("No Telegram alert targets configured")
        return 0
    return await send_message(
        format_arb_html(opportunity),
        chat_ids=targets,
        token=token,
        parse_mode="HTML",
    )


async def send_arbitrage_alerts(
    opportunities: list[ArbitrageOpportunity],
    *,
    chat_id: str | None = None,
    include_subscribers: bool = True,
    token: str | None = None,
    deduplicate: bool = False,
    min_margin_pct: float | None = None,
) -> int:
    if not opportunities:
        return 0

    settings = get_settings()
    alert_floor = (
        settings.alert_min_margin_pct if min_margin_pct is None else min_margin_pct
    )
    eligible = [o for o in opportunities if o.margin_pct > alert_floor]
    if not eligible:
        if opportunities:
            logger.info(
                "All %s opportunities at or below alert min margin (>%.1f%%)",
                len(opportunities),
                alert_floor,
            )
        return 0

    to_send = eligible
    store = None
    if deduplicate:
        from moneyline.alerts.dedup import AlertDedupStore

        store = AlertDedupStore(cooldown_minutes=settings.alert_dedup_minutes)
        to_send = store.filter_new(eligible)
        if not to_send:
            logger.info("All %s opportunities suppressed by alert dedup", len(eligible))
            return 0

    targets = resolve_alert_targets(chat_id, include_subscribers=include_subscribers)
    if not targets:
        logger.warning("No Telegram alert targets configured")
        return 0

    ordered = sorted(to_send, key=lambda o: o.margin_pct, reverse=True)
    sent = 0

    try:
        if len(ordered) <= ALERT_INDIVIDUAL_LIMIT:
            for opp in ordered:
                try:
                    sent += await send_arbitrage_alert(
                        opp,
                        chat_ids=targets,
                        token=token,
                    )
                    if deduplicate:
                        store.mark_sent(opp)
                except TelegramAlertError as exc:
                    logger.error("Telegram alert failed: %s", exc)
            return sent

        grouped = group_by_margin_bucket(ordered)
        bucket_order = [label for _, _, label in MARGIN_ALERT_BUCKETS]
        bucket_order.extend(
            label for label in grouped if label not in bucket_order
        )

        for bucket_label in bucket_order:
            bucket_opps = grouped.get(bucket_label, [])
            if not bucket_opps:
                continue
            bucket_opps.sort(key=lambda o: o.margin_pct, reverse=True)
            chunks = _chunk_opportunities(bucket_label, bucket_opps)
            for part, chunk in enumerate(chunks, start=1):
                text = format_batch_summary_html(
                    bucket_label,
                    chunk,
                    part=part,
                    parts=len(chunks),
                )
                try:
                    sent += await send_message(
                        text,
                        chat_ids=targets,
                        token=token,
                        parse_mode="HTML",
                    )
                    if deduplicate and store:
                        for opp in chunk:
                            store.mark_sent(opp)
                except TelegramAlertError as exc:
                    logger.error("Telegram batch alert failed: %s", exc)
    except TelegramAlertError as exc:
        logger.error("Telegram alerts aborted: %s", exc)

    return sent


async def fetch_recent_chats(token: str | None = None) -> list[dict]:
    settings = get_settings()
    token = (token or settings.telegram_bot_token).strip()
    if not token:
        raise TelegramAlertError("TELEGRAM_BOT_TOKEN is not set")

    url = _api_url("getUpdates", token)
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url)
        data = resp.json()

    if resp.status_code != 200 or not data.get("ok"):
        description = data.get("description", resp.text)
        raise TelegramAlertError(f"Telegram getUpdates failed: {description}")

    chats: dict[str, dict] = {}
    for update in data.get("result", []):
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        chat_id_value = chat.get("id")
        if chat_id_value is None:
            continue
        key = str(chat_id_value)
        chats[key] = {
            "chat_id": key,
            "type": chat.get("type", ""),
            "title": chat.get("title") or chat.get("username") or chat.get("first_name", ""),
            "last_text": (message.get("text") or "")[:80],
        }
    return list(chats.values())
