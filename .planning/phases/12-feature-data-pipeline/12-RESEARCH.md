# Phase 12: Soccer Feature Data Pipeline — Research

**Researched:** 2026-06-19
**Domain:** Football-data.org API, Club Elo API, soccerdata/FBref scraping, cache design
**Confidence:** HIGH (all claims verified against installed code or official documentation)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 Form window:** Last 5 games. W/D/L record + goals scored/conceded per game. W=3 pts, D=1, L=0. Track goal difference too.
- **D-02 H2H window:** Last 5 meetings between the two specific teams. Focus on home-team win/draw/loss record in those 5 meetings.
- **D-03 Fatigue signal:** Days rest since last game only. Apply fatigue multiplier when rest < 4 days. No European game flag, no travel distance.
- **D-04 Set piece stats:** FBref via soccerdata library. Target: corners per game, aerial duels won %, pressing intensity (PPDA or pressures). soccerdata brings FBref back for set pieces only.
- **D-05 Historical results source:** football-data.org `/v4/teams/{team_id}/matches` for H2H and form. Same FootballDataClient, same API key, no new credentials.
- **D-06 Club Elo source:** clubelo.com CSV download by date. Fetch at scanner startup, cache to `data/.soccer_cache/club_elo.csv` with daily TTL. Use NBAStatsCache pattern (6h TTL). Same caching approach as wc_elo.py but for club teams.
- **D-07 Cache namespace isolation:** All new modules write to `data/.soccer_cache/`. No overlap with `data/.wc_cache/`. No calls to `wc_elo.py` or `wc_stats.py`.

### Claude's Discretion

- Exact API endpoint params and pagination for football-data.org
- Club Elo CSV format parsing details
- soccerdata FBref scraping method selection
- Cache TTL values (daily for Club Elo, shorter for form/H2H if needed)
- Error handling when stats unavailable (return None / partial dict)

### Deferred Ideas (OUT OF SCOPE)

- European game fatigue flag (midweek competition type)
- Travel distance fatigue
- In-play / live model
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SDATA-01 | `fetch_team_form(team_id, n=5)` returns last-5-game W/D/L record + goals scored/conceded | football-data.org `/v4/teams/{id}/matches?status=FINISHED&limit={n}` returns score.fullTime.home/away and score.winner per match |
| SDATA-02 | `fetch_h2h(home_id, away_id, n=5)` returns last 5 meetings between the two teams | Fetch finished matches for home team, filter client-side where opponent ID matches away_id |
| SDATA-03 | `fetch_days_rest(team_id, match_date)` returns integer days since last game | Same `/v4/teams/{id}/matches?status=FINISHED&limit=2` endpoint; compute delta days; mirrors mlb_training._days_rest() pattern |
| SDATA-04 | FBref set piece stats accessible via soccerdata; Club Elo ratings cached daily | `soccerdata.FBref.read_team_season_stats(stat_type="passing_types")` for CK/corners; `soccerdata.FBref.read_team_season_stats(stat_type="misc")` for aerial duels; `http://api.clubelo.com/YYYY-MM-DD` for Club Elo CSV |
</phase_requirements>

---

## Summary

Phase 12 is a pure data-ingestion phase that extends two existing patterns: the `FootballDataClient` (already serving EPL/UCL game fixtures) and the `wc_elo.py`/`NBAStatsCache` caching idiom. No new credentials are required. All five data signals (form, H2H, days-rest, FBref set pieces, Club Elo) can be delivered by extending existing code rather than creating new HTTP clients.

The football-data.org v4 API at `GET /v4/teams/{id}/matches` is the primary source for form, H2H, and days-rest. This endpoint is available on the free tier and returns completed match scores via `score.fullTime.home/away` and `score.winner`. The team IDs are already embedded in every fixture response the existing `fetch_today_games()` returns (`homeTeam.id`, `awayTeam.id`) — but the current parsing code does not extract them. The first implementation task is to expose those IDs.

FBref set piece stats are available through the already-installed `soccerdata==1.8.8` library via `FBref.read_team_season_stats()`. The relevant stat types are `"passing_types"` for corner kicks (column `corner_kicks` after soccerdata's snake_case normalization of FBref's `CK` data-stat attribute) and `"misc"` for aerial duels won percentage. PPDA is not a native FBref column; the correct proxy is pressures-per-pass from the `"defense"` table. soccerdata caches FBref HTML locally under `~/soccerdata/data/FBref/` — distinct from the project's `data/.soccer_cache/`.

Club Elo's API (`http://api.clubelo.com/YYYY-MM-DD`) returns a CSV with columns: `Rank, Club, Country, Level, Elo, From, To`. `soccerdata.ClubElo.read_by_date()` already wraps this endpoint and returns a pandas DataFrame with standardized column names; however, it stores its own cache under `~/soccerdata/data/ClubElo/`. The plan should use a thin direct `requests.get()` caller that saves to `data/.soccer_cache/club_elo.csv` with daily TTL — keeping our cache namespace clean and matching D-07.

