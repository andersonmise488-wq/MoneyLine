# MoneyLine Production Architecture

Target architecture for commercial deployment, informed by OddsJam, BetBurger, BetsLayer/BetSlayer, and open-source surebet scanners.

## Industry comparison

| Capability | OddsJam | BetBurger | BetsLayer | MoneyLine today |
|------------|---------|-----------|-----------|-----------------|
| Odds refresh | Sub-second (1M+ odds/sec) | Up to 1,800 arbs/min via API | Real-time web/mobile | ~10 min batch scan |
| Entity matching | Proprietary (150+ books) | Pre-matched in API output | Bookmaker pages + filters | Sportradar ID + fuzzy |
| Market mapping | Full props/alts/live | 200+ market types | Filters by market | ~8 types/sport YAML |
| Normalization | Internal canonical IDs | `BookmakerEventDto` + `BetDto` | Calculator + rounding | `Event` + `MarketOdds` |
| Arb output | Margin, stakes, deep links | JSON API (`ArbApiResponse`) | Add-to-betslip URLs | Telegram + dashboard |
| Financial model | Commission-aware tools | Filter by ROI % | Exchange commission, rounding | Dutching only |
| Live | Yes (1s refresh) | Prematch + live API | Live included | Prematch only |
| Execution | Deep links | API for automation | Prefilled stakes on book pages | None |

## Target pipeline (production)

```
┌──────────────┐    ┌─────────────────┐    ┌──────────────────┐
│  Retriever   │───▶│  RawOffer       │───▶│  CanonicalOffer  │
│  (per book)  │    │  (book-native)  │    │  (entity+market) │
└──────────────┘    └─────────────────┘    └────────┬─────────┘
                                                     │
                    ┌────────────────────────────────▼─────────┐
                    │  EntityIndex: fixture_id → BookOffer[]     │
                    │  MarketIndex: (fixture, spec_id, line)     │
                    └────────────────────┬───────────────────────┘
                                         │
                    ┌────────────────────▼───────────────────────┐
                    │  ArbEngine: best odds per outcome, fees,   │
                    │  settlement rules, staleness, limits       │
                    └────────────────────┬───────────────────────┘
                                         │
                    ┌────────────────────▼───────────────────────┐
                    │  ArbOpportunity v2 → cache / WS / alerts   │
                    └────────────────────────────────────────────┘
```

## Layer 1: Entity resolution (events)

### What competitors do

1. **Primary ID** — Sportradar / Betradar / internal fixture UUID (OddsJam API, Betika/Odibets/Pepeta).
2. **Secondary ID** — League + kickoff bucket + canonical team IDs (BetBurger `BookmakerEventDto`).
3. **Fuzzy fallback** — Token normalization, stopwords, Jaccard + Levenshtein, competition constraint (surebet.js, Arbiter-Bot).
4. **Human review queue** — Low-confidence matches flagged, not arbed.

### MoneyLine target

```yaml
# config/team_aliases.yaml
soccer:
  "manchester united":
    canonical_id: team:mu
    aliases: [man utd, manchester utd, m united]
  "bayern munich":
    canonical_id: team:bayern
    aliases: [bayern munchen, fc bayern]
```

**Fixture key** (canonical):

```
fixture_id = sha256(sport | canonical_home | canonical_away | kickoff_utc_hour)
```

**Match confidence** (store on cluster):

| Source | Confidence |
|--------|------------|
| Shared Sportradar parent_match_id | 1.0 |
| Shared betradarId on non-SR book | 0.95 |
| Fuzzy + same competition + kickoff ≤15m | 0.85–0.92 |
| Fuzzy only | 0.70–0.84 (alert only, no auto-arb) |

**Changes from today:**

- Replace greedy fuzzy clustering with **union-find** on candidate pairs above threshold.
- Add **competition_id** normalization (`config/competition_aliases.yaml`).
- Persist `fixture_id` and `match_confidence` on clusters.
- Block arbs when `match_confidence < 0.90` unless Sportradar trio.

## Layer 2: Market specification (canonical markets)

### What competitors do

Markets are not matched by display name. They use a **MarketSpec**:

