# Technology Stack — World Cup 2026 Mode

**Project:** Alpha Terminal v1.1 — WC Soccer Mode
**Researched:** 2026-06-18
**Scope:** New additions only. Existing EPL/UCL stack (football-data.org client + Understat + ProphitBet XGBoost) is unchanged.

---

## Decision Summary

| Question | Answer | Confidence |
|----------|--------|------------|
| Does football-data.org free tier cover WC 2026? | YES — competition code `WC` | HIGH |
| Does The Odds API cover WC match lines on current plan? | NO — requires Business plan ($99/mo) | HIGH |
| Does The Odds API cover WC player props? | NO — soccer player props not offered | HIGH |
| Is statsbombpy correct for historical WC training data? | YES — 2018 + 2022, 64 matches each, free | HIGH |
| Is there a free WC fixture fallback if football-data.org fails? | YES — openfootball/worldcup.json (no key) | HIGH |
| Does Understat cover national team / WC player stats? | NO — domestic leagues only | HIGH |
| Is soccerdata/FBref a viable live WC player stats source? | AVOID — scraping is fragile, fragile | MEDIUM |

---

## 1. Fixture Ingestion — football-data.org (EXTEND existing client)

**Decision:** Extend `FootballDataClient` — add `"wc": "WC"` to `_COMP_MAP`. No new API key, no new library.

### Evidence

- football-data.org free tier explicitly covers 12 competitions including the FIFA World Cup and European Championship. The competition code is `WC`.
- Endpoint: `GET https://api.football-data.org/v4/competitions/WC/matches?dateFrom=YYYY-MM-DD&dateTo=YYYY-MM-DD`
- Same 10 req/min rate limit applies. Same `X-Auth-Token: {FOOTBALL_API_KEY}` header. Same response schema as EPL/UCL.
- The `stage` field differentiates group stage from knockouts (`GROUP_STAGE`, `ROUND_OF_16`, `QUARTER_FINALS`, `SEMI_FINALS`, `FINAL`).
- **What is NOT available on free tier:** draw odds / 3-way lines; per-player goal logs per match; squad data (requires Deep Data plan at €29/month).
- The `scorers` endpoint (`/competitions/WC/scorers`) returns top scorers for the tournament — goals only, no assists/shots, no per-match breakdown.

### What to add

```python
# alpha/data/ingestion/football_data_client.py
_COMP_MAP: dict[str, str] = {
    "epl": "PL",
    "ucl": "CL",
    "wc":  "WC",   # <-- new: FIFA World Cup 2026
}
```

The existing `fetch_today_games()` method will work without modification once `"wc"` is in the map. The `league` field on returned game dicts will be `"wc"`.

---

## 2. Match Lines (Win/Draw/Loss Odds) — The Odds API Situation

**Decision:** Do NOT expand The Odds API to World Cup. Remain on existing free plan (NBA-only). Use Poisson model for WC match lines with market-implied fallback.

### Evidence

- The Odds API sport key for WC is `soccer_fifa_world_cup`. The endpoint would be `GET /v4/sports/soccer_fifa_world_cup/odds/`.
- World Cup coverage requires the **Business plan at $99/month** (200,000 req/month). Current account is on the free tier (500 credits/month, NBA h2h only).
- Player props for soccer are **not listed** in any tier. The documented player prop markets on Business tier are: NBA, NHL, MLB, WNBA, AFL, NRL. Soccer appears only as anytime-goalscorer outright tournament markets (e.g. "who wins the Golden Boot"), not per-match in-game player prop lines.
- Upgrading solely for WC violates the "free APIs only" project constraint.

### Fallback path for WC match odds

The existing `SoccerModel._market_implied_predict()` defaults to `home_odds=-110, draw_odds=300, away_odds=250` when no odds are provided. This will be the WC default. The Poisson model built from StatsBomb historical national-team attack/defense rates will be the primary signal.

**Optional future enhancement (not default):** Add `WC_ODDS_ENABLED=false` env flag. When true, call `soccer_fifa_world_cup` h2h endpoint as a supplemental signal. One h2h call costs 1 credit. Gate it behind the flag so it does not consume budget by default.

---

## 3. Historical Training Data — statsbombpy (NEW library)

**Decision:** Add `statsbombpy>=1.19.0`. Use open data (no credentials needed). Pull WC 2018 and 2022 match events to compute national-team attack/defense rates and per-player career WC stats.

### Evidence — StatsBomb Open Data Coverage

StatsBomb open data (GitHub: `statsbomb/open-data`) includes:

| Tournament | competition_id | season_id | Matches | Data |
|------------|---------------|-----------|---------|------|
| FIFA World Cup 2018 | 43 | 3 | 64 | events + lineups |
| FIFA World Cup 2022 | 43 | 106 | 64 | events + lineups + 360 (partial) |