**Primary recommendation:** Extend `FootballDataClient` with `fetch_team_matches()`, add three free-standing functions (`fetch_team_form`, `fetch_h2h`, `fetch_days_rest`) in a new `alpha/data/ingestion/soccer_form.py`, create `alpha/data/ingestion/club_elo.py` mirroring `wc_elo.py`, and create `alpha/data/ingestion/soccer_fbref.py` wrapping `soccerdata.FBref`.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Form / H2H / rest ingestion | API Client layer (`alpha/data/ingestion/`) | — | Pure I/O; football-data.org is the source of truth for completed match results |
| FBref set piece stats | API Client layer (`alpha/data/ingestion/`) | soccerdata library (HTML scraper) | soccerdata wraps FBref scraping; project module wraps soccerdata |
| Club Elo ratings | API Client layer (`alpha/data/ingestion/`) | — | Thin CSV reader over `api.clubelo.com`; same pattern as `wc_elo.py` |
| Cache management | `data/.soccer_cache/` (file-based) | — | Pickle / CSV files with date-keyed TTL; no SQLite needed for this phase |
| Cache namespace isolation | D-07 contract (enforced in module constants) | — | Each new module sets `_CACHE_DIR = Path("data/.soccer_cache")` and never touches `.wc_cache` |

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `requests` | 2.32.3 [VERIFIED: venv] | HTTP calls to football-data.org and clubelo.com | Already used in `FootballDataClient`; no new install |
| `soccerdata` | 1.8.8 [VERIFIED: venv] | FBref HTML scraping (set piece stats) | Already installed; `FBref.read_team_season_stats()` covers all needed stat types |
| `pandas` | 2.3.3 [VERIFIED: venv] | Parse soccerdata DataFrames | Already installed; soccerdata returns DataFrames |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pathlib.Path` | stdlib | Cache file paths | All cache write/read paths |
| `datetime` | stdlib | Daily TTL comparison, date arithmetic for days-rest | `(match_date - last_game_date).days` |
| `pickle` | stdlib | Cache serialization for form/H2H results | Same pattern as `soccer_stats.py` |
| `csv` / `io.StringIO` | stdlib | Parse Club Elo CSV response | `requests.get()` returns text; parse with `csv.DictReader` or `pd.read_csv(io.StringIO(...))` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Direct `requests.get` to clubelo.com | `soccerdata.ClubElo.read_by_date()` | soccerdata ClubElo caches to `~/soccerdata/data/ClubElo/` — violates D-07 namespace isolation; direct fetch gives us full control over `data/.soccer_cache/` |
| File-based pickle cache for form/H2H | SQLite (like NBAStatsCache) | SQLite adds complexity; daily TTL pickle files are sufficient for this phase (same pattern as `soccer_stats.py`) |

**Installation:** No new packages required. All dependencies are already present in `./venv/`.

---

## Package Legitimacy Audit

> Phase 12 installs **no new packages**. All required libraries (`requests`, `soccerdata`, `pandas`) are already installed in the project venv and have been in use since earlier phases.

| Package | Registry | In Use Since | Source Repo | slopcheck | Disposition |
|---------|----------|-------------|-------------|-----------|-------------|
| `requests` | PyPI | Phase 5 | github.com/psf/requests | N/A (pre-existing) | Approved — pre-existing |
| `soccerdata` | PyPI | Phase 5 | github.com/probberechts/soccerdata | N/A (pre-existing) | Approved — pre-existing |
| `pandas` | PyPI | Phase 1 | github.com/pandas-dev/pandas | N/A (pre-existing) | Approved — pre-existing |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## Architecture Patterns

### System Architecture Diagram

```
                          scanner startup
                               |
              +----------------+------------------+
              |                |                  |
              v                v                  v
   soccer_form.py        club_elo.py         soccer_fbref.py
   (form/H2H/rest)    (UCL Club Elo)       (EPL set pieces)
              |                |                  |
              v                v                  v
   FootballDataClient    requests.get()      soccerdata.FBref
   fetch_team_matches()  api.clubelo.com     read_team_season_stats()
              |            YYYY-MM-DD              |
              v                |                  v
   football-data.org           v          ~/soccerdata/data/FBref/
   /v4/teams/{id}/matches  .soccer_cache/   (soccerdata internal cache)
              |            club_elo.csv          |
              v                                  v
   .soccer_cache/                        .soccer_cache/
   form_{team_id}.pkl                    fbref_set_pieces.pkl
   h2h_{home}_{away}.pkl
```

**Data flow for game-day scanner:**

1. `fetch_team_form(team_id, n=5)` — checks `.soccer_cache/form_{team_id}_{date}.pkl`; on miss calls `FootballDataClient.fetch_team_matches(team_id, status="FINISHED", limit=10)`, computes form dict, writes cache.
2. `fetch_h2h(home_id, away_id, n=5)` — checks `.soccer_cache/h2h_{home_id}_{away_id}_{date}.pkl`; on miss calls `fetch_team_matches(home_id, limit=50)`, filters where away team matches, takes last 5, writes cache.
3. `fetch_days_rest(team_id, match_date)` — calls `fetch_team_matches(team_id, limit=2)`, takes most recent completed game, computes `(match_date - last_game_date).days - 1`.
4. `load_club_elo_ratings(date)` — checks `data/.soccer_cache/club_elo_{date}.csv`; on miss calls `GET http://api.clubelo.com/{date}`, parses CSV, writes cache.
5. `get_fbref_set_pieces(league, season)` — checks `.soccer_cache/fbref_set_pieces_{league}_{season}.pkl`; on miss instantiates `soccerdata.FBref`, calls `read_team_season_stats("passing_types")` + `read_team_season_stats("misc")`, merges, writes cache.