| Field | Purpose |
|-------|---------|
| `market_family` | e.g. `match_result`, `totals`, `handicap`, `btts` |
| `period` | `full_time`, `1st_half`, `1st_quarter`, … |
| `line` | 2.5, -1.5, null |
| `scope` | `match`, `home_team`, `away_team`, `player` |
| `settlement` | `regular_time`, `incl_ot`, `incl_ew`, `push_void` |
| `outcome_set` | `{home, draw, away}` or `{over, under}` |

BetBurger pre-computes this in API `BetDto`. OddsJam maps "same market" as identical event + bet type + line.

### MoneyLine target

Extend `markets.yaml` entries:

```yaml
btts:
  display: Both Teams To Score
  market_family: btts
  outcomes: [yes, no]
  settlement: regular_time
  betika_sub_type_ids: ["29"]
  period_from_name: true   # require explicit 1st/2nd half in name
```

**Grouping key v2:**

```python
(sport, fixture_id, market_family, period, scope, line, settlement, sub_type_id)
```

**Equivalence rules** (`config/market_equivalence.yaml`):

- Block: `btts` 1st half ↔ full time (even if names fuzzy-match).
- Block: integer totals (2.0 vs 2.5) cross-book.
- Block: combo markets (1X2 + O/U).
- Allow: Asian handicap -0.5 ↔ DNB (with settlement flag).

## Layer 3: Team & name normalization

### Pipeline (borrowed from Arbiter-Bot + surebet)

```
raw name
  → NFKD accent strip
  → lowercase
  → alias lookup (team_aliases.yaml)
  → strip tokens: fc, sc, united, city, cf, …
  → punctuation → space
  → collapse whitespace
  → optional: token sort for fuzzy
```

**Event title** (tennis/MMA): `"Djokovic, N."` → `"djokovic n"`.

**Market name**: resolve via `market_aliases.yaml` longest-match-first (not first-match).

## Layer 4: Arb logic

### Industry standard algorithm

For each `(fixture_id, market_spec, line)`:

1. Collect all **CanonicalOffer** rows from N bookmakers.
2. For each required outcome, pick **max decimal odds** on a **unique book**.
3. `implied_sum = Σ(1/odds_i)`.
4. `gross_margin = (1 - implied_sum) * 100`.
5. `net_margin = gross_margin - fees - tax_on_winnings`.
6. If `net_margin >= min_margin` and all legs **fresh** (< TTL), emit arb.
7. Compute stakes: Dutching (equal profit) + **book rounding** (BetsLayer).

### MoneyLine additions needed

| Rule | Status |
|------|--------|
| Min/max margin band | Done (3–12%) |
| Unique book per leg | Done |
| Line tolerance ±0.01 | Done |
| Whole-number O/U block | Done |
| Odds fetched_at TTL | **Missing** |
| Commission per book | **Missing** |
| Withholding tax (KE) | **Missing** |
| Match confidence gate | **Missing** |
| Palp detection (>15% margin) | Partial (12% cap) |
| Middle detection | **Missing** |
| Dedup by opportunity fingerprint | **Missing** |

### ArbOpportunity v2 schema

```python
class ArbLeg:
    bookmaker: str
    book_event_id: str
    book_market_id: str
    outcome_key: str          # canonical: "home", "over", "yes"
    display_label: str
    decimal_odds: float
    odds_fetched_at: datetime
    stake: float
    deep_link: str | None     # BetsLayer-style

class ArbOpportunityV2:
    opportunity_id: str       # stable hash for dedup
    fixture_id: str
    sport: Sport
    market_spec_id: str
    period: MarketPeriod
    line: float | None
    match_confidence: float
    gross_margin_pct: float
    net_margin_pct: float
    legs: list[ArbLeg]
    home_team: str
    away_team: str
    competition: str | None
    start_time: datetime
    detected_at: datetime
    expires_at: datetime        # min(leg TTL)
    settlement: str
```

## Layer 5: Storage & deployment

### Current (dev)

- SQLite single file
- JSON cache `arbs_latest.json`
- 10 min poll loop

### Production target

| Component | Technology |
|-----------|------------|
| Hot odds | Redis / TimescaleDB (leg-level TTL) |
| Fixtures | Postgres `fixtures`, `book_offers` |
| Arbs | Postgres + Redis pub/sub → WebSocket |
| Workers | Celery/RQ: one worker per bookmaker |
| Scan mode | Incremental: event list every 60s, markets every 30s for matched fixtures |
| API | FastAPI (existing) + auth + rate limits |
| Alerts | Telegram + optional WhatsApp (BetsLayer Exclusive) |

