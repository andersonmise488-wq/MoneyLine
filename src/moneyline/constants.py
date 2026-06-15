from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "db" / "moneyline.sqlite"
PARQUET_DIR = DATA_DIR / "parquet"

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Minimum fuzzy match score (0-100) to link events across bookmakers
EVENT_MATCH_THRESHOLD = 88
TEAM_MATCH_THRESHOLD = 85
# Max kickoff difference when matching the same fixture across bookmakers
EVENT_KICKOFF_MATCH_MINUTES = 30

# Arbitrage defaults — detect every positive-margin surebet (no floor at scan time)
DEFAULT_MIN_MARGIN_PCT = 0.0
# Public teaser band on the marketing site (subscribers see everything)
PUBLIC_TEASER_MAX_MARGIN_PCT = 3.0
# Cross-book arbs require fixture match confidence at or above this (see matching/confidence.py).
MIN_MATCH_CONFIDENCE_FOR_ARB = 0.90
DEFAULT_BANKROLL = 10_000.0

# Prematch collection window (72 hours ahead, plus short past grace)
EVENT_LOOKAHEAD_HOURS = 72
# Minimum total events a healthy full scan should collect across all books/sports
MIN_HEALTHY_EVENTS = 1000
EVENT_PAST_GRACE_MINUTES = 30
# Keep arbs on the board briefly when a scan misses them between cycles
ACTIVE_ARB_GRACE_MINUTES = 20
# Resend Telegram alert only when fingerprint changes within this window
ALERT_DEDUP_MINUTES = 60
# Reject arb legs when market odds are older than this (seconds). 0 = disabled.
ODDS_STALENESS_SECONDS = 0
# Hot sports rescanned more often (minutes)
HOT_SPORTS_SCAN_INTERVAL_MINUTES = 2
OTHER_SPORTS_SCAN_INTERVAL_MINUTES = 5
HOT_SPORTS = frozenset({"soccer", "tennis"})

# Book health — minimum prematch events per sport before a book is flagged weak
CORE_SPORTS = frozenset({"soccer", "tennis", "basketball"})
SPORT_MIN_EVENTS = 10
NICHE_SPORT_MIN_EVENTS = 3

# Display timezone for alerts and CLI (East Africa Time, UTC+3)
DISPLAY_TIMEZONE = "EAT"

# Telegram alerts — only send opportunities at or above this margin (scan/dashboard unaffected)
DEFAULT_ALERT_MIN_MARGIN_PCT = 5.0

# Telegram alert batching
ALERT_INDIVIDUAL_LIMIT = 100
TELEGRAM_MESSAGE_MAX_LENGTH = 4096

# Margin buckets for batched alerts (min inclusive, max inclusive, label)
MARGIN_ALERT_BUCKETS: list[tuple[float, float, str]] = [
    (0.01, 2.99, "0.1-3.0%"),
    (3.0, 5.0, "3.0-5.0%"),
    (5.1, 7.0, "5.1-7.0%"),
    (7.1, 10.0, "7.1-10.0%"),
    (10.1, 15.0, "10.1-15.0%"),
    (15.1, 20.0, "15.1-20.0%"),
    (20.1, float("inf"), "20.1%+"),
]
