from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path

from moneyline.constants import DATA_DIR
from moneyline.subscriptions.plans import plan_label
from moneyline.subscriptions.stats import DashboardData
from moneyline.timezone import format_eat


def _fmt_kes(amount: float) -> str:
    return f"KES {amount:,.0f}"


def render_dashboard_html(data: DashboardData) -> str:
    stats = data.stats
    generated = format_eat(stats.generated_at)

    active_rows = ""
    for sub in data.active_subscribers:
        plan = plan_label(sub.plan) if sub.plan else "-"
        expiry = format_eat(sub.expires_at) if sub.expires_at else "-"
        active_rows += (
            "<tr>"
            f"<td>{escape(sub.telegram_chat_id)}</td>"
            f"<td>@{escape(sub.telegram_username or '-')}</td>"
            f"<td>{escape(sub.phone or '-')}</td>"
            f"<td>{escape(plan)}</td>"
            f"<td>{escape(expiry)}</td>"
            "</tr>"
        )
    if not active_rows:
        active_rows = '<tr><td colspan="5" class="muted">No active subscribers</td></tr>'

    payment_rows = ""
    for txn in data.recent_payments:
        status = txn.get("status", "")
        status_class = "ok" if status == "success" else "bad" if status == "failed" else "pending"
        completed = txn.get("completed_at") or txn.get("created_at") or ""
        if completed:
            try:
                completed = format_eat(datetime.fromisoformat(completed))
            except ValueError:
                pass
        payment_rows += (
            "<tr>"
            f"<td>{escape(completed)}</td>"
            f"<td>{escape(str(txn.get('phone', '-')))}</td>"
            f"<td>{escape(str(txn.get('plan', '-')))}</td>"
            f"<td>{_fmt_kes(float(txn.get('amount', 0)))}</td>"
            f"<td><span class='{status_class}'>{escape(status)}</span></td>"
            f"<td>{escape(str(txn.get('mpesa_receipt') or '-'))}</td>"
            "</tr>"
        )
    if not payment_rows:
        payment_rows = '<tr><td colspan="6" class="muted">No payments yet</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="60">
  <title>MoneyLine Subscribers Dashboard</title>
  <style>
    :root {{
      --bg: #0f1419;
      --card: #1a2332;
      --text: #e7ecf3;
      --muted: #8b98a8;
      --accent: #22c55e;
      --accent2: #3b82f6;
      --warn: #f59e0b;
      --bad: #ef4444;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 8px; font-size: 1.75rem; }}
    .sub {{ color: var(--muted); margin-bottom: 24px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
      margin-bottom: 28px;
    }}
    .card {{
      background: var(--card);
      border-radius: 12px;
      padding: 18px;
      border: 1px solid rgba(255,255,255,0.06);
    }}
    .card .label {{ color: var(--muted); font-size: 0.85rem; }}
    .card .value {{ font-size: 1.6rem; font-weight: 700; margin-top: 4px; }}
    .card.income .value {{ color: var(--accent); }}
    .card.active .value {{ color: var(--accent2); }}
    section {{ margin-bottom: 32px; }}
    section h2 {{ font-size: 1.1rem; margin: 0 0 12px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--card);
      border-radius: 12px;
      overflow: hidden;
    }}
    th, td {{
      padding: 10px 12px;
      text-align: left;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      font-size: 0.92rem;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    .muted {{ color: var(--muted); }}
    .ok {{ color: var(--accent); }}
    .bad {{ color: var(--bad); }}
    .pending {{ color: var(--warn); }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>MoneyLine Subscribers</h1>
    <p class="sub">Updated {escape(generated)} EAT · auto-refreshes every 60s</p>

    <div class="grid">
      <div class="card active">
        <div class="label">Active subscribers</div>
        <div class="value">{stats.active_count}</div>
      </div>
      <div class="card income">
        <div class="label">Total income</div>
        <div class="value">{_fmt_kes(stats.total_income_kes)}</div>
      </div>
      <div class="card">
        <div class="label">This month</div>
        <div class="value">{_fmt_kes(stats.income_this_month_kes)}</div>
      </div>
      <div class="card">
        <div class="label">Today</div>
        <div class="value">{_fmt_kes(stats.income_today_kes)}</div>
      </div>
      <div class="card">
        <div class="label">Weekly / Monthly active</div>
        <div class="value">{stats.weekly_active} / {stats.monthly_active}</div>
      </div>
      <div class="card">
        <div class="label">Expired · Pending</div>
        <div class="value">{stats.expired_count} · {stats.pending_count}</div>
      </div>
      <div class="card">
        <div class="label">Successful payments</div>
        <div class="value">{stats.successful_payments}</div>
      </div>
      <div class="card">
        <div class="label">All subscribers</div>
        <div class="value">{stats.total_subscribers}</div>
      </div>
    </div>

    <section>
      <h2>Active subscribers</h2>
      <table>
        <thead>
          <tr>
            <th>Chat ID</th>
            <th>Username</th>
            <th>Phone</th>
            <th>Plan</th>
            <th>Expires (EAT)</th>
          </tr>
        </thead>
        <tbody>{active_rows}</tbody>
      </table>
    </section>

    <section>
      <h2>Recent payments</h2>
      <table>
        <thead>
          <tr>
            <th>Date (EAT)</th>
            <th>Phone</th>
            <th>Plan</th>
            <th>Amount</th>
            <th>Status</th>
            <th>Receipt</th>
          </tr>
        </thead>
        <tbody>{payment_rows}</tbody>
      </table>
    </section>
  </div>
</body>
</html>
"""


def write_dashboard_file(data: DashboardData, output: Path | None = None) -> Path:
    path = output or (DATA_DIR / "dashboard.html")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_dashboard_html(data), encoding="utf-8")
    return path
