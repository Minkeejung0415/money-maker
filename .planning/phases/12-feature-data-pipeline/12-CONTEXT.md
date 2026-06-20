# Phase 12: Soccer Feature Data Pipeline — Context

**Gathered:** 2026-06-19
**Milestone:** v1.4 — Soccer Mode Upgrade
**Status:** Ready for planning

<domain>
## Phase Boundary

Build all new data ingestion modules needed by the upgraded EPL and UCL soccer models:
- Form (last 5 games) from football-data.org
- H2H (last 5 meetings) from football-data.org
- Days-rest fatigue from game schedule
- FBref set piece stats (corners, aerial duels, pressing) via soccerdata
- Club Elo ratings from clubelo.com for UCL teams

This phase is data-only — no model training, no scanner changes. Downstream phases 13 and 14 consume these modules.

</domain>

<decisions>
## Implementation Decisions

### D-01 Form window
Last 5 games — W/D/L record + goals scored/conceded per game. W=3 pts, D=1, L=0. Track goal difference too.

### D-02 H2H window
Last 5 meetings between the two specific teams. Focus on home-team win/draw/loss record in those 5 meetings.

### D-03 Fatigue signal
Days rest since last game only. Apply fatigue multiplier when rest < 4 days. No European game flag, no travel distance.

### D-04 Set piece stats
FBref via soccerdata library. Target: corners per game, aerial duels won %, pressing intensity (PPDA or pressures).
soccerdata was originally scoped for soccer stats but replaced by Understat. Bring it back for set pieces only.

### D-05 Historical results source
football-data.org `/competitions/{id}/matches?team={id}` for H2H and form. Same FootballDataClient, same API key, no new credentials.

### D-06 Club Elo source
clubelo.com CSV download by date. Fetch at scanner startup, cache to `data/.soccer_cache/club_elo.csv` with daily TTL.
Use `NBAStatsCache` pattern (6h TTL). Same caching approach as wc_elo.py but for club teams.

### D-07 Cache namespace isolation
All new modules write to `data/.soccer_cache/` namespace. No overlap with `data/.wc_cache/`. No calls to `wc_elo.py` or `wc_stats.py`.

### Claude's Discretion
- Exact API endpoint params and pagination for football-data.org
- Club Elo CSV format parsing details
- soccerdata FBref scraping method selection
- Cache TTL values (daily for Club Elo, shorter for form/H2H if needed)
- Error handling when stats unavailable (return None / partial dict)

</decisions>

<canonical_refs>
## Canonical References

- `alpha/data/ingestion/football_data_client.py` — extend `FootballDataClient` with `fetch_team_matches(team_id, n=5)` for H2H/form
- `alpha/data/ingestion/wc_elo.py` — pattern to mirror for Club Elo reader (`load_club_elo_ratings()`)
- `alpha/data/ingestion/nba_stats_cache.py` — 6h TTL caching pattern to reuse
- `alpha/data/ingestion/soccer_stats.py` — Understat pipeline (keep for xG/goals; FBref adds on top, no replacement)
- `.planning/phases/05-data-foundation/` — WC data foundation pattern for reference

</canonical_refs>

<code_context>
## Existing Code Insights

- `FootballDataClient` already has `_get_with_retry()` and handles 429 backoff — extend it rather than creating a new client
- `wc_elo.py` uses a simple JSON cache pattern — Club Elo uses CSV (clubelo format) but same idea
- `soccer_stats.py` uses Understat for xG rolling averages — these remain unchanged; FBref set pieces are additive
- soccerdata library is already in venv (was used in earlier soccer work)

</code_context>

<specifics>
## Specific Implementation Notes

- Form signal: encode as `form_points` (sum of W×3+D×1) and `form_goal_diff` over last 5 games
- H2H signal: `h2h_home_win_rate` (home team wins / 5 meetings)
- Rest signal: `home_rest_days`, `away_rest_days` — same pattern as MLB's `_days_rest()` in mlb_training.py
- Club Elo: clubelo.com endpoint is `http://api.clubelo.com/{YYYY-MM-DD}` — returns CSV of all team ratings for that date

</specifics>

<deferred>
## Deferred

- European game fatigue flag (midweek competition type) — deferred to future milestone
- Travel distance fatigue — deferred
- In-play / live model — deferred

</deferred>
