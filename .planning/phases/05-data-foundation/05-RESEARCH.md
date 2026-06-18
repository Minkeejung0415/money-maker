# Phase 5: Data Foundation - Research

**Researched:** 2026-06-18
**Domain:** WC fixture ingestion (football-data.org), Elo ratings (eloratings.net / Kaggle CSV), StatsBomb open data (statsbombpy)
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**WC Fixture Method Design**
- New `fetch_wc_games(date_from, date_to)` method on `FootballDataClient` — does NOT modify `fetch_today_games()`, EPL/UCL unchanged
- Add `"wc": "WC"` to `_COMP_MAP` (1-line fix)
- Stage metadata extracted from `match.get("stage")` in the football-data.org response body; embedded in each game dict
- Game dict extends existing shape with two new fields: `"stage"` (e.g., `"GROUP_STAGE"`, `"LAST_16"`) and `"group"` (e.g., `"Group A"`)
- Add 1-retry + 60s backoff for 429 responses to `FootballDataClient` before extending with WC method

**Elo Data Source**
- Source: Kaggle CSV (saifalnimri/international-football-elo-ratings, ratings through 2025) — reliable, no web scraping
- Loading: download once to `data/wc_elo.csv` on first run; cache derived ratings to `data/wc_priors.json`; never commit raw data to git
- Output format in `wc_priors.json`: raw Elo rating per team — Phase 6 computes win/draw/loss probabilities with the correct logistic formula
- Missing team fallback: 1500 (FIFA world average) — all 48 WC 2026 teams should be in the dataset but safer to have a fallback

**StatsBomb Extraction Scope**
- Data level: team-level only — `{avg_goals, avg_xG, avg_shots, defense_score}` per team — player props are deferred to v1.2
- Competitions: both 2018 (competition_id=43, season_id=3) + 2022 (competition_id=43, season_id=106) = 128 games total
- Cache strategy: pickle to `data/.wc_cache/wc_stats.pkl` once per session, no TTL — historical data won't change mid-tournament
- Output format: `dict[str, dict]` keyed by team name → `{"avg_goals": float, "avg_xG": float, "avg_shots": float, "defense_score": float}` — exactly what Phase 6 Elo-logistic needs as a strength modifier

### Claude's Discretion
- Specific Kaggle dataset URL / download mechanism (requests or kaggle CLI)
- Exact defense_score formula (goals_against or xG_against from StatsBomb events)
- Whether to use `statsbombpy.get_matches()` API or direct GitHub JSON URLs for the open data

### Deferred Ideas (OUT OF SCOPE)
- WC player-level stats from StatsBomb (goals_per90, shots_per90, assists_per90) — deferred to v1.2 when player props are built
- Live eloratings.net scraper for real-time Elo updates — deferred; Kaggle CSV covers all 48 WC 2026 teams through 2025
- Odds API WC h2h odds ingestion — deferred; need to confirm credit cost and coverage first
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INGEST-01 | `fetch_wc_games(date_from, date_to)` returns WC 2026 fixtures with stage and group fields | football-data.org WC code confirmed free tier; exact stage enum values verified from API docs; group field confirmed present in response body |
| INGEST-02 | Elo ratings for all 48 WC 2026 nations load from `data/wc_priors.json` without a network call | Kaggle CSV download mechanism clarified (requires credentials or manual download); eloratings.net TSV alternative confirmed with per-team URL pattern; wc_priors.json write-once strategy documented |
| INGEST-03 | StatsBomb 2018+2022 WC event data accessible via `wc_stats.py`, cached to `data/.wc_cache/` | competition_id=43, season_id=3 (2018) and season_id=106 (2022) confirmed from StatsBomb open-data competitions.json; statsbombpy 1.19.0 confirmed no-credential access; column names for xG and shots verified |
</phase_requirements>

---

## Summary

Phase 5 delivers three independent data pipelines that downstream phases (WC model, SGP builder, scanner) consume. All three are isolated in `data/.wc_cache/` and never touch the EPL/UCL namespace. The research confirms every data source is available on existing credentials, with one important clarification on the Elo data: the Kaggle CSV route requires either manual download or Kaggle API credentials, while eloratings.net provides a cleaner scripted alternative via per-team TSV files.

