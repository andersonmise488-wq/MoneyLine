"""Run one full prematch scan and print dashboard-ready results."""
from __future__ import annotations

from moneyline.web.background import run_scan_and_cache

if __name__ == "__main__":
    snap = run_scan_and_cache(min_margin_pct=0.0, max_events=0, max_markets=0)
    print("total", snap.total, "scanning", snap.scanning, "error", snap.error)
    print("events cap", snap.max_events, "markets cap", snap.max_markets)
    d = snap.diagnostics or {}
    print("events", d.get("events_collected"), "markets", d.get("markets_collected"))
    print("best", d.get("best_cross_book_margin_pct"), d.get("best_cross_book_label"))
    for o in snap.opportunities[:15]:
        print(f"  {o.margin_pct:.2f}% {o.home_team} vs {o.away_team} [{o.market_display}]")
