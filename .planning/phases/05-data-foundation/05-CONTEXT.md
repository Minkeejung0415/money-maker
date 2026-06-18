# Phase 5: Data Foundation - Context

**Gathered:** 2026-06-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 5 delivers the 3 data sources that WC match model and SGP builder need: live WC 2026 fixtures from football-data.org, national team Elo ratings from Kaggle CSV, and StatsBomb 2018+2022 historical event data. All 3 are isolated in their own cache namespace (`data/.wc_cache/`) and must not touch the EPL/UCL pipeline.

</domain>

<decisions>
## Implementation Decisions

### WC Fixture Method Design
- New `fetch_wc_games(date_from, date_to)` method on `FootballDataClient` — does NOT modify `fetch_today_games()`, EPL/UCL unchanged
- Add `"wc": "WC"` to `_COMP_MAP` (1-line fix)
- Stage metadata extracted from `match.get("stage")` in the football-data.org response body; embedded in each game dict
- Game dict extends existing shape with two new fields: `"stage"` (e.g., `"GROUP_STAGE"`, `"LAST_16"`) and `"group"` (e.g., `"Group A"`)
- Add 1-retry + 60s backoff for 429 responses to `FootballDataClient` before extending with WC method

### Elo Data Source
- Source: Kaggle CSV (saifalnimri/international-football-elo-ratings, ratings through 2025) — reliable, no web scraping
- Loading: download once to `data/wc_elo.csv` on first run; cache derived ratings to `data/wc_priors.json`; never commit raw data to git
- Output format in `wc_priors.json`: raw Elo rating per team — Phase 6 computes win/draw/loss probabilities with the correct logistic formula
- Missing team fallback: 1500 (FIFA world average) — all 48 WC 2026 teams should be in the dataset but safer to have a fallback

### StatsBomb Extraction Scope
- Data level: team-level only — `{avg_goals, avg_xG, avg_shots, defense_score}` per team — player props are deferred to v1.2
- Competitions: both 2018 (competition_id=43, season_id=3) + 2022 (competition_id=43, season_id=106) = 128 games total
- Cache strategy: pickle to `data/.wc_cache/wc_stats.pkl` once per session, no TTL — historical data won't change mid-tournament
- Output format: `dict[str, dict]` keyed by team name → `{"avg_goals": float, "avg_xG": float, "avg_shots": float, "defense_score": float}` — exactly what Phase 6 Elo-logistic needs as a strength modifier

### Claude's Discretion
- Specific Kaggle dataset URL / download mechanism (requests or kaggle CLI)
- Exact defense_score formula (goals_against or xG_against from StatsBomb events)
- Whether to use `statsbombpy.get_matches()` API or direct GitHub JSON URLs for the open data

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `alpha/data/ingestion/football_data_client.py` — `FootballDataClient` class with `_BASE_URL`, `_COMP_MAP`, and `fetch_today_games()`. Add `fetch_wc_games()` and 429 retry here.
- `alpha/data/ingestion/soccer_stats.py` — cache pattern using `pickle.load/dump` with date-keyed files in `data/.soccer_cache/`. Mirror this pattern in `wc_stats.py` using `data/.wc_cache/`.
- `alpha/config/settings.py` — `football_api_key: str = ""` already exists; no new env var needed for WC fixtures

### Established Patterns
- Cache files: `Path("data/.{sport}_cache") / f"{key}_{date.today()}.pkl"` — WC uses no-TTL pickle instead
- HTTP calls: `requests.get(..., headers={"X-Auth-Token": self.api_key}, timeout=10)` then `.raise_for_status()`
- Logging: `logger.info("Fetched %d WC games from football-data.org", len(games))`

### Integration Points
- `_COMP_MAP` in `football_data_client.py` — add `"wc": "WC"` entry
- `alpha/data/ingestion/__init__.py` — may need to export new `wc_stats.py` module
- Downstream (Phase 6): `wc_model.py` reads `wc_priors.json` for Elo ratings and calls `wc_stats.py` for team strength modifiers

</code_context>

<specifics>
## Specific Ideas

- `statsbombpy>=1.19.0` is the confirmed library for StatsBomb open data — install via `./venv/Scripts/python.exe -m pip install statsbombpy`
- football-data.org WC competition code confirmed as `"WC"` (verified in research)
- `data/wc_priors.json` is the canonical output of the Elo pipeline — Phase 6 reads this file directly
- STATE.md Pending Todo confirmed: check and add 429 retry before extending `FootballDataClient`

</specifics>

<deferred>
## Deferred Ideas

- WC player-level stats from StatsBomb (goals_per90, shots_per90, assists_per90) — deferred to v1.2 when player props are built
- Live eloratings.net scraper for real-time Elo updates — deferred; Kaggle CSV covers all 48 WC 2026 teams through 2025
- Odds API WC h2h odds ingestion — deferred; need to confirm credit cost and coverage first

</deferred>
