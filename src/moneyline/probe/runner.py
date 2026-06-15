from __future__ import annotations

import asyncio
import time
from typing import Iterable

from rich.console import Console
from rich.table import Table

from moneyline.bookmakers.registry import ADAPTERS, get_adapter
from moneyline.config_loader import get_all_bookmakers
from moneyline.models.schemas import Bookmaker, ProbeResult, Sport

console = Console()


async def probe_bookmaker(bookmaker: Bookmaker) -> list[ProbeResult]:
    cfg = get_all_bookmakers()[bookmaker.value]
    adapter = get_adapter(bookmaker)
    results: list[ProbeResult] = []

    async with adapter:
        report = await adapter.health_check()

    for check in report.get("checks", []):
        results.append(
            ProbeResult(
                bookmaker=bookmaker,
                endpoint=check.get("endpoint", ""),
                url=check.get("url", ""),
                status_code=check.get("status_code"),
                ok=bool(check.get("ok")),
                latency_ms=check.get("latency_ms"),
                sample_bytes=check.get("sample_bytes"),
                error=check.get("error"),
                notes=cfg.get("notes"),
            )
        )
    return results


async def probe_all(bookmakers: Iterable[Bookmaker] | None = None) -> list[ProbeResult]:
    targets = list(bookmakers or Bookmaker)
    tasks = [probe_bookmaker(bm) for bm in targets]
    nested = await asyncio.gather(*tasks, return_exceptions=True)

    flat: list[ProbeResult] = []
    for bm, result in zip(targets, nested):
        if isinstance(result, Exception):
            flat.append(
                ProbeResult(
                    bookmaker=bm,
                    endpoint="*",
                    url="",
                    status_code=None,
                    ok=False,
                    latency_ms=None,
                    sample_bytes=None,
                    error=str(result),
                )
            )
        else:
            flat.extend(result)
    return flat


def print_probe_report(results: list[ProbeResult]) -> None:
    table = Table(title="MoneyLine Bookmaker Probe Report")
    table.add_column("Bookmaker", style="cyan")
    table.add_column("Endpoint")
    table.add_column("Status")
    table.add_column("Latency")
    table.add_column("OK")
    table.add_column("Notes")

    for r in results:
        status = str(r.status_code) if r.status_code else (r.error or "ERR")[:40]
        latency = f"{r.latency_ms:.0f}ms" if r.latency_ms else "-"
        ok_str = "[green]YES[/]" if r.ok else "[red]NO[/]"
        notes = (r.notes or "")[:50]
        table.add_row(r.bookmaker.value, r.endpoint, status, latency, ok_str, notes)

    console.print(table)

    live = {
        Bookmaker.BETIKA,
        Bookmaker.ODIBETS,
        Bookmaker.PEPETA,
        Bookmaker.BANGBET,
        Bookmaker.BETPAWA,
        Bookmaker.MOZZARTBET,
        Bookmaker.SHABIKI,
        Bookmaker.SPORTYBET,
        Bookmaker.PALMSBET,
        Bookmaker.SPORTPESA,
    }
    ok_bookies = {r.bookmaker for r in results if r.ok}
    console.print(f"\n[bold]Live adapters ready:[/] {', '.join(b.value for b in ok_bookies & live)}")
    pending = set(Bookmaker) - ok_bookies
    if pending:
        console.print(
            f"[yellow]Needs endpoint capture:[/] {', '.join(b.value for b in pending)}"
        )