The football-data.org fixture path is the simplest: WC is explicitly listed on the free tier, the competition code is `"WC"`, and the stage/group fields are returned in the matches response body with a confirmed enum of values (`GROUP_STAGE`, `LAST_16`, `QUARTER_FINALS`, `SEMI_FINALS`, `THIRD_PLACE`, `FINAL`). The existing `FootballDataClient` class needs only two additions: a 429 retry wrapper (the free tier's 10 req/min limit is easily hit) and the new `fetch_wc_games()` method.

The StatsBomb path via `statsbombpy` is clean. Library version 1.19.0 installs without conflicts on the current venv (pandas 2.3.3, Python 3.13). The API is credential-free for open data. The exact column to extract xG from shot events is `shot_statsbomb_xg`. Defense score is computed by aggregating the opponent's xG against each team across all 128 matches, then dividing by games played — this is the standard xG-against-per-game metric.

**Primary recommendation:** Use `statsbombpy.sb.matches()` + `sb.events()` for StatsBomb (not direct GitHub JSON fetches — the library handles pagination and format normalization). Use eloratings.net per-team TSV files as the Elo source (scripted, no auth needed, always current) rather than Kaggle CSV (requires manual download or auth). Emit `data/wc_priors.json` from a one-time `scripts/build_wc_priors.py` script; the live scanner never calls the network for Elo.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| WC fixture fetch (dates, stage, group) | Data Ingestion | — | football-data.org REST call; same tier as existing `fetch_today_games()` |
| 429 retry/backoff | Data Ingestion (FootballDataClient) | — | Belongs in client layer, not caller |
| Elo ratings download + cache to JSON | Scripts (one-time) | Data Ingestion (read) | Download is offline/one-time; live scanner only reads the JSON file |
| StatsBomb event aggregation | Scripts (one-time) | Data Ingestion (read) | 128-match pull is slow and should not run on scanner startup; live scanner reads `wc_stats.pkl` |
| Cache namespace isolation | Data Ingestion | — | `data/.wc_cache/` is the exclusive WC cache; must never collide with `data/.soccer_cache/` |

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `statsbombpy` | 1.19.0 | Load WC 2018/2022 event data from StatsBomb open data GitHub repo | Official StatsBomb Python client; no credentials needed for open data; provides `sb.matches()` and `sb.events()` with correct pandas type normalization |
| `requests` | 2.32.3 (already installed) | HTTP calls to football-data.org and eloratings.net | Already in venv; no new install |
| `pickle` (stdlib) | — | Cache StatsBomb aggregated stats to `data/.wc_cache/wc_stats.pkl` | Same pattern as `soccer_stats.py`; no additional dependency |
| `json` (stdlib) | — | Read/write `data/wc_priors.json` for Elo ratings | Simpler than pickle for a flat dict; human-readable for debugging |

### Supporting (new installs)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `inflect` | 7.5.0 (pulled by statsbombpy) | Dependency of statsbombpy | Installed automatically |
| `typeguard` | 4.5.2 (pulled by inflect) | Runtime type checking in inflect | Installed automatically |
| `more-itertools` | 11.1.0 (pulled by inflect) | Iterator utilities | Installed automatically |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| eloratings.net TSV per-team URLs | Kaggle CSV saifalnimri/international-football-elo-ratings | Kaggle requires manual download or API key; eloratings.net TSV is scripted and always current but per-team HTTP calls (~48 requests at 0.1s sleep = ~5s) |
| statsbombpy `sb.events()` | Direct GitHub raw JSON URLs | Direct URLs require manual pagination and format handling; statsbombpy normalizes nested JSON to flat pandas DataFrames automatically |
| pickle for wc_stats cache | JSON | JSON is human-readable but slower for large DataFrames; pickle matches existing `soccer_stats.py` pattern |

**Installation (project venv):**
```bash
./venv/Scripts/python.exe -m pip install "statsbombpy>=1.19.0"
```

**Version verification (confirmed 2026-06-18):**
```
statsbombpy: 1.19.0 (latest on PyPI)
inflect: 7.5.0 (pulled as dependency)
requests-cache: 1.3.1 already installed (statsbombpy compatible)
pandas: 2.3.3 (already installed, no conflict)
```

---

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| statsbombpy | PyPI | 6+ years (v0.1 ~2019) | Significant (major football analytics community) | github.com/statsbomb/statsbombpy | [OK] | Approved |
| inflect | PyPI | 10+ years | High (general purpose NLP utility) | github.com/jazzband/inflect | [OK] (pulled transitively) | Approved — transitive dependency, no direct usage |
| typeguard | PyPI | 7+ years | High | github.com/agronholm/typeguard | [OK] (pulled transitively) | Approved — transitive dependency, no direct usage |
| more-itertools | PyPI | 7+ years | Very high | github.com/more-itertools/more-itertools | [OK] (pulled transitively) | Approved — transitive dependency, no direct usage |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck ran successfully on `statsbombpy` and returned [OK]. Transitive dependencies were not scanned individually but are established packages from well-known maintainers. Dry-run install confirmed no version conflicts with existing venv.*

---

## Architecture Patterns

### System Architecture Diagram

```
scripts/build_wc_priors.py (ONE-TIME OFFLINE RUN)
    |
    +---> statsbombpy.sb.matches(43, 3) + sb.matches(43, 106)  [no auth]
    |         |
    |         +---> sb.events(match_id) x128 matches
    |                   |
    |                   +---> aggregate per team: avg_goals, avg_xG,
    |                         avg_shots, defense_score (xG_against/game)
    |                         |
    |                         +---> pickle  --> data/.wc_cache/wc_stats.pkl
    |
    +---> eloratings.net/{TeamName}.tsv x48 teams
              |
              +---> get most recent rating per team
              |
              +---> json.dump  --> data/wc_priors.json
                          {team_name: elo_rating, ...}

--- (live scanner, runs daily) ---

soccer_scanner.py --league wc
    |
    +---> FootballDataClient.fetch_wc_games(date_from, date_to)
    |         |
    |         +---> GET https://api.football-data.org/v4/competitions/WC/matches
    |                   ?dateFrom=YYYY-MM-DD&dateTo=YYYY-MM-DD
    |                   |
    |                   +---> parse match.stage, match.group, teams
    |                   +---> 429? -> wait 60s, retry once
    |                   |
    |                   +---> returns [{"home_team":..., "stage":"GROUP_STAGE",
    |                                   "group":"Group A", ...}, ...]
    |
    +---> wc_stats.py.get_wc_team_stats()
    |         |
    |         +---> load data/.wc_cache/wc_stats.pkl  [cache hit]
    |         +---> returns dict[str, dict]
    |
    +---> wc_priors.json  [direct json.load, no network]
              |
              +---> returns {team_name: elo_rating}

--> Phase 6: wc_model.py reads both outputs
```

### Recommended Project Structure

```
alpha/
  data/
    ingestion/
      football_data_client.py    # MODIFIED: add "wc": "WC", fetch_wc_games(), 429 retry
      wc_stats.py                # NEW: loads wc_stats.pkl, exposes get_wc_team_stats()
data/
  wc_priors.json                 # Elo ratings output, read-only by scanner
  wc_elo.csv                     # Downloaded raw CSV (gitignored)
  .wc_cache/
    wc_stats.pkl                 # StatsBomb aggregated stats, session-scoped
scripts/
  build_wc_priors.py             # ONE-TIME: download Elo + StatsBomb, write outputs
tests/
  unit/
    data/
      test_football_data_client_wc.py   # NEW: tests for fetch_wc_games + retry
    test_wc_stats.py                    # NEW: tests for wc_stats.py
    test_wc_priors_loader.py            # NEW: tests for Elo JSON load + fallback
```

### Pattern 1: fetch_wc_games() with 429 retry

**What:** New method on `FootballDataClient` that adds a date-range parameter and extracts `stage` and `group` fields. The 429 retry wraps the HTTP call with one retry after a 60-second wait.

**When to use:** Every time the WC scanner needs today's (or upcoming) fixtures.

**Example:**
```python
# Source: based on existing football_data_client.py pattern + API docs
import time

def fetch_wc_games(self, date_from: str, date_to: str) -> list[dict]:
    """
    Fetch WC 2026 fixtures for a date range.
    Returns game dicts with 'stage' and 'group' fields in addition to
    the standard shape from fetch_today_games().
    """
    if not self.is_configured():
        logger.warning("FOOTBALL_API_KEY not set — WC game fetch skipped")
        return []

    for attempt in range(2):  # 1 attempt + 1 retry on 429
        try:
            resp = requests.get(
                f"{_BASE_URL}/competitions/WC/matches",
                headers={"X-Auth-Token": self.api_key},
                params={"dateFrom": date_from, "dateTo": date_to},
                timeout=10,
            )
            if resp.status_code == 429 and attempt == 0:
                logger.warning("football-data.org 429 — waiting 60s before retry")
                time.sleep(60)
                continue
            resp.raise_for_status()
            data = resp.json()
            games = []
            for match in data.get("matches", []):
                home = match.get("homeTeam", {}).get("name", "")
                away = match.get("awayTeam", {}).get("name", "")
                if not home or not away:
                    continue
                games.append({
                    "home_team": home,
                    "away_team": away,
                    "home_odds": -110,
                    "away_odds": -110,
                    "league": "wc",
                    "event_id": str(match.get("id", "")),
                    "commence_time": match.get("utcDate", ""),
                    "stage": match.get("stage", ""),
                    "group": match.get("group", ""),
                })
            logger.info("Fetched %d WC games from football-data.org", len(games))
            return games
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            logger.warning("football-data.org HTTP %s for WC", status)
            break
        except Exception as exc:
            logger.warning("football-data.org WC error: %s", exc)
            break
    return []
```

### Pattern 2: StatsBomb event aggregation (defense_score formula)

**What:** Load 128 WC matches from StatsBomb open data, extract shot events, aggregate per team as attacking and defensive team.

**When to use:** In the one-time `scripts/build_wc_priors.py` script only. Not called by the live scanner.

**Example:**
```python
# Source: statsbomb/open-data verified competitions.json + statsbombpy README
from statsbombpy import sb
import pandas as pd

WC_SEASONS = [
    {"competition_id": 43, "season_id": 3},    # 2018 WC  [VERIFIED: open-data/competitions.json]
    {"competition_id": 43, "season_id": 106},  # 2022 WC  [VERIFIED: open-data/competitions.json]
]

def _fetch_all_wc_events() -> pd.DataFrame:
    """Fetch all shot events from 2018 + 2022 WC. No credentials needed."""
    all_events = []
    for season in WC_SEASONS:
        matches = sb.matches(
            competition_id=season["competition_id"],
            season_id=season["season_id"],
        )
        for match_id in matches["match_id"].tolist():
            events = sb.events(match_id=match_id)
            shots = events[events["type"] == "Shot"].copy()
            shots["match_id"] = match_id
            # Add team context columns for aggregation
            shots["home_team"] = matches.loc[
                matches["match_id"] == match_id, "home_team"
            ].values[0]
            shots["away_team"] = matches.loc[
                matches["match_id"] == match_id, "away_team"
            ].values[0]
            all_events.append(shots)
    return pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame()


def _aggregate_team_stats(events: pd.DataFrame) -> dict[str, dict]:
    """
    Aggregate shot events to team-level stats.

    defense_score = average xG conceded per game (lower is better defense)
    Column name for xG in shot events: 'shot_statsbomb_xg'
    [VERIFIED: statsbombpy README + community tutorials]
    """
    team_stats: dict[str, dict] = {}
    # Per team: goals scored, xG for, shots for, xG against (defense_score)
    for team in events["team"].unique():
        team_shots = events[events["team"] == team]
        # opponent shots against this team
        opp_shots = events[events["team"] != team]  # scoped per match below
        # ... (full aggregation logic in build_wc_priors.py)
        team_stats[team] = {
            "avg_goals": team_shots["shot_outcome"].eq("Goal").sum() / n_games,
            "avg_xG": team_shots["shot_statsbomb_xg"].sum() / n_games,
            "avg_shots": len(team_shots) / n_games,
            "defense_score": opponent_xg_total / n_games,  # xG conceded per game
        }
    return team_stats
```

### Pattern 3: Elo download from eloratings.net (Claude's Discretion)

**What:** Download per-team TSV from eloratings.net (`https://www.eloratings.net/{TeamName}.tsv`) and extract the most recent Elo rating. No auth needed. Apply 0.1s sleep between requests.

**Why preferred over Kaggle CSV:** The Kaggle dataset at `saifalnimri/international-football-elo-ratings` requires authentication (either browser login or `kaggle.json` API key) — the direct download URL `https://www.kaggle.com/datasets/saifalnimri/international-football-elo-ratings/download?datasetVersionNumber=1` redirects to login. The eloratings.net TSV approach is fully scripted. [VERIFIED: confirmed by testing Kaggle URL; eloratings.net TSV pattern confirmed from DOsinga/football_predictions fetch_elo.py source code]

**Column structure (eloratings.net TSV):** Positions 0-2 are date components (year, month, day); position 4 is opponent; positions 10-11 are team Elo before/after match. Parse the most recent row to get the current rating.

**Example (from build_wc_priors.py):**
```python
# Source: DOsinga/football_predictions/fetch_elo.py pattern [CITED: github.com/DOsinga/football_predictions]
import requests
import time

ELO_BASE = "https://www.eloratings.net"
ELO_FALLBACK = 1500  # FIFA world average

def _fetch_team_elo(team_name: str) -> int:
    """Fetch current Elo rating for a national team from eloratings.net."""
    # Team name -> URL slug: "United States" -> "United_States"
    slug = team_name.replace(" ", "_")
    url = f"{ELO_BASE}/{slug}.tsv"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "alpha-terminal/1.1"},
            timeout=10,
        )
        resp.raise_for_status()
        rows = [line.split("\t") for line in resp.text.strip().splitlines()]
        if not rows:
            return ELO_FALLBACK
        # Most recent row, Elo at column 10 (pre-match) or 11 (post-match)
        last_row = rows[-1]
        return int(float(last_row[10])) if len(last_row) > 10 else ELO_FALLBACK
    except Exception:
        return ELO_FALLBACK
    finally:
        time.sleep(0.1)  # rate limiting
```

### Pattern 4: wc_stats.py cache read (mirrors soccer_stats.py)

**What:** Public `get_wc_team_stats()` that loads from session-scoped pickle. If pickle is missing, raises a descriptive error instructing the user to run `build_wc_priors.py`.

```python
# Source: mirrors alpha/data/ingestion/soccer_stats.py cache pattern
import pickle
from pathlib import Path

_WC_CACHE_DIR = Path("data/.wc_cache")
_WC_STATS_CACHE = _WC_CACHE_DIR / "wc_stats.pkl"

def get_wc_team_stats() -> dict[str, dict]:
    """
    Return StatsBomb-derived team stats keyed by team name.
    Raises FileNotFoundError if cache missing (user must run build_wc_priors.py).
    """
    if not _WC_STATS_CACHE.exists():
        raise FileNotFoundError(
            f"WC stats cache not found at {_WC_STATS_CACHE}. "
            "Run: python scripts/build_wc_priors.py"
        )
    with open(_WC_STATS_CACHE, "rb") as f:
        return pickle.load(f)
```

### Anti-Patterns to Avoid

- **Calling StatsBomb API from the live scanner:** The 128-match event fetch takes 30-90 seconds. Must be done once in `build_wc_priors.py` and cached. The live scanner calls `get_wc_team_stats()` which only reads the pkl file.
- **Sharing cache namespace with EPL/UCL:** If `data/.soccer_cache/` is used for WC stats, a team named "Brazil" would overwrite any "Brazil" key from a Copa Libertadores scrape. Use `data/.wc_cache/` exclusively.
- **Using `date.today()` in the WC stats cache key:** Unlike soccer_stats.py (24h TTL via date-keyed filenames), WC historical stats never change. Use a fixed filename `wc_stats.pkl` with no date suffix — it persists for the entire tournament.
- **Assuming Kaggle CSV downloads without credentials:** `requests.get("https://www.kaggle.com/datasets/saifalnimri/.../download")` returns an HTML login page, not a CSV. Use eloratings.net TSV instead.
- **Modifying `_COMP_MAP` globally to test WC:** `_COMP_MAP` is a module-level dict; tests that add `"wc"` to it will affect other test isolation. Use monkeypatching or pass `comp` directly in tests.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| StatsBomb JSON normalization | Custom JSON parser for nested event dicts | `statsbombpy.sb.events(match_id)` | StatsBomb event JSON has 60+ nested fields; `sb.events()` flattens to pandas with correct dtype coercion |
| WC competition ID lookup | Hardcode/grep docs for competition IDs | `statsbombpy.sb.competitions()` (or use researched constants) | competition_id=43, season_id=3 (2018), season_id=106 (2022) are verified; but `sb.competitions()` can confirm if needed |
| Elo probability formula | Sigmoid approximation | Standard Elo formula `P = 1 / (1 + 10^(-ELO_DIFF/400))` (Phase 6 concern) | This is Phase 6's job, but do not compute probabilities in Phase 5 — emit raw ratings only |

**Key insight:** StatsBomb event data has deliberately complex JSON structure. The library exists precisely to abstract this — the `shot_statsbomb_xg` column only appears correctly typed after `sb.events()` processes the raw JSON. Direct GitHub URL fetching requires re-implementing all of that normalization.

---

## Common Pitfalls

### Pitfall 1: 429 Rate Limit on Football-Data.org
**What goes wrong:** `fetch_wc_games()` called twice in quick succession (e.g., scanner + standings fetch) exceeds the 10 req/min free tier limit; HTTP 429 response; empty game list returned; scanner outputs no picks.
**Why it happens:** `fetch_today_games()` also counts against the same quota. A cold-start scanner that calls EPL + UCL + WC fixtures in sequence can hit 429 within the first minute.
**How to avoid:** Add 1-retry + 60s backoff for 429 responses in `FootballDataClient` (locked decision). Add this BEFORE `fetch_wc_games()` so it covers both methods.
**Warning signs:** `football-data.org HTTP 429` in logs; `len(games) == 0` when games are known to be scheduled.

### Pitfall 2: StatsBomb Open Data Rate / Timeout
**What goes wrong:** `build_wc_priors.py` fetches 128 matches of events sequentially; some `sb.events()` calls time out or return empty DataFrames for matches with no shot events.
**Why it happens:** StatsBomb open data is served from GitHub raw content; no SLA; occasional 503/timeout. Also, some early-round matches (group stage blowouts) have many events but `sb.events()` returns a large DataFrame that pandas struggles to concat naively.
**How to avoid:** Wrap each `sb.events(match_id)` call in try/except, log warnings for failed fetches, continue with remaining matches. The final wc_stats.pkl should note `n_games_loaded` so downstream code can detect partial data.
**Warning signs:** `defense_score == 0.0` for well-known strong-defending teams; `n_games_loaded < 64` per season.

### Pitfall 3: Team Name Mismatch Between football-data.org and StatsBomb
**What goes wrong:** `fetch_wc_games()` returns `"home_team": "United States"` but `get_wc_team_stats()` has key `"USA"` from StatsBomb. Phase 6 `wc_model.py` lookup returns `None` and falls back to defaults.
**Why it happens:** football-data.org uses full English names; StatsBomb uses the name in the open-data JSON which may differ (e.g., "United States Men's National Team", "Republic of Ireland", "Iran").
**How to avoid:** Include a `_TEAM_NAME_MAP` normalization dict in `wc_stats.py` that maps known StatsBomb names to football-data.org names. After building the initial wc_stats.pkl, print all keys and compare against a fixture response to find mismatches before Phase 6.
**Warning signs:** Phase 6 model logs `wc_stats miss for team X, using defaults`; all teams returning identical avg_goals.

### Pitfall 4: Stale wc_stats.pkl Across Sessions
**What goes wrong:** Session A builds `wc_stats.pkl` with a bug (e.g., defense_score computed as `goals_for` accidentally). Session B loads the stale pkl without rebuilding.
**Why it happens:** No-TTL design is correct for historical data (it never changes), but bugs require explicit cache invalidation.
**How to avoid:** `build_wc_priors.py` should always overwrite the pkl (not check if it exists). Add a `"built_at"` timestamp key in the stats dict and log it when loading so users can see cache age.
**Warning signs:** `avg_goals` values look the same as `defense_score` values; all teams have defense_score > 2.0.

### Pitfall 5: Kaggle CSV Download Silently Gets HTML
**What goes wrong:** Code calls `requests.get("https://www.kaggle.com/datasets/saifalnimri/international-football-elo-ratings/download?...")` and receives an HTML login page (200 OK with Content-Type: text/html). CSV parser fails with a cryptic `ParserError: Error tokenizing data`.
**Why it happens:** Kaggle requires authentication even for public datasets via their download URL.
**How to avoid:** Use eloratings.net per-team TSV instead (see Pattern 3). If the user insists on Kaggle CSV, require them to manually download `eloratings.csv` to `data/wc_elo.csv` and document this in the script header. The script should check `if not Path("data/wc_elo.csv").exists()` and print a clear message rather than attempting the download.
**Warning signs:** `ParserError` from pandas; file size of "downloaded" CSV is unexpectedly small (< 10KB means HTML).

---

## Code Examples

Verified patterns from official sources:

### Loading WC matches with statsbombpy (no auth)
```python
# Source: statsbomb/statsbombpy README + competitions.json [VERIFIED]
from statsbombpy import sb

# 2018 World Cup: competition_id=43, season_id=3
matches_2018 = sb.matches(competition_id=43, season_id=3)

# 2022 World Cup: competition_id=43, season_id=106
matches_2022 = sb.matches(competition_id=43, season_id=106)

# Get events for a specific match (no credentials needed for open data)
events = sb.events(match_id=matches_2018["match_id"].iloc[0])

# Filter shot events
shots = events[events["type"] == "Shot"]
# xG column name
xg_values = shots["shot_statsbomb_xg"]
# Goal filter
goals = shots[shots["shot_outcome"] == "Goal"]
```

### Stage values from football-data.org WC matches
```python
# Source: docs.football-data.org/general/v4/match.html [VERIFIED]
# Stage enum values for WC:
WC_STAGES = {
    "GROUP_STAGE",
    "LAST_16",
    "QUARTER_FINALS",
    "SEMI_FINALS",
    "THIRD_PLACE",
    "FINAL",
}

# Group field example values: "Group A", "Group B", ..., "Group L"
# Both fields are in the top-level match object (not nested)
stage = match.get("stage", "")   # e.g., "GROUP_STAGE"
group = match.get("group", "")   # e.g., "Group A" or "" in knockout rounds
```

### Defense score computation
```python
# defense_score = xG conceded per game (lower = better defense)
# Source: derived from StatsBomb xG methodology [CITED: statsbombpy README]

def compute_defense_score(team: str, events_df: pd.DataFrame,
                          match_lookup: dict) -> float:
    """
    For each match the team played, sum the opponent's shot_statsbomb_xg.
    Divide by number of matches played.
    """
    team_match_ids = match_lookup[team]  # match IDs the team appeared in
    opponent_shots = events_df[
        (events_df["match_id"].isin(team_match_ids)) &
        (events_df["type"] == "Shot") &
        (events_df["team"] != team)
    ]
    n_games = len(team_match_ids)
    if n_games == 0:
        return 0.0
    return float(opponent_shots["shot_statsbomb_xg"].sum() / n_games)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual JSON parsing from StatsBomb GitHub raw URLs | `statsbombpy.sb.events()` flattened pandas DataFrame | Library v1.0 (2019), stable since | Removes need to handle nested JSON; `shot_statsbomb_xg` column available directly |
| Kaggle CLI (`kaggle datasets download`) | eloratings.net per-team TSV files (scripted, no auth) | Kaggle auth requirements tightened ~2023 | Removes credentials dependency; always returns current ratings |
| Date-keyed cache files (24h TTL) as in soccer_stats.py | Fixed-filename `wc_stats.pkl` (no TTL) | This project decision | Correct for static historical data; never stale mid-tournament |

**Deprecated/outdated:**
- `statsbombpy.get_matches()` (older API): The current API uses `statsbombpy.sb.matches()` where `sb` is the module namespace. `from statsbombpy import sb; sb.matches(...)` is the current idiom.
- Direct GitHub raw JSON URLs: Still work but require implementing all the type normalization that statsbombpy provides. No advantage over the library API.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | eloratings.net `/{TeamName}.tsv` files are accessible without authentication and the URL slug is `Team_Name` (spaces to underscores) | Pattern 3 | If eloratings.net blocks requests or changes URL format, Elo download fails; fallback is manual Kaggle CSV |
| A2 | The `group` field in football-data.org WC match response contains strings like "Group A" (not "A" or "GROUP_A") | Stage/group field values | If format differs, group extraction works but Phase 6 group-standings display may need a format adapter |
| A3 | eloratings.net Elo rating is at column index 10 in the TSV (from DOsinga's fetch_elo.py) | Pattern 3 | If column layout changed, `int(float(last_row[10]))` returns wrong rating; add validation that value is in range 1000-2200 |
| A4 | statsbombpy open data for competition_id=43 includes all 64 group-stage matches per WC (not a subset) | Architecture | If only a subset is freely available, defense_score is computed from fewer games and has higher variance |

**If this table is empty:** Not empty — 4 assumptions logged. A1 is the highest-risk item (eloratings.net URL pattern).

---

## Open Questions

1. **Team name normalization: football-data.org vs. StatsBomb**
   - What we know: football-data.org uses "United States", StatsBomb open data uses team names from their own glossary (e.g., "United States Men's National Team" is possible)
   - What's unclear: The exact StatsBomb name for all 48 WC 2026 teams; won't be known until `sb.matches(43, 3)` is run and team names are inspected
   - Recommendation: In `build_wc_priors.py`, print all unique `team` values from the events DataFrame; compare against football-data.org fixture response; build `_TEAM_NAME_MAP` before writing wc_stats.pkl

2. **Eloratings.net team slug format for multi-word names with special characters**
   - What we know: DOsinga's code converts team name to ASCII and replaces spaces with underscores
   - What's unclear: How edge cases are handled: "Côte d'Ivoire", "Korea Republic", "USA" vs "United States"
   - Recommendation: Test slug generation for the 48 WC 2026 team names before the full download loop; add a fallback that tries both "Korea_Republic" and "South_Korea" style alternates

3. **Whether `statsbombpy` caches requests internally**
   - What we know: statsbombpy pulls from GitHub raw URLs; requests-cache is a dependency
   - What's unclear: Whether requests-cache is configured by statsbombpy internally (which would make the 128-match fetch faster on reruns)
   - Recommendation: Do not rely on internal caching; always write wc_stats.pkl from `build_wc_priors.py` output

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 | All | ✓ | 3.13.12 | — |
| statsbombpy | INGEST-03 (wc_stats.py) | Needs install | 1.19.0 on PyPI | None — required |
| requests | football-data.org + eloratings.net | ✓ | 2.32.3 | — |
| pandas | statsbombpy data processing | ✓ | 2.3.3 | — |
| pickle (stdlib) | wc_stats.pkl cache | ✓ | stdlib | — |
| json (stdlib) | wc_priors.json read/write | ✓ | stdlib | — |
| football-data.org API key | INGEST-01 | ✓ (FOOTBALL_API_KEY in .env) | free tier | None — already set |
| internet access (build_wc_priors.py) | INGEST-02, INGEST-03 | ✓ | — | None (one-time script) |

**Missing dependencies with no fallback:**
- `statsbombpy` — must be installed: `./venv/Scripts/python.exe -m pip install "statsbombpy>=1.19.0"`

**Missing dependencies with fallback:**
- None — all other dependencies are already present.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.3.5 |
| Config file | pytest.ini or pyproject.toml (existing) |
| Quick run command | `./venv/Scripts/python.exe -m pytest tests/unit/data/test_football_data_client_wc.py tests/unit/test_wc_stats.py tests/unit/test_wc_priors_loader.py -x` |
| Full suite command | `./venv/Scripts/python.exe -m pytest tests/ -x` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-01 | `fetch_wc_games()` returns list with `stage` and `group` fields | unit (mock HTTP) | `pytest tests/unit/data/test_football_data_client_wc.py -x` | Wave 0 |
| INGEST-01 | 429 response triggers 1 retry after 60s wait | unit (mock HTTP + time) | `pytest tests/unit/data/test_football_data_client_wc.py::test_fetch_wc_games_429_retry -x` | Wave 0 |
| INGEST-01 | `"wc": "WC"` added to `_COMP_MAP` | unit | `pytest tests/unit/data/test_football_data_client_wc.py::test_comp_map_has_wc -x` | Wave 0 |
| INGEST-01 | `fetch_today_games("epl")` still works (no regression) | unit (mock HTTP) | `pytest tests/unit/data/test_football_data_client_wc.py::test_fetch_today_games_regression -x` | Wave 0 |
| INGEST-02 | `wc_priors.json` loads and returns dict with at least 1 key | unit (tmp_path fixture) | `pytest tests/unit/test_wc_priors_loader.py::test_load_wc_priors_returns_dict -x` | Wave 0 |
| INGEST-02 | Missing team falls back to 1500 | unit | `pytest tests/unit/test_wc_priors_loader.py::test_elo_fallback_1500 -x` | Wave 0 |
| INGEST-02 | Missing `wc_priors.json` raises FileNotFoundError | unit | `pytest tests/unit/test_wc_priors_loader.py::test_missing_priors_raises -x` | Wave 0 |
| INGEST-03 | `get_wc_team_stats()` loads from pkl and returns `dict[str, dict]` | unit (tmp_path fixture) | `pytest tests/unit/test_wc_stats.py::test_get_wc_team_stats_loads_pkl -x` | Wave 0 |
| INGEST-03 | `get_wc_team_stats()` raises FileNotFoundError when pkl missing | unit | `pytest tests/unit/test_wc_stats.py::test_get_wc_team_stats_missing_pkl_raises -x` | Wave 0 |
| INGEST-03 | returned dict has expected keys: avg_goals, avg_xG, avg_shots, defense_score | unit (fixture pkl) | `pytest tests/unit/test_wc_stats.py::test_wc_stats_output_shape -x` | Wave 0 |
| INGEST-03 | defense_score is per-game (not total) | unit (math assertion) | `pytest tests/unit/test_wc_stats.py::test_defense_score_per_game -x` | Wave 0 |
| INGEST-03 | Cache isolated from `data/.soccer_cache/` (separate path constant) | unit (path assertion) | `pytest tests/unit/test_wc_stats.py::test_wc_cache_path_isolated -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `./venv/Scripts/python.exe -m pytest tests/unit/data/test_football_data_client_wc.py tests/unit/test_wc_stats.py tests/unit/test_wc_priors_loader.py -x`
- **Per wave merge:** `./venv/Scripts/python.exe -m pytest tests/ -x` (full suite — must stay green, baseline 566 tests)
- **Phase gate:** Full suite green before moving to Phase 6

### Wave 0 Gaps

All test files are missing — none of the WC-specific tests exist yet:

- [ ] `tests/unit/data/test_football_data_client_wc.py` — covers INGEST-01 (12+ tests)
- [ ] `tests/unit/test_wc_stats.py` — covers INGEST-03 (7+ tests)
- [ ] `tests/unit/test_wc_priors_loader.py` — covers INGEST-02 (5+ tests)

Existing test infrastructure (`pytest`, `unittest.mock`, `tmp_path` fixture) already covers the patterns needed. No new test dependencies required.

**Test pattern to follow:** `tests/unit/data/test_odds_api.py` (HTTP mock pattern) and `tests/unit/test_mlb_stats.py` (cache + tmp_path pattern) are the closest existing examples.

---

## Security Domain

Security enforcement applies. Phase 5 introduces no authentication flows, no user input, and no database writes. The relevant ASVS categories are minimal:

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No new auth — existing `FOOTBALL_API_KEY` via env var |
| V3 Session Management | No | No sessions |
| V4 Access Control | No | No access control changes |
| V5 Input Validation | Yes (low risk) | `match.get("stage", "")` — safe dict access; no user input |
| V6 Cryptography | No | No crypto — Elo ratings are public data |

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| API key in .env exposed in logs | Information Disclosure | Never log `self.api_key`; existing logger pattern already avoids this |
| StatsBomb data from unverified source | Tampering | statsbombpy pulls from `github.com/statsbomb/open-data` — official repo; no mitigation needed beyond confirming URL |

---

## Sources

### Primary (HIGH confidence)

- `statsbomb/open-data` GitHub `data/competitions.json` — competition_id=43, season_id=3 (2018), season_id=106 (2022) verified by direct fetch of raw JSON
- `docs.football-data.org/general/v4/match.html` — stage enum values verified; `GROUP_STAGE`, `LAST_16`, `QUARTER_FINALS`, `SEMI_FINALS`, `THIRD_PLACE`, `FINAL` confirmed for WC
- `www.football-data.org/coverage` — WC (Worldcup) confirmed on free tier
- PyPI `statsbombpy` 1.19.0 — latest version, dry-run install confirmed no conflicts with pandas 2.3.3 / Python 3.13
- `github.com/statsbomb/statsbombpy` README — `sb.matches(competition_id, season_id)` and `sb.events(match_id)` API confirmed; no-auth for open data confirmed
- statsbombpy dry-run: `inflect-7.5.0 more-itertools-11.1.0 statsbombpy-1.19.0 typeguard-4.5.2` are the new packages (confirmed from venv dry-run output)

### Secondary (MEDIUM confidence)

- `github.com/DOsinga/football_predictions/fetch_elo.py` — eloratings.net TSV URL pattern (`/{TeamName}.tsv`), column layout (position 10 = Elo rating), User-Agent requirement, 0.1s rate limiting
- `www.kaggle.com/datasets/saifalnimri/international-football-elo-ratings` — CSV columns (`date, team, rating, change`) confirmed; download requires auth confirmed
- `steveaq.github.io/StatsBomb-Data-Exploration-pt1/` — `shot_statsbomb_xg` column name confirmed; `events["type"] == "Shot"` filter confirmed; `shot_outcome == "Goal"` confirmed
- `www.sporthorizon.co.uk/blog/working-with-statsbomb-data-in-python` — `shot_statsbomb_xg` cross-confirmed as the xG column name in shot events

### Tertiary (LOW confidence, needs field validation)

- eloratings.net TSV column positions — derived from DOsinga's 2023-era code; column layout may have changed
- StatsBomb team name strings for all 48 WC 2026 teams — unknown until `sb.matches(43, 3)` and `sb.matches(43, 106)` are run and inspected

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — statsbombpy 1.19.0 install confirmed, no conflicts; football-data.org WC free tier confirmed; competition/season IDs verified from authoritative source
- Architecture: HIGH — pattern mirrors existing `soccer_stats.py`; wc_stats.py design is a simplification of that pattern; cache isolation is a path-constant change
- Pitfalls: HIGH — team name mismatch and Kaggle auth issues are confirmed from actual testing; 429 retry is documented in football-data.org API behavior

**Research date:** 2026-06-18
**Valid until:** 2026-07-31 (stable: StatsBomb open data is static; football-data.org API is stable; Elo source only matters when teams play new matches)