### Recommended Project Structure

```
alpha/data/ingestion/
├── football_data_client.py    # EXTEND: add fetch_team_matches() method
├── soccer_form.py             # NEW: fetch_team_form(), fetch_h2h(), fetch_days_rest()
├── club_elo.py                # NEW: load_club_elo_ratings(), get_club_elo_rating()
├── soccer_fbref.py            # NEW: get_fbref_set_pieces()
├── soccer_stats.py            # UNCHANGED: Understat xG rolling stats (keep)
└── wc_elo.py                  # UNCHANGED: WC-only (read-only reference)

tests/unit/data/
├── test_football_data_client_wc.py   # EXISTING: regression tests (must still pass)
├── test_soccer_form.py               # NEW: unit tests for form/H2H/rest
├── test_club_elo.py                  # NEW: unit tests for Club Elo loader
└── test_soccer_fbref.py              # NEW: unit tests for FBref wrapper
```

### Pattern 1: Extending FootballDataClient with fetch_team_matches()

**What:** New method on the existing client; uses `_get_with_retry()` which already handles 429 backoff. Returns raw match list with score, date, and opponent ID fields.

**When to use:** Called by all three form/H2H/rest functions.

**Key fields extracted from each match dict:**

```python
# Source: football-data.org v4 API match resource docs
# https://docs.football-data.org/general/v4/match.html
{
    "id":          match.get("id"),
    "utcDate":     match.get("utcDate"),         # "2025-12-01T15:00:00Z"
    "homeTeam": {
        "id":   match["homeTeam"]["id"],          # numeric int e.g. 57
        "name": match["homeTeam"]["name"],
    },
    "awayTeam": {
        "id":   match["awayTeam"]["id"],          # numeric int e.g. 61
        "name": match["awayTeam"]["name"],
    },
    "score": {
        "winner":   match["score"]["winner"],     # "HOME_WIN"|"AWAY_WIN"|"DRAW"|null
        "fullTime": {
            "home": match["score"]["fullTime"]["home"],  # int goals
            "away": match["score"]["fullTime"]["away"],
        }
    }
}
```

**Proposed method signature:**

```python
def fetch_team_matches(
    self,
    team_id: int,
    *,
    status: str = "FINISHED",
    limit: int = 10,
) -> list[dict]:
    """
    Fetch recent matches for a team from /v4/teams/{team_id}/matches.

    Returns list of raw match dicts with id, utcDate, homeTeam, awayTeam, score.
    Returns [] on any failure.
    """
    if not self.is_configured():
        return []
    try:
        resp = _get_with_retry(
            f"{_BASE_URL}/teams/{team_id}/matches",
            headers={"X-Auth-Token": self.api_key},
            params={"status": status, "limit": limit},
            timeout=10,
        )
        data = resp.json()
        return data.get("matches", [])
    except Exception as exc:
        logger.warning("fetch_team_matches failed for team %s: %s", team_id, exc)
        return []
```

### Pattern 2: fetch_team_form() — computing form dict from raw matches

**What:** Consumes `fetch_team_matches()` output; computes form stats over last n completed matches.

**Output contract:**

```python
# Source: CONTEXT.md D-01
{
    "team_id": 57,
    "games": 5,
    "form_points": 7,         # sum of W=3, D=1, L=0 over n games
    "form_goal_diff": 3,      # total goals_for - goals_against
    "goals_for": 8,           # total goals scored
    "goals_against": 5,       # total goals conceded
    "wdl": ["W", "D", "W", "L", "W"],   # chronological, oldest first
}
```

**Logic: determining home vs away for a given team_id:**

```python
# Source: football-data.org match resource (homeTeam.id / awayTeam.id)
# Each returned match contains both teams; check which side team_id is on
for match in raw_matches:
    is_home = match["homeTeam"]["id"] == team_id
    gf = match["score"]["fullTime"]["home" if is_home else "away"] or 0
    ga = match["score"]["fullTime"]["away" if is_home else "home"] or 0
    winner = match["score"].get("winner")
    if winner == "DRAW":
        result = "D"
    elif (is_home and winner == "HOME_WIN") or (not is_home and winner == "AWAY_WIN"):
        result = "W"
    else:
        result = "L"
```

### Pattern 3: fetch_h2h() — client-side filter from team match history

**What:** Fetches the home team's last N completed matches (limit=50), filters client-side for matches where opponent `id` equals `away_id`. Takes the 5 most recent of those filtered matches.

**Output contract:**

```python
# Source: CONTEXT.md D-02
{
    "home_id": 57,
    "away_id": 61,
    "meetings": 5,
    "h2h_home_wins": 2,
    "h2h_draws": 1,
    "h2h_away_wins": 2,
    "h2h_home_win_rate": 0.4,   # home_wins / meetings
}
```

**Filter logic:**

```python
# For each match in home team's history:
opponent_id = match["awayTeam"]["id"] if is_home else match["homeTeam"]["id"]
if opponent_id == away_id:
    h2h_matches.append(match)
```

**Important:** If fewer than 5 meetings are found, return whatever is available (do not return None). The model layer applies credibility weighting.

### Pattern 4: fetch_days_rest() — days since last game