- Event data contains 80+ columns per event: `shot_statsbomb_xg`, `shot_outcome`, `pass_goal_assist`, `player`, `team`, `minute`, `period`, `location`, `position`, etc.
- No authentication needed for open data. The library detects missing credentials and falls back to open GitHub data automatically.
- Version 1.19.0 is current on PyPI as of June 2026.
- **Critical limitation:** StatsBomb open data is post-match historical only. It does NOT cover live WC 2026 matches. WC 2026 data will only appear after the tournament concludes (based on their release pattern for prior tournaments). Use 2018+2022 data as training priors and population baselines.

### Usage pattern

```python
from statsbombpy import sb

# List all available open competitions (no creds needed)
competitions = sb.competitions()
# Returns DataFrame; filter for competition_id == 43 to see WC seasons

# Fetch all 2022 WC matches
matches_2022 = sb.matches(competition_id=43, season_id=106)

# Fetch match events (one match at a time)
events = sb.events(match_id=<match_id>)
# Returns single DataFrame with 80+ columns

# Split by type for efficient access
events_split = sb.events(match_id=<match_id>, split=True)
shots  = events_split["shots"]   # has shot_statsbomb_xg column
passes = events_split["passes"]  # has pass_goal_assist column

# Aggregate across a whole competition (uses concurrent fetching internally)
all_events = sb.competition_events(
    country="World", division="FIFA World Cup", season="2022", gender="male"
)
```

### What to build with StatsBomb data

1. **National team attack/defense rates:** Goals scored + xG per match for each national team across 2018+2022. Used as Poisson lambda features for WC match model.
2. **Player career WC stats:** Per-player goals, shots, xG, assists per 90 minutes across all WC matches played. Used as prior means for WC prop model (if props are ever enabled).
3. **One-time offline build:** Run `scripts/build_wc_priors.py` to pull StatsBomb data and cache as `data/wc_priors.json`. The live scanner reads from this cache. No live StatsBomb calls during scanner runs.

### Install

```bash
./venv/Scripts/python.exe -m pip install "statsbombpy>=1.19.0"
```

StatsBombpy pulls pandas DataFrames from GitHub JSON files. It depends on `pandas`, `requests`, `ujson` — all already available or standard.

---

## 4. Live WC Player Stats — The Gap and How to Handle It

**Decision:** WC player props mode returns 0 legs (same as MLB/UCL today). Props are blocked by the absence of a free live per-player stat feed for international tournaments.

### Why Understat cannot be extended to WC

Understat covers exactly: EPL, La Liga, Bundesliga, Serie A, Ligue 1. National team football is architecturally out of scope — there is no Understat WC section. Confirmed by checking understat.com and community documentation.

### Why soccerdata/FBref is not recommended

FBref does cover the World Cup (it has a WC stats section: `fbref.com/en/comps/1/World-Cup-Stats`). The `soccerdata` library (v1.9.0, released April 2026) has `FBref` as a supported scraper class. However:
- FBref is known to block scrapers and rate-limit aggressively. Production use is fragile.
- No stable API — response format changes without notice.
- Terms of service are ambiguous for automated scraping.
- The existing `soccer_stats.py` already had issues with `soccerdata` on UCL (the MEMORY.md notes "BROKEN — needs Understat fix"), reinforcing that this is unreliable.

### Recommended path for WC props

Option A (current implementation): `wc_scanner.py --mode props` returns 0 legs with a logged warning: `"WC player props: no free live player stat source available"`. Same behavior as MLB.

Option B (future, if The Odds API Business plan is activated): The `soccer_fifa_world_cup` event-level endpoint offers `player_goal_scorer_anytime` market. Wire it in behind the `WC_ODDS_ENABLED` flag.

Option C (future, manual enrichment): Top-scorer tournament stats from `football-data.org /competitions/WC/scorers` can supplement StatsBomb career priors for current-form estimation.

---

## 5. WC Fixture Fallback — openfootball/worldcup.json

**Decision:** Use as zero-dependency backup when football-data.org is unavailable.

### Evidence

- GitHub: `openfootball/worldcup.json` — public domain, no API key.
- 2026 data: `https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json`
- Available files: `worldcup.json` (schedule + scores), `worldcup.groups.json` (group table), `worldcup.squads.json` (team rosters), `worldcup.stadiums.json`.
- Contains: match date, team1, team2, score (when played), round name.

```python
import requests
_WC_FALLBACK_URL = (
    "https://raw.githubusercontent.com/openfootball/worldcup.json"
    "/master/2026/worldcup.json"
)
data = requests.get(_WC_FALLBACK_URL, timeout=10).json()
# data["rounds"] -> list of rounds, each with "matches" list
```

**Limitations:** No odds. Community-maintained; live-score latency may be hours behind football-data.org. Use only as schedule source, not as results source for live betting.

No new library required. Uses `requests` already in stack.

---

## 6. New Python Packages Required

