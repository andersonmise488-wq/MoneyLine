from __future__ import annotations

import pandas as pd

from moneyline.alerts.telegram import (
    bookmaker_label,
    kickoff_label,
    market_title,
    participants_label,
    sport_heading,
)
from moneyline.constants import DEFAULT_BANKROLL
from moneyline.markets.period import format_line, period_label
from moneyline.models.schemas import ArbitrageOpportunity


def premium_teaser_dataframe(opportunities: list[ArbitrageOpportunity]) -> pd.DataFrame:
    """Public preview of premium-band arbs — match details without bookmaker stakes."""
    rows = []
    for opp in opportunities:
        rows.append(
            {
                "Margin": f"{opp.margin_pct:.2f}%",
                "Match": participants_label(opp),
                "Sport": sport_heading(opp.sport),
                "Market": market_title(opp),
                "Kickoff": kickoff_label(opp),
                "Books": f"{len(opp.legs)} legs — subscribe for details",
            }
        )
    return pd.DataFrame(rows)


def public_arbs_dataframe(opportunities: list[ArbitrageOpportunity]) -> pd.DataFrame:
    rows = []
    for opp in opportunities:
        rows.append(
            {
                "Match": participants_label(opp),
                "Sport": sport_heading(opp.sport),
                "Kickoff": kickoff_label(opp),
                "Margin": f"{opp.margin_pct:.2f}%",
            }
        )
    return pd.DataFrame(rows)


def admin_arbs_dataframe(opportunities: list[ArbitrageOpportunity]) -> pd.DataFrame:
    rows = []
    for opp in opportunities:
        legs = " | ".join(
            f"{bookmaker_label(str(leg.get('bookmaker', '')))} "
            f"{leg.get('label', '')}@{float(leg.get('price', 0)):.2f} "
            f"stake KES {float(leg.get('stake', 0)):,.0f}"
            for leg in opp.legs
        )
        rows.append(
            {
                "Margin %": round(opp.margin_pct, 2),
                "Sport": opp.sport.value,
                "Match": participants_label(opp),
                "Market": market_title(opp),
                "Period": period_label(opp.period),
                "Line": format_line(opp.line),
                "Kickoff (EAT)": kickoff_label(opp),
                "Legs": legs,
                "Bankroll": f"KES {DEFAULT_BANKROLL:,.0f}",
            }
        )
    return pd.DataFrame(rows)
