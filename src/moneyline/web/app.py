"""MoneyLine Streamlit app — public landing + admin console."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2]
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

import asyncio

import pandas as pd
import streamlit as st

from moneyline.alerts.telegram import send_arbitrage_alerts, telegram_configured
from moneyline.config.settings import get_settings
from moneyline.subscriptions.plans import plan_label
from moneyline.subscriptions.service import SubscriptionService
from moneyline.timezone import format_eat
from moneyline.web.background import get_background_scanner
from moneyline.web.cache import ScanCache, ScanSnapshot
from moneyline.web.formatters import admin_arbs_dataframe
from moneyline.web.filters import filter_all_arbs, filter_premium_arbs, filter_public_arbs, filter_realistic_arbs
from moneyline.web.styles import PUBLIC_CSS

st.set_page_config(
    page_title="MoneyLine",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.warning(
    "Legacy Streamlit console — production dashboards run at http://localhost:8080/admin "
    "(WebSocket live feed). Use Streamlit for one-off analytics only.",
    icon="ℹ️",
)


@st.cache_resource
def _start_background_scanner():
    scanner = get_background_scanner()
    scanner.start()
    return True


def _load_snapshot() -> ScanSnapshot:
    return ScanCache.load()



def render_public_page() -> None:
    st.markdown(PUBLIC_CSS, unsafe_allow_html=True)
    st.info("The live site runs at **http://localhost:8080** — WebSocket feed, no refresh needed.")
    st.link_button("Open MoneyLine", "http://localhost:8080", use_container_width=True, type="primary")
    st.caption("Admin console: http://localhost:8080/admin")
    st.markdown('<div class="staff-login">', unsafe_allow_html=True)
    with st.expander("Staff access (legacy Streamlit admin)", expanded=False):
        _render_staff_login()
    st.markdown("</div>", unsafe_allow_html=True)


def _render_staff_login() -> bool:
    settings = get_settings()
    if st.session_state.get("admin_authenticated"):
        return True

    if not settings.web_admin_password.strip():
        st.caption("Admin console not configured.")
        return False

    password = st.text_input("Password", type="password", key="staff_pw", label_visibility="collapsed")
    if st.button("Sign in", use_container_width=True):
        if password == settings.web_admin_password:
            st.session_state.admin_authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


def _render_profit_panel(stats) -> None:
    st.subheader("Profit collected")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total income", f"KES {stats.total_income_kes:,.0f}")
    c2.metric("This month", f"KES {stats.income_this_month_kes:,.0f}")
    c3.metric("Today", f"KES {stats.income_today_kes:,.0f}")
    c4.metric("Successful payments", stats.successful_payments)


def _render_arbs_panel(snapshot: ScanSnapshot, settings) -> None:
    st.subheader("Arbitrage opportunities")
    all_opps = snapshot.opportunities
    all_arbs = filter_all_arbs(all_opps)
    realistic_opps = filter_realistic_arbs(
        all_opps,
        min_margin_pct=settings.web_public_max_margin_pct,
    )
    public_opps = filter_public_arbs(
        all_opps,
        max_margin_pct=settings.web_public_max_margin_pct,
    )
    premium_opps = filter_premium_arbs(
        all_opps,
        min_margin_pct=settings.web_public_max_margin_pct + 0.01,
    )

    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("All arbs", len(all_arbs))
    s2.metric(f"Public (≤{settings.web_public_max_margin_pct:g}%)", len(public_opps))
    s3.metric("Premium (>3%)", len(premium_opps))
    s4.metric("Above public (≥3%)", len(realistic_opps))
    s5.metric("Scan", "Running…" if snapshot.scanning else "Idle")

    scanned_label = format_eat(snapshot.scanned_at) if snapshot.scanned_at else "Never"
    st.caption(
        f"Last scan: {scanned_label} EAT · "
        f"window: {snapshot.max_events or 'all'} events / "
        f"{snapshot.max_markets or 'all'} market fetches · "
        f"min margin: {snapshot.min_margin_pct:g}%"
    )
    if snapshot.error:
        st.error(f"Last scan error: {snapshot.error}")

    diag = snapshot.diagnostics or {}
    if diag:
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Events scanned", f"{diag.get('events_collected', 0):,}")
        d2.metric("Markets scanned", f"{diag.get('markets_collected', 0):,}")
        d3.metric("Matched fixtures", f"{diag.get('clusters_matched', 0):,}")
        best = diag.get("best_cross_book_margin_pct")
        d4.metric("Best cross-book margin", f"{best:.2f}%" if best is not None else "—")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("Run scan now", type="primary"):
            with st.spinner("Scanning all sports…"):
                get_background_scanner().force_scan()
            st.rerun()
    with col_b:
        if st.button("Send premium Telegram alerts", disabled=not premium_opps):
            with st.spinner("Sending…"):
                sent = asyncio.run(send_arbitrage_alerts(premium_opps, deduplicate=False))
            st.success(f"Sent {sent} Telegram message(s).")
    with col_c:
        st.link_button("Open live admin dashboard", "http://localhost:8080/admin", use_container_width=True)

    if not telegram_configured():
        st.warning("Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID for alerts.")

    st.markdown("**All detected arbs**")
    if all_arbs:
        st.dataframe(admin_arbs_dataframe(all_arbs), use_container_width=True, hide_index=True)
    elif snapshot.scanning:
        st.info("Full prematch scan running — this can take 15–30 minutes on first load.")
    else:
        st.info("No arbs in the latest scan.")

    with st.expander("Public teaser band (≤3%)"):
        if public_opps:
            st.dataframe(admin_arbs_dataframe(public_opps), use_container_width=True, hide_index=True)
        else:
            st.caption("Nothing in the public band right now.")

    with st.expander("Premium band (>3%)"):
        if premium_opps:
            st.dataframe(admin_arbs_dataframe(premium_opps), use_container_width=True, hide_index=True)
        else:
            st.caption("No premium-band arbs in the latest scan.")

    with st.expander("Above public band (≥3%)"):
        if realistic_opps:
            st.dataframe(admin_arbs_dataframe(realistic_opps), use_container_width=True, hide_index=True)
        else:
            st.caption("Nothing in the review band right now.")


def _render_subscribers_panel(service: SubscriptionService, stats) -> None:
    st.subheader("Subscribers")
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Active", stats.active_count)
    d2.metric("Expired", stats.expired_count)
    d3.metric("Pending", stats.pending_count)
    d4.metric("All time", stats.total_subscribers)

    subs = service.list_subscribers(limit=100)
    if subs:
        rows = [
            {
                "Chat ID": sub.telegram_chat_id,
                "Username": f"@{sub.telegram_username}" if sub.telegram_username else "—",
                "Plan": plan_label(sub.plan) if sub.plan else "—",
                "Status": sub.status,
                "Phone": sub.phone or "—",
                "Expires (EAT)": format_eat(sub.expires_at) if sub.expires_at else "—",
            }
            for sub in subs
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No subscribers yet.")

    if st.button("Regenerate dashboard HTML"):
        path = service.write_dashboard()
        st.success(f"Written to {path}")


def render_admin_page() -> None:
    settings = get_settings()
    service = SubscriptionService()
    stats = service.dashboard_data().stats
    snapshot = _load_snapshot()
    all_arbs = filter_all_arbs(snapshot.opportunities)

    st.markdown(PUBLIC_CSS, unsafe_allow_html=True)
    st.markdown('<span class="admin-badge">ADMIN</span>', unsafe_allow_html=True)
    st.title("MoneyLine Admin Console")

    tab_overview, tab_arbs, tab_subs = st.tabs(["Overview", "Arbs", "Subscribers"])

    with tab_overview:
        st.subheader("System overview")
        o1, o2, o3, o4 = st.columns(4)
        o1.metric("Active subscribers", stats.active_count)
        o2.metric("Arbs in cache", len(all_arbs))
        o3.metric("Profit collected", f"KES {stats.total_income_kes:,.0f}")
        o4.metric(
            "Best margin",
            f"{snapshot.diagnostics.get('best_cross_book_margin_pct', 0):.2f}%"
            if snapshot.diagnostics and snapshot.diagnostics.get("best_cross_book_margin_pct") is not None
            else "—",
        )
        _render_profit_panel(stats)
        st.divider()
        st.json(
            {
                "scan_interval_minutes": settings.web_scan_interval_minutes,
                "scan_min_margin_pct": settings.web_scan_min_margin_pct,
                "public_max_margin_pct": settings.web_public_max_margin_pct,
                "demo_mode": settings.subscription_demo_mode,
                "mpesa_configured": settings.mpesa_configured(),
                "telegram_bot": settings.telegram_bot_link(),
            }
        )

    with tab_arbs:
        _render_arbs_panel(snapshot, settings)

    with tab_subs:
        _render_profit_panel(stats)
        st.divider()
        _render_subscribers_panel(service, stats)


def main() -> None:
    if "admin_authenticated" not in st.session_state:
        st.session_state.admin_authenticated = False

    if st.session_state.admin_authenticated:
        if st.sidebar.button("Log out", use_container_width=True):
            st.session_state.admin_authenticated = False
            st.rerun()
        if st.sidebar.button("Public site", use_container_width=True):
            st.session_state.admin_authenticated = False
            st.rerun()
        render_admin_page()
        return

    render_public_page()


if __name__ == "__main__":
    main()