| Package | Version | Purpose | Status |
|---------|---------|---------|--------|
| `statsbombpy` | `>=1.19.0` | 2018 + 2022 WC historical event data for training priors | **NEW — add to pyproject.toml** |

Everything else is covered by existing dependencies:
- `football-data.org`: extended via existing `football_data_client.py` + `FOOTBALL_API_KEY`
- `requests`: already in stack — used for openfootball fallback
- `pandas`, `numpy`, `scipy`: already in stack — StatsBomb events are DataFrames; Poisson model uses `scipy.stats`
- `xgboost`, `joblib`: already in stack — WC match model follows same ProphitBet pattern as EPL/UCL
- `aiohttp`, `understat`: already installed but NOT used for WC

---

## 7. Integration Map

### Clients to extend (no new files needed)

| Existing file | Change |
|---------------|--------|
| `alpha/data/ingestion/football_data_client.py` | Add `"wc": "WC"` to `_COMP_MAP` — 1 line |
| `alpha/data/ingestion/odds_api.py` | No change. NBA-only guard stays. |
| `alpha/data/ingestion/soccer_stats.py` | No change. Understat EPL-only stays. |

### New files to create

| New file | Purpose |
|----------|---------|
| `alpha/data/ingestion/wc_stats.py` | StatsBombPy reader — loads `data/wc_priors.json`; returns national-team attack/defense rates and per-player career WC stats |
| `alpha/engines/sports/wc_model.py` | Inherits from `SoccerModel`; overrides `_build_game_features()` to use national-team WC priors instead of Understat rolling stats |
| `alpha/engines/sports/wc_sgp_builder.py` | Mirrors `soccer_sgp_builder.py` for WC legs |
| `scripts/build_wc_priors.py` | One-time: pulls StatsBomb 2018+2022 WC events, computes and saves `data/wc_priors.json` |
| `scripts/wc_scanner.py` | Entry point: `--mode props` / `--mode parlay` |

---

## 8. Environment Variables

| Variable | Status | Purpose |
|----------|--------|---------|
| `FOOTBALL_API_KEY` | Existing — already set | WC fixtures via football-data.org `WC` competition code |
| `ODDS_API_KEY` | Existing — NBA-only, no change | Not used for WC in default config |
| `WC_ODDS_ENABLED` | Optional new flag (default `false`) | Guard for future Odds API WC h2h expansion |

---

## 9. Alternatives Explicitly Rejected

| Alternative | Why Rejected |
|-------------|--------------|
| The Odds API Business plan ($99/mo) for WC match lines | Violates "free APIs only" project constraint |
| API-Football / API-Sports | Paid; free tier is 100 req/day (inadequate for daily scanner) |
| Sportmonks WC API | Paid; no meaningful free tier |
| SofaScore scraping | TOS violation risk; no stable Python library |
| soccerdata + FBref for live WC player stats | FBref blocks scrapers; fragile; already proven unreliable in this codebase for UCL |
| WorldCupAPI.com | Paid subscription for live data |
| FIFA official API | Not publicly documented or available to third-party developers |
| Expand Understat to WC | Architecturally impossible — Understat only covers top-5 domestic European leagues |

---

## Sources

- [football-data.org free tier coverage](https://www.football-data.org/coverage) — WC code `WC` confirmed, HIGH confidence
- [football-data.org v4 lookup tables](https://docs.football-data.org/general/v4/lookup_tables.html) — competition codes
- [The Odds API — FIFA World Cup odds page](https://the-odds-api.com/sports/fifa-world-cup-odds.html) — sport key `soccer_fifa_world_cup`, player props listed as anytime-goalscorer only
- [The Odds API — Sports APIs list](https://the-odds-api.com/sports-odds-data/sports-apis.html) — Business plan required for WC; soccer player props not listed
- [Odds API Pricing 2026 comparison](https://oddspapi.io/blog/odds-api-pricing-2026-comparison/) — tier structure confirmed
- [StatsBomb open-data GitHub](https://github.com/statsbomb/open-data) — WC 2018 (season_id=3) + 2022 (season_id=106) confirmed, 64 matches each
- [StatsBomb 2022 WC free data release post](https://blogarchive.statsbomb.com/news/statsbomb-release-free-2022-world-cup-data/)
- [statsbombpy PyPI](https://pypi.org/project/statsbombpy/) — version 1.19.0 current
- [statsbombpy GitHub + Context7 docs](https://github.com/statsbomb/statsbombpy) — API patterns confirmed via Context7 (`/statsbomb/statsbombpy`)
- [openfootball/worldcup.json GitHub](https://github.com/openfootball/worldcup.json) — 2026 fixtures confirmed in master branch
- [soccerdata PyPI](https://pypi.org/project/soccerdata/) — v1.9.0 confirmed, FBref World Cup coverage acknowledged but scraping fragility documented
