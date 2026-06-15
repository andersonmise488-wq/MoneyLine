# MoneyLine — Kenyan Sports Arbitrage System



Cross-bookmaker odds collection, normalization, and arbitrage detection for Kenyan sportsbooks.



## Supported bookmakers (10)



| Bookmaker   | Status        | API base | Notes |

|-------------|---------------|----------|-------|

| Betika      | **Live**      | `api.betika.com` | Sportradar — full market normalization |

| Odibets     | **Live**      | `apis.odibets.com` | Sportradar — shares `parent_match_id` |

| Pepeta      | **Live**      | `api.pepeta.com` | Betika white-label |

| BangBet     | **Live**      | `bet-api.bangbet.com` | POST `/match/list`, `/match/odds` |

| BetPawa     | **Live**      | `betpawa.co.ke/api/sportsbook` | Header `X-Pawa-Brand: betpawa-kenya` |

| MozzartBet  | **Live**      | `mozzartbet.co.ke` | POST `/betOffer2`, `/getBettingOdds` |

| Shabiki     | **Live**      | `sports-apipro.logiqsport.com` | PlayLogiq `/api/Pregame/Coupon` |

| SportyBet   | **Live**      | `sportybet.com/api/ke` | `/configurableLiveOrPrematchEvents` |

| PalmsBet    | **Live**      | `sb2frontend-altenar2.biahosted.com` | Altenar GetEvents/GetEventDetails |

| SportPesa   | **Live**      | `ke.sportpesa.com` | Akamai bypass via `curl_cffi` |



Run `moneyline probe` to re-check endpoint health.



## Supported sports (9)



Soccer, Tennis, Basketball, Volleyball, Handball, Baseball, Cricket, Field Hockey, Ice Hockey.



Sport IDs are mapped per bookmaker in `config/bookmakers.yaml`. Betika/Pepeta IDs were verified against `/v1/uo/sports`.



## Supported markets



Only markets listed in `config/markets.yaml` are ingested; everything else is dropped. Name-based bookmakers also use pattern aliases in `config/market_aliases.yaml`.



| Sport | Markets |

|-------|---------|

| Soccer | 1X2, Asian Handicap, O/U Goals, BTTS, Corners Totals, Draw No Bet, Live Totals |

| Tennis | Match Winner, Set Betting, Game Handicap, Total Games, Correct Set Score, Live/Next Game |

| Basketball | Moneyline, Spread, Totals, Quarter/Half/Team Totals, Live Spread/Totals |

| Volleyball | Match Winner, Set Handicap, Total Points, Correct Set Score, Live Set Betting |

| Handball | Match Winner (1X2), Asian Handicap, Totals, Team Totals, Live Totals |

| Baseball | Moneyline, Run Line, Totals, First 5 Innings, Team Totals, Live Inning Totals |

| Cricket | Match Winner, O/U Runs, Session, Innings Totals, Top Batsman, Live Winner |

| Field Hockey | Match Winner, Asian Handicap, Totals, Team Totals, Live Totals |

| Ice Hockey | Moneyline, Puck Line, Totals, Period Betting, Team Totals, Live Totals |



List markets for a sport: `moneyline markets --sport soccer`



## Quick start



```powershell

cd c:\Users\Public\MoneyLine

python -m venv .venv

.venv\Scripts\activate

pip install -e ".[dev]"



# Probe all bookmaker endpoints

moneyline probe



# Collect odds (single sport or all sports)

moneyline collect --sport soccer

moneyline collect-all



# Coverage matrix (events + normalized markets per bookie/sport)

moneyline coverage

moneyline coverage --sport tennis --sport basketball



# Find arbitrage opportunities (all 9 sports scanned in parallel by default)

moneyline arb --telegram

# Limit to one sport

moneyline arb --sport soccer --min-margin 3



# Smoke-test all adapters across all sports

.venv\Scripts\python scripts\test_adapters.py

.venv\Scripts\python scripts\test_adapters.py tennis basketball

```



## Architecture



```

bookmakers/     → per-bookie HTTP adapters + endpoint registry

markets/        → canonical market keys + bookie-specific mapping

matching/       → fuzzy event alignment across bookies

storage/        → SQLite (hot) + Parquet (historical via DuckDB)

arb/            → margin calculation + stake sizing

pipeline/       → orchestration + coverage reporting

probe/          → endpoint discovery & health checks

```



## Data layout



```

data/

  db/moneyline.sqlite      # events, odds snapshots, arbs

  parquet/

    odds/                  # partitioned by date/bookmaker/sport

    events/

```



## Telegram alerts

Set credentials in `.env` (see `.env.example`):

```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

```powershell
moneyline telegram chats   # after messaging the bot
moneyline telegram test
moneyline arb --telegram
```

## Disclaimer



For personal research only. Respect bookmaker ToS and local gambling regulations.

