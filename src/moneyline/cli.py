from __future__ import annotations

import asyncio
import logging
from enum import Enum

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from moneyline.models.schemas import Bookmaker, Sport
from moneyline.markets.period import format_line, period_label
from moneyline.timezone import format_eat
from moneyline.pipeline.collector import ALL_SPORTS, CollectionPipeline, resolve_market_fetch_limit
from moneyline.pipeline.coverage import CoverageScanner
from moneyline.bookmakers.registry import LIVE_BOOKMAKERS
from moneyline.constants import EVENT_LOOKAHEAD_HOURS, DEFAULT_MIN_MARGIN_PCT
from moneyline.probe.runner import print_probe_report, probe_all
from moneyline.storage.database import Storage

app = typer.Typer(name="moneyline", help="Kenyan sportsbook arbitrage scanner")
console = Console()


class SportChoice(str, Enum):
    soccer = "soccer"
    tennis = "tennis"
    basketball = "basketball"
    volleyball = "volleyball"
    handball = "handball"
    baseball = "baseball"
    cricket = "cricket"
    ice_hockey = "ice_hockey"


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")
    if not verbose:
        for name in ("httpx", "httpcore", "hpack"):
            logging.getLogger(name).setLevel(logging.WARNING)


@app.command()
def probe(
    bookmaker: list[str] = typer.Option(None, "--bookmaker", "-b", help="Bookmaker key to probe"),
    deep: bool = typer.Option(False, "--deep", "-d", help="Deep probe with response classification"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Probe bookmaker API endpoints and report health."""
    _setup_logging(verbose)

    if deep:
        import sys
        from pathlib import Path

        scripts = Path(__file__).resolve().parents[2] / "scripts"
        sys.path.insert(0, str(scripts))
        from deep_probe import print_summary, run_deep_probe, save_report  # type: ignore

        from moneyline.constants import DATA_DIR

        results = asyncio.run(run_deep_probe())
        out = DATA_DIR / "probe" / "latest_probe.json"
        save_report(results, out)
        print_summary(results)
        console.print(f"\nReport saved: {out}")
        console.print(f"Markdown: {DATA_DIR / 'probe' / 'PROBE_REPORT.md'}")
        return

    targets = [Bookmaker(b) for b in bookmaker] if bookmaker else list(Bookmaker)
    results = asyncio.run(probe_all(targets))
    print_probe_report(results)


@app.command()
def collect(
    sport: SportChoice = typer.Option(SportChoice.soccer, "--sport", "-s"),
    max_events: int = typer.Option(
        0, "--max-events", help="0 = fetch all events in the 72h window"
    ),
    max_markets: int = typer.Option(
        0, "--max-markets", help="0 = fetch markets for every collected event"
    ),
    lookahead_hours: int = typer.Option(
        EVENT_LOOKAHEAD_HOURS, "--lookahead-hours", help="Include events starting within N hours"
    ),
    export_parquet: bool = typer.Option(True, "--parquet/--no-parquet"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Collect odds from live bookmaker adapters."""
    _setup_logging(verbose)
    pipeline = CollectionPipeline(
        max_events=max_events,
        max_market_fetches=resolve_market_fetch_limit(max_markets),
        lookahead_hours=lookahead_hours,
    )
    sport_enum = Sport(sport.value)

    console.print(
        f"[bold]Collecting[/] {sport.value} odds "
        f"(next {lookahead_hours}h) from {len(LIVE_BOOKMAKERS)} bookmakers..."
    )
    events, markets = asyncio.run(pipeline.collect_sport(sport_enum))

    console.print(f"Events: {len(events)} | Normalized markets: {len(markets)}")

    if export_parquet:
        storage = Storage()
        path = storage.export_odds_parquet()
        if path.exists():
            console.print(f"Parquet export: {path}")


def _print_arb_table(opportunities: list, *, title: str | None = None) -> None:
    table = Table(title=title or f"Arbitrage Opportunities ({len(opportunities)})")
    table.add_column("Sport")
    table.add_column("Margin %", style="green")
    table.add_column("Match")
    table.add_column("Market")
    table.add_column("Period")
    table.add_column("Line")
    table.add_column("Kickoff (EAT)")
    table.add_column("Legs")

    for opp in opportunities[:20]:
        legs = " | ".join(
            f"{leg['bookmaker']} {leg['label']}@{leg['price']:.2f} "
            f"(L{format_line(leg.get('line'))})"
            for leg in opp.legs
        )
        table.add_row(
            opp.sport.value,
            f"{opp.margin_pct:.2f}",
            escape(f"{opp.home_team} vs {opp.away_team}"),
            escape(opp.market_display),
            period_label(opp.period),
            format_line(opp.line),
            format_eat(opp.start_time),
            escape(legs),
        )
    console.print(table)


def _run_arb_scan(
    *,
    sports: list[Sport],
    min_margin: float,
    max_events: int,
    max_markets: int,
    lookahead_hours: int,
    telegram: bool,
    verbose: bool,
) -> None:
    _setup_logging(verbose)
    pipeline = CollectionPipeline(
        min_margin_pct=min_margin,
        max_events=max_events,
        max_market_fetches=resolve_market_fetch_limit(max_markets),
        lookahead_hours=lookahead_hours,
    )

    if len(sports) == 1:
        console.print(
            f"[bold]Scanning[/] {sports[0].value} for arbs (min {min_margin}%)..."
        )
        opportunities = asyncio.run(
            pipeline.run(sports[0], send_telegram=telegram)
        )
    else:
        console.print(
            f"[bold]Scanning[/] {len(sports)} sports in parallel "
            f"for arbs (min {min_margin}%)..."
        )
        opportunities = asyncio.run(
            pipeline.run_all_sports(sports=sports, send_telegram=telegram)
        )

    if not opportunities:
        console.print("[yellow]No arbitrage opportunities found.[/]")
        return

    title = (
        f"Arbitrage Opportunities ({len(opportunities)})"
        if len(sports) == 1
        else f"Arbitrage Opportunities — All Sports ({len(opportunities)})"
    )
    _print_arb_table(opportunities, title=title)


@app.command()
def arb(
    sport: list[SportChoice] = typer.Option(
        None, "--sport", "-s", help="Limit to sport(s); default scans all 9 in parallel"
    ),
    min_margin: float = typer.Option(
        DEFAULT_MIN_MARGIN_PCT, "--min-margin", help="Minimum arb margin %"
    ),
    max_events: int = typer.Option(
        0, "--max-events", help="0 = fetch all events in the 72h window"
    ),
    max_markets: int = typer.Option(
        0, "--max-markets", help="0 = fetch markets for every collected event"
    ),
    lookahead_hours: int = typer.Option(
        EVENT_LOOKAHEAD_HOURS, "--lookahead-hours", help="Include events starting within N hours"
    ),
    telegram: bool = typer.Option(False, "--telegram", help="Send alerts to Telegram"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Collect odds and scan for arbitrage across all sports in parallel."""
    sports = [Sport(s.value) for s in sport] if sport else ALL_SPORTS
    _run_arb_scan(
        sports=sports,
        min_margin=min_margin,
        max_events=max_events,
        max_markets=max_markets,
        lookahead_hours=lookahead_hours,
        telegram=telegram,
        verbose=verbose,
    )


@app.command("arb-all")
def arb_all(
    sport: list[SportChoice] = typer.Option(
        None, "--sport", "-s", help="Limit to sport(s); default is all 9 sports"
    ),
    min_margin: float = typer.Option(
        DEFAULT_MIN_MARGIN_PCT, "--min-margin", help="Minimum arb margin %"
    ),
    max_events: int = typer.Option(
        0, "--max-events", help="0 = fetch all events in the 72h window"
    ),
    max_markets: int = typer.Option(
        0, "--max-markets", help="0 = fetch markets for every collected event"
    ),
    lookahead_hours: int = typer.Option(
        EVENT_LOOKAHEAD_HOURS, "--lookahead-hours", help="Include events starting within N hours"
    ),
    telegram: bool = typer.Option(False, "--telegram", help="Send alerts to Telegram"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Alias for arb — scans all sports in parallel."""
    sports = [Sport(s.value) for s in sport] if sport else ALL_SPORTS
    _run_arb_scan(
        sports=sports,
        min_margin=min_margin,
        max_events=max_events,
        max_markets=max_markets,
        lookahead_hours=lookahead_hours,
        telegram=telegram,
        verbose=verbose,
    )


@app.command("collect-all")
def collect_all(
    max_events: int = typer.Option(
        0, "--max-events", help="0 = fetch all events in the 72h window"
    ),
    max_markets: int = typer.Option(
        0, "--max-markets", help="0 = fetch markets for every collected event"
    ),
    lookahead_hours: int = typer.Option(
        EVENT_LOOKAHEAD_HOURS, "--lookahead-hours", help="Include events starting within N hours"
    ),
    export_parquet: bool = typer.Option(True, "--parquet/--no-parquet"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Collect odds for all 9 sports across live bookmakers."""
    _setup_logging(verbose)
    pipeline = CollectionPipeline(
        max_events=max_events,
        max_market_fetches=resolve_market_fetch_limit(max_markets),
        lookahead_hours=lookahead_hours,
    )

    console.print(
        f"[bold]Collecting all sports[/] (next {lookahead_hours}h) "
        f"from {len(LIVE_BOOKMAKERS)} bookmakers..."
    )
    results = asyncio.run(pipeline.collect_all_sports())

    table = Table(title="Collection Summary")
    table.add_column("Sport")
    table.add_column("Events", justify="right")
    table.add_column("Markets", justify="right")

    total_events = 0
    total_markets = 0
    for sport in ALL_SPORTS:
        events, markets = results.get(sport, ([], []))
        total_events += len(events)
        total_markets += len(markets)
        table.add_row(sport.value, str(len(events)), str(len(markets)))
    table.add_row("[bold]Total[/]", f"[bold]{total_events}[/]", f"[bold]{total_markets}[/]")
    console.print(table)

    if export_parquet:
        storage = Storage()
        path = storage.export_odds_parquet()
        if path.exists():
            console.print(f"Parquet export: {path}")


@app.command()
def coverage(
    max_events: int = typer.Option(5, "--max-events"),
    max_markets: int = typer.Option(2, "--max-markets"),
    lookahead_hours: int = typer.Option(
        EVENT_LOOKAHEAD_HOURS, "--lookahead-hours", help="Include events starting within N hours"
    ),
    sport: list[SportChoice] = typer.Option(None, "--sport", "-s", help="Limit to sport(s)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Report event and market coverage per sport and bookmaker."""
    _setup_logging(verbose)
    sports = [Sport(s.value) for s in sport] if sport else ALL_SPORTS
    scanner = CoverageScanner(
        max_events=max_events,
        max_market_fetches=resolve_market_fetch_limit(max_markets),
        lookahead_hours=lookahead_hours,
    )

    console.print(
        f"[bold]Scanning coverage[/] for {len(sports)} sport(s) within {lookahead_hours}h..."
    )
    rows = asyncio.run(scanner.scan_all(sports=sports))

    table = Table(title="Coverage Matrix")
    table.add_column("Sport")
    table.add_column("Bookmaker")
    table.add_column("Events", justify="right")
    table.add_column("Markets", justify="right")
    table.add_column("Market Keys")
    table.add_column("Status")

    for row in sorted(rows, key=lambda r: (r.sport.value, r.bookmaker.value)):
        if row.skipped:
            status = f"[dim]{row.skip_reason}[/]"
            keys = "-"
            evs = mks = "-"
        elif row.error:
            status = f"[red]{row.error[:40]}[/]"
            keys = "-"
            evs = str(row.events)
            mks = str(row.markets)
        else:
            status = "[green]ok[/]" if row.events else "[yellow]no events[/]"
            keys = ", ".join(sorted(row.market_keys)) or "-"
            evs = str(row.events)
            mks = str(row.markets)
        table.add_row(row.sport.value, row.bookmaker.value, evs, mks, keys, status)
    console.print(table)


telegram_app = typer.Typer(help="Telegram alert setup and testing")
app.add_typer(telegram_app, name="telegram")


@telegram_app.command("test")
def telegram_test(
    message: str = typer.Option("MoneyLine bot connected.", "--message", "-m"),
) -> None:
    """Send a test message using TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."""
    from moneyline.alerts.telegram import TelegramAlertError, send_message, telegram_configured
    from moneyline.config.settings import get_telegram_chat_ids

    if not telegram_configured():
        console.print(
            "[yellow]Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env[/]\n"
            "Run [bold]moneyline telegram chats[/] after messaging your bot."
        )
        raise typer.Exit(code=1)

    targets = get_telegram_chat_ids()
    try:
        sent = asyncio.run(send_message(f"<b>MoneyLine</b>\n{message}"))
    except TelegramAlertError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]Telegram test sent to {sent} chat(s):[/] {', '.join(targets)}")


@telegram_app.command("chats")
def telegram_chats() -> None:
    """List chat IDs from recent messages to your bot (getUpdates)."""
    from moneyline.alerts.telegram import TelegramAlertError, fetch_recent_chats
    from moneyline.config.settings import get_settings

    settings = get_settings()
    if not settings.telegram_bot_token.strip():
        console.print("[yellow]Set TELEGRAM_BOT_TOKEN in .env first.[/]")
        raise typer.Exit(code=1)

    try:
        chats = asyncio.run(fetch_recent_chats())
    except TelegramAlertError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc

    if not chats:
        console.print(
            "[yellow]No chats found.[/] Open Telegram, message your bot, then run this again."
        )
        return

    table = Table(title="Telegram Chats")
    table.add_column("Chat ID", style="cyan")
    table.add_column("Type")
    table.add_column("Name")
    table.add_column("Last message")
    for chat in chats:
        table.add_row(
            chat["chat_id"],
            chat.get("type", ""),
            str(chat.get("title", "")),
            str(chat.get("last_text", "")),
        )
    console.print(table)
    console.print("\nAdd the chat ID to .env as [bold]TELEGRAM_CHAT_ID[/]")


subscribers_app = typer.Typer(help="Paid subscriber management")
app.add_typer(subscribers_app, name="subscribers")


@subscribers_app.command("list")
def subscribers_list(
    limit: int = typer.Option(50, "--limit"),
    active_only: bool = typer.Option(False, "--active"),
) -> None:
    """List subscribers and subscription status."""
    from moneyline.subscriptions.service import SubscriptionService
    from moneyline.subscriptions.plans import plan_label

    service = SubscriptionService()
    rows = service.list_active_subscribers() if active_only else service.list_subscribers(limit=limit)

    table = Table(title="MoneyLine Subscribers")
    table.add_column("Chat ID", style="cyan")
    table.add_column("Username")
    table.add_column("Plan")
    table.add_column("Status")
    table.add_column("Phone")
    table.add_column("Expires (EAT)")

    for sub in rows:
        plan = plan_label(sub.plan) if sub.plan else "-"
        expiry = format_eat(sub.expires_at) if sub.expires_at else "-"
        table.add_row(
            sub.telegram_chat_id,
            sub.telegram_username or "-",
            plan,
            sub.status,
            sub.phone or "-",
            expiry,
        )
    console.print(table)


@subscribers_app.command("dashboard")
def subscribers_dashboard(
    output: str = typer.Option("", "--output", "-o", help="HTML file path"),
    open_browser: bool = typer.Option(False, "--open", help="Open dashboard in browser"),
) -> None:
    """Generate subscriber dashboard HTML (active subs, income, payments)."""
    from pathlib import Path

    from moneyline.constants import DATA_DIR
    from moneyline.subscriptions.service import SubscriptionService

    service = SubscriptionService()
    path = service.write_dashboard(output=Path(output) if output else None)
    stats = service.dashboard_data().stats

    console.print(f"[green]Dashboard written:[/] {path}")
    console.print(
        f"Active: {stats.active_count} | "
        f"Total income: KES {stats.total_income_kes:,.0f} | "
        f"This month: KES {stats.income_this_month_kes:,.0f}"
    )
    console.print(f"Live dashboard: [cyan]http://localhost:8080/dashboard[/] (when running moneyline serve)")

    if open_browser:
        import webbrowser

        webbrowser.open(path.resolve().as_uri())


@subscribers_app.command("expire")
def subscribers_expire() -> None:
    """Mark expired subscriptions and disconnect alert access."""
    from moneyline.subscriptions.service import SubscriptionService

    service = SubscriptionService()
    expired = service.expire_due_subscribers()
    console.print(f"[yellow]Expired {len(expired)} subscription(s)[/]")
    for chat_id in expired:
        console.print(f"  {chat_id}")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8080, "--port"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the HTTP server for M-Pesa STK callbacks."""
    _setup_logging(verbose)
    import uvicorn

    console.print(f"[bold]Starting MoneyLine API[/] on http://{host}:{port}")
    console.print("Public live dashboard: [cyan]/[/]  (WS [cyan]/ws/public[/])")
    console.print("Admin live dashboard: [cyan]/admin[/]  (WS [cyan]/ws/scan[/])")
    console.print("M-Pesa callback: [cyan]/mpesa/callback[/]")
    console.print("Subscriber dashboard: [cyan]/dashboard[/]")
    console.print("Prematch scanner + Telegram alerts run automatically with the API.")
    console.print("Telegram subscription bot starts automatically with the API.")
    from moneyline.config.settings import get_settings

    billing = get_settings().billing_mode()
    if billing == "auto_activate":
        console.print(
            "[yellow]Billing: auto-activate[/] — subscribers get alerts instantly "
            "(Daraja STK switches on automatically once passkey + callback are set)."
        )
    elif billing == "daraja_stk":
        console.print("[green]Billing: Daraja STK[/] — automated M-Pesa prompts.")
    else:
        console.print(f"[yellow]Billing mode:[/] {billing}")
    uvicorn.run("moneyline.api.app:app", host=host, port=port, reload=False)


bot_app = typer.Typer(help="Telegram subscription bot")
app.add_typer(bot_app, name="bot")

mpesa_app = typer.Typer(help="M-Pesa Daraja STK")
app.add_typer(mpesa_app, name="mpesa")


@mpesa_app.command("probe")
def mpesa_probe() -> None:
    """Check Daraja OAuth, STK credentials, and list what's missing."""
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "probe_daraja.py"
    subprocess.run([sys.executable, str(script)], check=False)


@bot_app.command("info")
def bot_info() -> None:
    """Show bot username and share link for new subscribers."""
    import httpx

    from moneyline.alerts.telegram import TelegramAlertError, _api_url
    from moneyline.config.settings import get_settings

    settings = get_settings()
    token = settings.telegram_bot_token.strip()
    if not token:
        console.print("[yellow]Set TELEGRAM_BOT_TOKEN in .env first.[/]")
        raise typer.Exit(code=1)

    url = _api_url("getMe", token)
    try:
        resp = httpx.get(url, timeout=20.0)
        data = resp.json()
    except httpx.HTTPError as exc:
        console.print(f"[red]Could not reach Telegram: {exc}[/]")
        raise typer.Exit(code=1) from exc

    if resp.status_code != 200 or not data.get("ok"):
        raise TelegramAlertError(data.get("description", resp.text))

    bot = data["result"]
    username = bot.get("username", "")
    name = str(bot.get("first_name", "MoneyLine"))
    username = bot.get("username", "")
    link = f"https://t.me/{username}" if username else "(set a username via @BotFather)"

    console.print(f"[bold]{escape(name)}[/]" + (f" (@{username})" if username else ""))
    console.print(f"Share link: [cyan]{link}[/]")
    console.print("\nAnyone with this link can open the bot and subscribe.")
    if settings.subscription_demo_mode:
        console.print(
            "[yellow]Demo mode is on[/] — subscriptions activate instantly (no M-Pesa charge)."
        )
    elif settings.uses_daraja_stk():
        console.print("[green]Daraja STK mode[/] — automated M-Pesa prompts on subscribe.")
    elif settings.uses_manual_stk():
        console.print("[yellow]Manual STK mode[/] — admin pushes from till.")
    else:
        console.print(
            "[yellow]Daraja not fully configured[/] — run [bold]moneyline mpesa probe[/]"
        )
    console.print("\nStart the bot with: [bold]moneyline bot run[/]")


@bot_app.command("run")
def bot_run(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    """Poll Telegram for /subscribe commands and initiate M-Pesa STK push."""
    from moneyline.alerts.telegram import TelegramAlertError
    from moneyline.bot.telegram_bot import TelegramBot

    _setup_logging(verbose)
    bot = TelegramBot()
    try:
        asyncio.run(bot.run_forever())
    except TelegramAlertError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc


@app.command()
def web(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8501, "--port"),
) -> None:
    """Launch the Streamlit web app (public preview + admin console)."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    from moneyline.constants import PROJECT_ROOT

    app_path = Path(__file__).resolve().parent / "web" / "app.py"
    env = os.environ.copy()
    src_path = str(PROJECT_ROOT / "src")
    env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")

    console.print(f"[bold]Starting MoneyLine web[/] at http://localhost:{port}")
    console.print("Public: low-margin arb preview · Admin: password in sidebar")
    console.print("[dim]Click 'Load preview' in the app — first scan takes 1–3 min.[/]")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.address",
            host,
            "--server.port",
            str(port),
            "--browser.gatherUsageStats",
            "false",
        ],
        env=env,
        check=True,
    )


@app.command()
def markets(
    sport: SportChoice = typer.Option(SportChoice.soccer, "--sport", "-s"),
) -> None:
    """List canonical markets configured for a sport."""
    from moneyline.markets.registry import MarketRegistry

    registry = MarketRegistry()
    sport_enum = Sport(sport.value)
    table = Table(title=f"Markets — {sport.value}")
    table.add_column("Key")
    table.add_column("Display")
    table.add_column("Outcomes")
    table.add_column("Live Only")

    for key in sorted(registry.allowed_market_keys(sport_enum)):
        spec = registry.market_spec(sport_enum, key) or {}
        outcomes = ", ".join(str(x) for x in spec.get("outcomes", []))
        live = "yes" if spec.get("live_only") else ""
        table.add_row(key, spec.get("display", ""), outcomes, live)
    console.print(table)


@app.command()
def sports() -> None:
    """List Betika sport IDs (useful for mapping)."""
    from moneyline.bookmakers.betika import BetikaAdapter

    async def _run():
        async with BetikaAdapter() as adapter:
            return await adapter.fetch_sports()

    rows = asyncio.run(_run())
    table = Table(title="Betika Sports")
    table.add_column("ID")
    table.add_column("Name")
    for s in rows:
        table.add_row(str(s.get("sport_id")), str(s.get("sport_name")))
    console.print(table)


if __name__ == "__main__":
    app()