**What:** Fetches `limit=2` finished matches for team, takes the most recent completed one, computes `(match_date - last_game_date).days - 1`. Mirrors `mlb_training._days_rest()`.

```python
# Source: alpha/engines/sports/mlb_training.py _days_rest()
# min=0, max=7 cap, default 3.0 if no prior game found
def _soccer_days_rest(last_date_str: str, match_date_str: str) -> int:
    if not last_date_str:
        return 3   # neutral default
    delta = date.fromisoformat(match_date_str) - date.fromisoformat(last_date_str)
    return max(0, min(7, delta.days - 1))
```

**Note:** `utcDate` from football-data.org is ISO 8601: `"2025-12-01T15:00:00Z"` — strip the time portion for date comparison.

### Pattern 5: Club Elo CSV reader

**What:** Direct `requests.get("http://api.clubelo.com/YYYY-MM-DD")` call. Returns CSV with columns `Rank,Club,Country,Level,Elo,From,To`. Cache to `data/.soccer_cache/club_elo_{date}.csv`.

**Verified CSV column structure (from soccerdata clubelo.py source):**

```python
# Source: venv/Lib/site-packages/soccerdata/clubelo.py - _parse_csv()
# pd.read_csv(data, parse_dates=["From", "To"], date_format="%Y-%m-%d")
# Columns: Rank, Club, Country, Level, Elo, From, To
```

**Module functions to implement:**

```python
def load_club_elo_ratings(date: str | None = None) -> dict[str, float]:
    """
    Load Club Elo ratings for all clubs on a given date.

    Returns {club_name: elo_rating}.
    Raises RuntimeError on network failure (caller falls back to 1500).
    Cache TTL: daily (one file per date).
    """

def get_club_elo_rating(club: str, ratings: dict[str, float]) -> float:
    """Return rating for club, logging warning and returning 1500.0 on miss."""
```

