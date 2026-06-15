from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from moneyline.constants import DB_PATH, PARQUET_DIR
from moneyline.models.schemas import ArbitrageOpportunity, Event, MarketOdds


class Storage:
    """SQLite for hot data + Parquet archives via DuckDB."""

    def __init__(self, db_path: Path | None = None, parquet_dir: Path | None = None) -> None:
        self.db_path = db_path or DB_PATH
        self.parquet_dir = parquet_dir or PARQUET_DIR
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        (self.parquet_dir / "odds").mkdir(parents=True, exist_ok=True)
        (self.parquet_dir / "events").mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_key TEXT PRIMARY KEY,
                    bookmaker TEXT NOT NULL,
                    external_id TEXT,
                    parent_match_id TEXT,
                    sport TEXT NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    competition TEXT,
                    start_time TEXT NOT NULL,
                    is_live INTEGER DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS odds_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL,
                    bookmaker TEXT NOT NULL,
                    sport TEXT NOT NULL,
                    market_key TEXT NOT NULL,
                    market_display TEXT,
                    is_live INTEGER DEFAULT 0,
                    line REAL,
                    outcomes_json TEXT NOT NULL,
                    sub_type_id TEXT,
                    fetched_at TEXT NOT NULL,
                    FOREIGN KEY (event_key) REFERENCES events(event_key)
                );

                CREATE INDEX IF NOT EXISTS idx_odds_market
                    ON odds_snapshots(bookmaker, sport, market_key, fetched_at);

                CREATE TABLE IF NOT EXISTS arbitrage_opportunities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cluster_id TEXT NOT NULL,
                    sport TEXT NOT NULL,
                    market_key TEXT NOT NULL,
                    margin_pct REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    detected_at TEXT NOT NULL
                );
                """
            )

    def upsert_events(self, events: list[Event]) -> None:
        now = datetime.utcnow().isoformat()
        rows = [
            (
                e.event_key,
                e.bookmaker.value,
                e.external_id,
                e.parent_match_id,
                e.sport.value,
                e.home_team,
                e.away_team,
                e.competition,
                e.start_time.isoformat(),
                int(e.is_live),
                now,
            )
            for e in events
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO events (
                    event_key, bookmaker, external_id, parent_match_id,
                    sport, home_team, away_team, competition, start_time, is_live, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_key) DO UPDATE SET
                    home_team=excluded.home_team,
                    away_team=excluded.away_team,
                    start_time=excluded.start_time,
                    is_live=excluded.is_live,
                    updated_at=excluded.updated_at
                """,
                rows,
            )

    def insert_odds(self, markets: list[MarketOdds]) -> None:
        rows = [
            (
                m.event_key,
                m.bookmaker.value,
                m.sport.value,
                m.market_key,
                m.market_display,
                int(m.is_live),
                m.line,
                json.dumps([o.model_dump(mode="json") for o in m.outcomes]),
                m.sub_type_id,
                m.fetched_at.isoformat(),
            )
            for m in markets
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO odds_snapshots (
                    event_key, bookmaker, sport, market_key, market_display,
                    is_live, line, outcomes_json, sub_type_id, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def insert_arbitrage(self, opportunities: list[ArbitrageOpportunity]) -> None:
        rows = [
            (
                o.cluster_id,
                o.sport.value,
                o.market_key,
                o.margin_pct,
                o.model_dump_json(),
                o.detected_at.isoformat(),
            )
            for o in opportunities
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO arbitrage_opportunities (
                    cluster_id, sport, market_key, margin_pct, payload_json, detected_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def export_odds_parquet(self, date: str | None = None) -> Path:
        """Export odds snapshots to partitioned Parquet."""
        date = date or datetime.utcnow().strftime("%Y-%m-%d")
        out_dir = self.parquet_dir / "odds" / f"date={date}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "odds.parquet"

        con = duckdb.connect()
        con.execute(f"ATTACH '{self.db_path}' AS db (TYPE SQLITE)")
        df = con.execute(
            """
            SELECT * FROM db.odds_snapshots
            WHERE CAST(fetched_at AS DATE) = ?
            """,
            [date],
        ).df()

        if df.empty:
            # Export all if no date filter hits
            df = con.execute("SELECT * FROM db.odds_snapshots").df()

        if not df.empty:
            df.to_parquet(out_file, index=False)
        con.close()
        return out_file

    def query_latest_odds(self, sport: str, market_key: str) -> pd.DataFrame:
        con = duckdb.connect()
        con.execute(f"ATTACH '{self.db_path}' AS db (TYPE SQLITE)")
        df = con.execute(
            """
            WITH ranked AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY event_key, bookmaker, market_key, line
                        ORDER BY fetched_at DESC
                    ) AS rn
                FROM db.odds_snapshots
                WHERE sport = ? AND market_key = ?
            )
            SELECT * FROM ranked WHERE rn = 1
            """,
            [sport, market_key],
        ).df()
        con.close()
        return df

    def load_events_dataframe(self, sport: str | None = None) -> pd.DataFrame:
        with self._connect() as conn:
            if sport:
                cur = conn.execute("SELECT * FROM events WHERE sport = ?", (sport,))
            else:
                cur = conn.execute("SELECT * FROM events")
            rows = cur.fetchall()
        return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()