### DB migrations (v2)

```sql
-- fixtures (canonical)
CREATE TABLE fixtures (
  fixture_id TEXT PRIMARY KEY,
  sport TEXT NOT NULL,
  canonical_home TEXT NOT NULL,
  canonical_away TEXT NOT NULL,
  competition_id TEXT,
  start_time TIMESTAMPTZ NOT NULL
);

-- book-side event mapping
CREATE TABLE book_events (
  bookmaker TEXT NOT NULL,
  external_id TEXT NOT NULL,
  fixture_id TEXT REFERENCES fixtures(fixture_id),
  parent_match_id TEXT,
  raw_home TEXT,
  raw_away TEXT,
  match_confidence REAL,
  PRIMARY KEY (bookmaker, external_id)
);

-- odds with period + settlement
CREATE TABLE offers (
  id BIGSERIAL PRIMARY KEY,
  fixture_id TEXT NOT NULL,
  bookmaker TEXT NOT NULL,
  market_spec_id TEXT NOT NULL,
  period TEXT NOT NULL,
  line REAL,
  scope TEXT,
  settlement TEXT,
  outcomes JSONB NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_offers_lookup
  ON offers (fixture_id, market_spec_id, period, line, fetched_at DESC);

-- deduplicated arbs
CREATE TABLE arbs (
  opportunity_id TEXT PRIMARY KEY,
  payload JSONB NOT NULL,
  first_seen_at TIMESTAMPTZ,
  last_seen_at TIMESTAMPTZ,
  status TEXT DEFAULT 'active'
);
```

## Layer 6: Retriever pattern (surebet.js)

Each bookmaker implements:

```python
class BookRetriever(Protocol):
    async def fetch_fixtures(self, sport: Sport) -> list[RawFixture]: ...
    async def fetch_offers(self, raw_fixture_id: str) -> list[RawOffer]: ...
    def health(self) -> RetrieverHealth: ...
```

Adapters become thin **retrievers**; normalization moves to shared **Canonicalizer**.

## Kenya deployment checklist

### P0 — Trust (before charging subscribers)

- [ ] Fixture confidence scoring + block low-confidence arbs
- [ ] BTTS/half-period equivalence hardening (done partially)
- [ ] Odds staleness: reject legs older than 120s
- [ ] Arb deduplication (`opportunity_id`)
- [ ] Full scan on startup; display diagnostics when empty

### P1 — Product parity (BetsLayer tier)

- [ ] Scan interval ≤ 2 min prematch; parallel sports
- [ ] Deep links per bookmaker leg
- [ ] Net margin after 20% withholding tax option
- [ ] Admin: match review queue for fuzzy clusters
- [ ] Fix SportyBet retriever; Shabiki field hockey

### P2 — BetBurger API tier

- [ ] Public REST API: `/api/v1/arbs` (authenticated)
- [ ] WebSocket push on new/updated arbs
- [ ] Postgres migration from SQLite
- [ ] Per-book worker with circuit breakers

### P3 — OddsJam tier

- [ ] Live odds path (separate retriever mode)
- [ ] Sub-minute refresh on matched fixtures
- [ ] Player props + double chance markets
- [ ] Middle / EV+ modules

## Mapping: current code → target

| Current | Target module |
|---------|---------------|
| `bookmakers/*.py` | `retrievers/` + keep adapters |
| `matching/fuzzy.py` | `canonical/fixtures.py` (EntityIndex) |
| `markets/normalizer.py` | `canonical/markets.py` (MarketSpec) |
| `markets/grouping.py` | `canonical/grouping.py` (v2 key) |
| `arb/engine.py` | `arb/engine_v2.py` (fees, TTL, confidence) |
| `models/schemas.py` | `models/schemas.py` + `models/canonical.py` |
| `storage/database.py` | `storage/postgres.py` (migration) |

## References

- OddsJam: real-time multi-book scan, identical market+line matching, stake calculator
- BetBurger: pre-matched JSON API (`BookmakerEventDto`, `BetDto`, `ArbsDto`)
- BetsLayer: prematch+live, commission rounding, deep links, profit tracker
- surebet (danielcardeenas): retriever-agnostic, fuzzy events, pluggable arbers
- Arbiter-Bot: text normalization, Jaccard+Levenshtein, pre-filters