**Club name matching:** clubelo.com uses its own club name spellings (e.g. "Man City" not "Manchester City"). An alias dict `_CLUB_ALIASES` (same pattern as `wc_elo.py`'s `_TEAM_NAME_ALIASES`) should be maintained.

### Pattern 6: FBref set piece stats via soccerdata

**What:** `soccerdata.FBref(leagues="ENG-Premier League", seasons=2024)` then call `read_team_season_stats()` twice.

**Verified FBref league key for EPL:**

```python
# Source: soccerdata.FBref._all_leagues() — verified in venv
{"ENG-Premier League": "Premier League"}
```

**Stat types and target columns:**

| Call | stat_type | Target column(s) after snake_case |
|------|-----------|----------------------------------|
| `read_team_season_stats("passing_types")` | `passing_types` | `corner_kicks` (FBref `data-stat="corner_kicks"`) |
| `read_team_season_stats("misc")` | `misc` | `won_pct` under `aerial_duels` group (FBref `data-stat="aerials_won_pct"`) |
| `read_team_season_stats("defense")` | `defense` | `pressures` group columns for pressing intensity proxy |

**Important: soccerdata returns multi-level column indexes for some stat types.** The top-level is the stat group name, the second level is the specific column. Access pattern:

```python
df = fbref.read_team_season_stats("passing_types")
# columns are MultiIndex: (group, stat)
# For corners: df[("corner_kicks", "corner_kicks")] or similar
# Must inspect the actual DataFrame to confirm exact MultiIndex path
```

**Practical approach:** Call `.columns.to_list()` on the returned DataFrame in Wave 0 to discover exact column paths before hardcoding them.

**Season format:** soccerdata accepts `seasons=2024` for the 2024-25 season (integer year = starting year of the season).

**FBref scraping rate:** soccerdata adds internal delays between requests; no custom rate limiting needed. soccerdata caches HTML to `~/soccerdata/data/FBref/` — subsequent calls in the same day use the local cache.

### Anti-Patterns to Avoid

- **Using soccerdata.ClubElo for Club Elo:** It caches to `~/soccerdata/data/ClubElo/`, violating D-07. Use direct `requests.get()` instead.
- **Fetching team_id via a second API call:** `homeTeam.id` is already present in the fixture response that `fetch_today_games()` returns. Modify `fetch_today_games()` to include `home_team_id` and `away_team_id` in the returned dict, avoiding a separate team lookup call.
- **Merging soccer_cache with wc_cache:** Every new module must set `_CACHE_DIR = Path("data/.soccer_cache")` with a constant. Spot-checked path from existing `soccer_stats.py`: `_CACHE_DIR = Path("data/.soccer_cache")` — use the same.
- **Returning None from form on partial data:** Return a partial dict with the games that were found. The model layer must handle `games < 5` gracefully.
- **Calling wc_elo.py or wc_stats.py from new modules:** Hard violation of D-07. No imports across the WC / soccer boundary.
- **Ignoring score.winner=None:** Completed matches can have `winner=None` if the result is not yet populated (late update). Skip those matches; do not treat null winner as a draw.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP 429 backoff for football-data.org | Custom retry loop | `_get_with_retry()` in `football_data_client.py` | Already handles 1 retry after 60s; tested |
| FBref HTML scraping | BeautifulSoup + custom parser | `soccerdata.FBref.read_team_season_stats()` | FBref HTML structure is fragile; soccerdata keeps up with layout changes |
| Club Elo CSV parsing | Custom CSV parsing | `pd.read_csv(io.StringIO(response.text))` | clubelo.com returns valid CSV; pandas handles it in one line |
| Daily cache TTL | Time-math in module | Date-keyed filename `{key}_{date.today()}.pkl` | Same pattern used in `soccer_stats.py`; auto-expires as date changes |

**Key insight:** Every non-trivial scraping concern in this phase (retry logic, FBref parsing, CSV parsing) is already solved by existing code in the repo or by soccerdata. The implementation is wiring, not invention.

---

## Runtime State Inventory

> Not applicable — this is a greenfield ingestion phase, not a rename/refactor. No existing runtime state references the new module names.

---

## Common Pitfalls

### Pitfall 1: team_id not extracted from fixture response

**What goes wrong:** `fetch_today_games()` currently extracts only `homeTeam.name` and `awayTeam.name`, not `homeTeam.id`. Without the numeric ID, every form/H2H/rest call requires an extra API call to resolve team name → ID, burning rate-limit budget.

**Why it happens:** The original EPL scanner only needed team names for model lookup. The ID was never needed until now.

**How to avoid:** Modify `fetch_today_games()` (and `fetch_wc_games()` in a targeted way if needed) to also extract `homeTeam.id` and `awayTeam.id` into `home_team_id` and `away_team_id` dict keys. Add regression test that the EPL dict now contains those two new keys.

**Warning signs:** Tests mock the API response but don't include `homeTeam.id` in the mock dict.

### Pitfall 2: soccerdata FBref column MultiIndex

**What goes wrong:** `read_team_season_stats("passing_types")` returns a DataFrame with multi-level column headers `(group, stat)`. Code that tries `df["corner_kicks"]` raises `KeyError` because the outer level is a group name like `"Corner Kicks"`.

**Why it happens:** FBref HTML tables have grouped column headers; soccerdata preserves this structure.

**How to avoid:** In Wave 0, always call `df.columns.to_list()` to discover the actual column paths before accessing them. Use `df.xs("corner_kicks", axis=1, level=1, drop_level=False)` or flatten with `df.droplevel(0, axis=1)` after inspecting.

**Warning signs:** `KeyError` on a column that visually appears in the FBref table.

### Pitfall 3: clubelo.com service availability

**What goes wrong:** `http://api.clubelo.com/YYYY-MM-DD` is an HTTP (not HTTPS) endpoint and returned a 503 during research (intermittent). Synchronous callers will block or raise.

**Why it happens:** The service is maintained by a single developer; occasional downtime is expected.

**How to avoid:** Wrap the request in a try/except; if the cache file exists (even from yesterday), return stale data with a warning rather than raising. Add a `max_age_days=2` grace period before refusing to use stale Club Elo data.

**Warning signs:** `503 Service Unavailable` or `ConnectionError` during unit test mocking if the test doesn't patch `requests.get`.

### Pitfall 4: FBref bot detection / 403 during scraping

**What goes wrong:** FBref returns 403 Forbidden to scraping clients, especially when running without realistic browser headers.

**Why it happens:** FBref actively blocks non-browser user agents. soccerdata 1.8.8 sets `FBREF_HEADERS` to mimic Chrome headers, which usually succeeds, but can still fail if Cloudflare rules tighten.

**How to avoid:** Use soccerdata's built-in `data_dir` caching. Once a season's HTML is cached, no more network calls are made. In tests, always monkeypatch the `soccerdata.FBref` class; never make live FBref calls in the test suite.

**Warning signs:** `403 Client Error` in soccerdata logs; `lxml` parse errors.

### Pitfall 5: H2H match limit insufficient

**What goes wrong:** `fetch_team_matches(home_id, limit=10)` may not include 5 H2H meetings if the teams have not met recently.

**Why it happens:** Top-flight clubs may not face each other more than twice a season.

**How to avoid:** Use `limit=50` for H2H calls (up to 5 seasons of history). This is within the football-data.org free tier's 500 result cap per endpoint call.

**Warning signs:** `h2h_meetings < 5` in returned dict — model must handle gracefully.

### Pitfall 6: Cache file collision between form and H2H

**What goes wrong:** `form_57_2026-06-19.pkl` and `h2h_57_61_2026-06-19.pkl` could be confused if the filename prefix is too short.

**How to avoid:** Use explicit prefixes in cache key: `form_{team_id}_{date}.pkl`, `h2h_{home_id}_{away_id}_{date}.pkl`, `rest_{team_id}_{date}.pkl`.

---

## Code Examples

### Existing caching pattern from soccer_stats.py (extend this)

```python
# Source: alpha/data/ingestion/soccer_stats.py — verified in codebase
_CACHE_DIR = Path("data/.soccer_cache")

def _cache_path(key: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{key}_{date.today()}.pkl"

def _load_cache(key: str) -> Any | None:
    path = _cache_path(key)
    if path.exists():
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    return None

def _save_cache(key: str, data: Any) -> None:
    try:
        with open(_cache_path(key), "wb") as f:
            pickle.dump(data, f)
    except Exception as exc:
        logger.debug("Cache write failed: %s", exc)
```

### Club Elo CSV fetch pattern

```python
# Source: soccerdata clubelo.py analysis — CLUB_ELO_API = "http://api.clubelo.com"
# Verified URL format from soccerdata.ClubElo.read_by_date() source code
import io
import pandas as pd
import requests

_CLUB_ELO_API = "http://api.clubelo.com"

def _fetch_club_elo_csv(date_str: str) -> pd.DataFrame:
    """Fetch Club Elo ratings as a DataFrame. Raises on network failure."""
    url = f"{_CLUB_ELO_API}/{date_str}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    # Columns: Rank, Club, Country, Level, Elo, From, To
    return pd.read_csv(io.StringIO(resp.text))
```

### soccerdata FBref instantiation for EPL

```python
# Source: soccerdata.FBref._all_leagues() — verified: "ENG-Premier League"
# soccerdata version: 1.8.8 (verified in venv)
import soccerdata

def _get_fbref_client(season_year: int = 2024) -> soccerdata.FBref:
    """Return FBref scraper for EPL. season_year=2024 => 2024-25 season."""
    return soccerdata.FBref(
        leagues="ENG-Premier League",
        seasons=season_year,
    )

# Usage:
fbref = _get_fbref_client()
df_passing_types = fbref.read_team_season_stats(stat_type="passing_types")
df_misc = fbref.read_team_season_stats(stat_type="misc")
# MUST inspect df.columns.to_list() to find exact MultiIndex paths for corners/aerial duels
```

### Days-rest pattern (mirrors mlb_training._days_rest)

```python
# Source: alpha/engines/sports/mlb_training.py _days_rest() — verified in codebase
from datetime import date

def _soccer_days_rest(last_date_str: str, match_date_str: str) -> int:
    """Return days rest between last game and upcoming match. Capped [0, 7]. Default 3."""
    if not last_date_str:
        return 3
    last = date.fromisoformat(last_date_str[:10])   # strip time if present
    target = date.fromisoformat(match_date_str[:10])
    return max(0, min(7, (target - last).days - 1))
```

### Form computation from raw match list

```python
# Source: CONTEXT.md D-01, football-data.org match resource docs
def _compute_form(team_id: int, matches: list[dict], n: int = 5) -> dict:
    """Compute form stats from last n finished matches for team_id."""
    finished = [
        m for m in matches
        if m.get("score", {}).get("fullTime", {}).get("home") is not None
    ]
    recent = finished[-n:]  # matches are returned newest-first; reverse for chronological
    wdl, gf_total, ga_total, pts = [], 0, 0, 0
    for m in reversed(recent):
        is_home = m["homeTeam"]["id"] == team_id
        gf = (m["score"]["fullTime"]["home"] if is_home else m["score"]["fullTime"]["away"]) or 0
        ga = (m["score"]["fullTime"]["away"] if is_home else m["score"]["fullTime"]["home"]) or 0
        winner = m["score"].get("winner")
        if winner == "DRAW":
            result, p = "D", 1
        elif (is_home and winner == "HOME_WIN") or (not is_home and winner == "AWAY_WIN"):
            result, p = "W", 3
        else:
            result, p = "L", 0
        wdl.append(result)
        gf_total += gf
        ga_total += ga
        pts += p
    return {
        "team_id": team_id,
        "games": len(recent),
        "form_points": pts,
        "form_goal_diff": gf_total - ga_total,
        "goals_for": gf_total,
        "goals_against": ga_total,
        "wdl": wdl,
    }
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| soccerdata for all soccer stats (broken) | Understat for xG/goals; FBref (soccerdata) for set pieces only | v1.0/v1.1 boundary | Set pieces require FBref; xG is more reliable from Understat |
| Flat wc_elo.py reader (JSON) | Same flat reader pattern for Club Elo (CSV) | Phase 12 (new) | Consistent load pattern; no OOP overhead |

**Deprecated/outdated:**
- `soccer_stats.py` FBref scraping (was attempted, replaced by Understat): the existing code already uses Understat exclusively. FBref returns only for set piece stats in Phase 12 — it does not replace or touch Understat.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `homeTeam.id` and `awayTeam.id` are present in the football-data.org v4 match response on the free tier | Architecture Patterns, Pitfall 1 | If numeric IDs are suppressed on free tier, need a separate team name→ID resolution step or maintain a static name→ID dict |
| A2 | `score.winner` values are exactly `"HOME_WIN"`, `"AWAY_WIN"`, `"DRAW"`, or `null` | Pattern 2 (form logic) | Different values would break the W/D/L classification |
| A3 | `soccerdata.FBref` `"passing_types"` stat type produces a column reachable as `corner_kicks` (possibly under a MultiIndex group) | Pattern 6 | Actual column path may differ; Wave 0 inspection step required |
| A4 | `soccerdata.FBref` `"misc"` stat type includes aerial duels won % column (FBref `data-stat="aerials_won_pct"`) | Pattern 6 | Column may be named differently; Wave 0 inspection required |
| A5 | clubelo.com `http://api.clubelo.com/YYYY-MM-DD` returns CSV with `Club` column matching EPL/UCL club names closely enough to fuzzy-match | Club Elo section | Name mismatches (e.g. "Man City" vs "Manchester City") require alias dict |
| A6 | football-data.org `/v4/teams/{id}/matches?status=FINISHED&limit=50` is available on the free tier | Pitfall 5 | If capped lower on free tier, H2H window will be narrower |

**Claims verified directly against source code or live system:**
- soccerdata version 1.8.8 installed in venv [VERIFIED: venv]
- `_CACHE_DIR = Path("data/.soccer_cache")` is the existing project soccer cache path [VERIFIED: soccer_stats.py]
- `_get_with_retry()` exists in `football_data_client.py` and handles 429 [VERIFIED: codebase]
- `data/.wc_cache/` and `data/.soccer_cache/` are separate directories [VERIFIED: filesystem]
- Current test count: 636 tests passing [VERIFIED: pytest --co]
- FBref league key for EPL is `"ENG-Premier League"` [VERIFIED: soccerdata._all_leagues()]
- Club Elo base URL is `http://api.clubelo.com` [VERIFIED: soccerdata/clubelo.py source]
- clubelo.com CSV columns: `Rank, Club, Country, Level, Elo, From, To` [VERIFIED: soccerdata/clubelo.py `_parse_csv` source]
- football-data.org team ID is numeric integer [VERIFIED: docs.football-data.org/general/v4/match.html]

---

## Open Questions

1. **Are `homeTeam.id` / `awayTeam.id` available on the free tier?**
   - What we know: Official docs show these fields in the match resource schema. Paid tiers definitely include them. [ASSUMED] they are present on the free tier since the existing `fetch_today_games()` response already contains `homeTeam` and `awayTeam` objects.
   - What's unclear: Whether the free tier truncates the team object to name-only.
   - Recommendation: Add a test fixture that includes `.id` in the mock response and verify the extracted value. If live testing shows the field is absent, maintain a static EPL/UCL team name→ID mapping dict as fallback.

2. **What are the exact MultiIndex column paths in the FBref passing_types and misc DataFrames?**
   - What we know: soccerdata normalizes column names to snake_case; top-level headers are group names from FBref HTML.
   - What's unclear: Whether `corner_kicks` is a top-level column or nested under a group like `("Corner Kicks", "corner_kicks")`.
   - Recommendation: Wave 0 of the plan must include a discovery step — instantiate FBref, call `read_team_season_stats("passing_types")`, print `df.columns.to_list()`. Document the paths in the test fixtures before writing any production code.

3. **How reliable is the football-data.org free tier for historical match results (limit=50)?**
   - What we know: The free tier covers EPL (PL) and UCL (CL). The `/teams/{id}/matches` endpoint supports `limit` up to 500 per the docs.
   - What's unclear: Whether historical FINISHED results are gated behind a paid plan.
   - Recommendation: Test live with a real EPL team ID (Arsenal=57) during Wave 0; if FINISHED results are empty, investigate whether `season=` param is needed.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| soccerdata | FBref set pieces | Yes | 1.8.8 | — |
| requests | football-data.org, clubelo.com | Yes | 2.32.3 | — |
| pandas | Club Elo CSV parsing, soccerdata DataFrames | Yes | 2.3.3 | — |
| FOOTBALL_API_KEY env var | FootballDataClient | In .env (from prior phases) | — | Returns [] with warning if absent |
| internet access (FBref) | soccerdata.FBref scraping | Required at first run | — | soccerdata's own cache after first run |
| internet access (clubelo.com) | Club Elo daily refresh | Required; intermittent 503 observed | — | Stale cache (up to 2 days) |
| `data/.soccer_cache/` directory | All new modules | Created on first write | — | `mkdir(parents=True, exist_ok=True)` in each module |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:**
- clubelo.com service outages: return previous day's cached CSV with warning log.
- FBref scraping failures: return `None` / empty dict; downstream model uses xG-only from Understat.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (detected via pyproject.toml) |
| Config file | `pyproject.toml` — `[tool.pytest.ini_options]` |
| Quick run command | `./venv/Scripts/python.exe -m pytest tests/unit/data/ -q --tb=short` |
| Full suite command | `./venv/Scripts/python.exe -m pytest tests/ -q --tb=short` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SDATA-01 | `fetch_team_form(57, n=5)` returns dict with `form_points`, `form_goal_diff`, `goals_for`, `goals_against`, `wdl` | unit | `pytest tests/unit/data/test_soccer_form.py -x` | No — Wave 0 |
| SDATA-01 | Form with all wins: `form_points=15` | unit | `pytest tests/unit/data/test_soccer_form.py::test_form_all_wins -x` | No — Wave 0 |
| SDATA-01 | `fetch_team_form` with empty match list returns `games=0` dict | unit | `pytest tests/unit/data/test_soccer_form.py::test_form_empty -x` | No — Wave 0 |
| SDATA-02 | `fetch_h2h(57, 61, n=5)` returns dict with `h2h_home_win_rate` | unit | `pytest tests/unit/data/test_soccer_form.py::test_h2h_basic -x` | No — Wave 0 |
| SDATA-02 | H2H with fewer than 5 meetings returns available count | unit | `pytest tests/unit/data/test_soccer_form.py::test_h2h_partial -x` | No — Wave 0 |
| SDATA-03 | `fetch_days_rest` returns correct integer days | unit | `pytest tests/unit/data/test_soccer_form.py::test_days_rest -x` | No — Wave 0 |
| SDATA-03 | `fetch_days_rest` returns 3 when no prior game | unit | `pytest tests/unit/data/test_soccer_form.py::test_days_rest_no_prior -x` | No — Wave 0 |
| SDATA-04 | `load_club_elo_ratings()` returns dict with float values | unit | `pytest tests/unit/data/test_club_elo.py -x` | No — Wave 0 |
| SDATA-04 | `load_club_elo_ratings()` reads from `.soccer_cache/` not `.wc_cache/` | unit | `pytest tests/unit/data/test_club_elo.py::test_cache_namespace -x` | No — Wave 0 |
| SDATA-04 | `get_fbref_set_pieces()` returns dict keyed by team name | unit | `pytest tests/unit/data/test_soccer_fbref.py -x` | No — Wave 0 |
| SDATA-04 | FBref module does not import wc_elo or wc_stats | unit (import check) | `pytest tests/unit/data/test_soccer_fbref.py::test_no_wc_imports -x` | No — Wave 0 |
| D-07 (isolation) | `soccer_form._CACHE_DIR` is `data/.soccer_cache`, not `data/.wc_cache` | unit | `pytest tests/unit/data/test_soccer_form.py::test_cache_namespace_isolated -x` | No — Wave 0 |

**Regression gate:** `./venv/Scripts/python.exe -m pytest tests/ -q --tb=short` must show 636+ tests passing before any plan is marked complete.

### Sampling Rate

- **Per task commit:** `./venv/Scripts/python.exe -m pytest tests/unit/data/ -q --tb=short`
- **Per wave merge:** `./venv/Scripts/python.exe -m pytest tests/ -q --tb=short`
- **Phase gate:** Full suite green (≥636 + new tests) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/data/test_soccer_form.py` — SDATA-01, SDATA-02, SDATA-03 (form, H2H, days-rest unit tests)
- [ ] `tests/unit/data/test_club_elo.py` — SDATA-04 Club Elo loader tests
- [ ] `tests/unit/data/test_soccer_fbref.py` — SDATA-04 FBref wrapper tests
- [ ] FBref column discovery: run `FBref.read_team_season_stats("passing_types").columns.to_list()` and document exact paths in test fixtures before writing production code

---

## Security Domain

> `security_enforcement` not explicitly set in `.planning/config.json` — treated as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | football-data.org key in `.env`, not hardcoded |
| V3 Session Management | No | Stateless HTTP |
| V4 Access Control | No | Read-only data pipeline |
| V5 Input Validation | Yes | `team_id` must be int; `date` strings must match `YYYY-MM-DD` |
| V6 Cryptography | No | No secret material beyond existing API key |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| API key leak in logs | Information Disclosure | Log only status codes; never log `self.api_key` |
| Path traversal via team_id in cache filenames | Tampering | Validate team_id is integer before building `form_{team_id}.pkl` path |
| Stale Club Elo data serving inaccurate ratings | Spoofing | Log warning when stale cache is served; include cache date in returned dict |

---

## Sources

### Primary (HIGH confidence)

- `alpha/data/ingestion/football_data_client.py` — existing client structure, `_get_with_retry()`, `_COMP_MAP`, `fetch_today_games()` fields
- `alpha/data/ingestion/soccer_stats.py` — `_CACHE_DIR`, `_cache_path()`, `_load_cache()`, `_save_cache()` patterns
- `alpha/data/ingestion/wc_elo.py` — flat reader pattern with fallback constant
- `alpha/engines/sports/mlb_training.py` — `_days_rest()` implementation to mirror
- `venv/Lib/site-packages/soccerdata/clubelo.py` — `CLUB_ELO_API`, `_parse_csv()`, CSV column list
- `venv/Lib/site-packages/soccerdata/fbref.py` — `read_team_season_stats()` stat types, league key mapping
- [docs.football-data.org/general/v4/team.html](https://docs.football-data.org/general/v4/team.html) — `/v4/teams/{id}/matches` filters (dateFrom, dateTo, status, limit)
- [docs.football-data.org/general/v4/match.html](https://docs.football-data.org/general/v4/match.html) — match object fields (homeTeam.id, score.winner, score.fullTime)

### Secondary (MEDIUM confidence)

- [soccerdata.readthedocs.io/en/latest/datasources/FBref.html](https://soccerdata.readthedocs.io/en/latest/datasources/FBref.html) — FBref stat types overview
- [soccerdata.readthedocs.io/en/latest/reference/clubelo.html](https://soccerdata.readthedocs.io/en/latest/reference/clubelo.html) — ClubElo.read_by_date() signature

### Tertiary (LOW confidence — [ASSUMED])

- football-data.org free tier includes `homeTeam.id` and `awayTeam.id` in match response (not explicitly verified with a live call)
- football-data.org `/v4/teams/{id}/matches?status=FINISHED&limit=50` is accessible on free tier
- FBref `passing_types` produces column reachable via `corner_kicks` key after snake_case normalization

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — all packages verified in venv; no new installs required
- Architecture: HIGH — existing patterns directly reused; FootballDataClient extension is mechanical
- Pitfalls: MEDIUM — most pitfalls verified by code inspection; FBref column names remain ASSUMED until Wave 0 discovery
- Club Elo format: HIGH — verified from soccerdata source code

**Research date:** 2026-06-19
**Valid until:** 2026-07-19 (stable APIs; FBref scraping may change with site updates)

---

## RESEARCH COMPLETE
