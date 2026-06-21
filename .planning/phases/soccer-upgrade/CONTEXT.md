# Soccer Mode Upgrade — Context

**Gathered:** 2026-06-19
**Milestone:** v1.4 (proposed — phases TBD, will follow v1.3 MLB)
**Status:** Ready for planning

<domain>
## Phase Boundary

Upgrade the EPL + UCL soccer scanner from a near-market-echo model to an
independent prediction engine. The model currently falls back to market-implied
odds whenever the ProphitBet XGBoost pkl is absent (which is almost always).
This milestone adds four new signal categories, retrains XGBoost on EPL
historical data, replaces the UCL fallback with Club Elo, and enables draw
betting when the model strongly favors it.

**In scope:**
- Feature pipeline: form (last 5), H2H (last 5 meetings), days-rest fatigue, FBref set piece stats
- EPL model: retrain XGBoost with expanded feature schema (3 seasons historical data)
- UCL model: Club Elo-logistic (clubelo.com), same pattern as WC Elo model
- Draw betting: include draw legs when model EV > 5% (replaces skip-all)
- Data sources: football-data.org historical results (H2H + form + schedule), soccerdata/FBref (set pieces)

**Out of scope:**
- Soccer player props (no free odds source — deferred)
- validate_soccer_picks.py accuracy grader (user deferred to later)
- In-play / live model
- European game fatigue flag (only days-rest, not midweek competition type)
- UCL XGBoost (too few games per team — Elo-logistic instead)

</domain>

<decisions>
## Implementation Decisions

### Feature Engineering

- **D-01 Form window:** Last 5 games — W/D/L record + goals scored/conceded per game. Standard analytics window.
- **D-02 H2H window:** Last 5 meetings between the two specific teams. Captures persistent matchup tendencies without using stale data.
- **D-03 Fatigue signal:** Days rest since last game only. Apply a fatigue multiplier when rest < 4 days. No European game flag; no travel distance.
- **D-04 Set piece / style metrics:** FBref via soccerdata library. Target: corners per game, aerial duels won %, pressing intensity (PPDA or pressures). These cover factors that affect low-scoring games differently.

### Data Sources

- **D-05 Historical results:** football-data.org `/competitions/{id}/matches?team={id}` endpoint for H2H lookup and form computation. Same API key, no new credentials.
- **D-06 Set piece data:** soccerdata (FBref scraper) — was originally scoped for soccer stats but replaced by Understat. Bring it back for set pieces only, keep Understat for xG/goals.
- **D-07 Club Elo:** clubelo.com for UCL teams. Same Elo-logistic formula used in WC model (`wc_model.py`). Fetch ratings at scanner runtime (or cache daily).

### Model Architecture

- **D-08 EPL model:** Retrain XGBoost classifier on 3 seasons of EPL historical data (~1,140 games). Feature schema = rolling xG/goals (Understat) + form + H2H + days-rest + set pieces. Same train/calibrate/test pattern as NBA v1.0.
- **D-09 UCL model:** Club Elo-logistic. No XGBoost for UCL — per-team UCL game count is too sparse (~6-8 games/season). This is a clean separation: `SoccerModel` routes EPL games to XGBoost, UCL games to a new `UCLEloModel`.
- **D-10 Claude's discretion on architecture:** exact feature normalization, calibration method (Platt scaling vs. isotonic), and train/val/test split dates are Claude's call.

### Draw Market

- **D-11 Draw betting enabled:** Include draw legs in parlay combinations when model-estimated draw probability produces EV > 5%. Previously draw bets were skipped entirely (illiquid risk).
- **D-12 Draw gate:** Only include draw legs in classic parlays when the model produces a draw probability estimate from the Elo or XGBoost layer — not from market-implied fallback. Market-implied draw bets are never included.

### Claude's Discretion

- Exact calibration technique for XGBoost probabilities (Platt scaling preferred based on NBA experience)
- Train/val/test window dates for EPL historical data
- Feature normalization strategy
- How to handle team name mismatches between football-data.org and Understat/FBref

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Soccer Engine
- `alpha/engines/sports/soccer_model.py` — Current SoccerModel (XGBoost + market-implied fallback). New work extends or replaces the XGBoost layer; market-implied remains as final fallback.
- `alpha/engines/sports/wc_model.py` — WCMatchModel with Elo-logistic formula and dynamic draw algorithm. The UCL Elo model (`UCLEloModel`) should mirror this pattern.
- `alpha/engines/sports/soccer_sgp_builder.py` — SGP builder. Draw legs need to be added as a valid bet type.
- `scripts/soccer_scanner.py` — Main scanner entry point. Routing logic between EPL XGBoost and UCL Elo lives here.

### Existing Data Pipelines
- `alpha/data/ingestion/soccer_stats.py` — Understat EPL stats pipeline (rolling xG, goals, shots). Keep for xG/goals features; FBref adds on top.
- `alpha/data/ingestion/football_data_client.py` — FootballDataClient for fixtures and odds. H2H and form lookup will use the `/matches` endpoint of this same client.
- `alpha/data/ingestion/soccer_injuries.py` — ESPN soccer injury pipeline (currently used for `goals_lost` adjustment in XGBoost features).
- `alpha/data/ingestion/wc_elo.py` — WC Elo reader (`load_elo_ratings()`). Club Elo reader mirrors this pattern.

### WC Milestone Reference (v1.1 + v1.2)
- `.planning/phases/05-data-foundation/` — Data foundation pattern (cache namespaces, reader modules)
- `.planning/phases/06-match-model/` — Elo-logistic implementation decisions
- `.planning/phases/07-sgp-builder/` — SGP builder pattern with stage-aware correlation

### External Docs / APIs
- football-data.org `/competitions/{id}/matches` — historical match results for H2H + form
- clubelo.com — Club Elo ratings download (CSV or per-team API)
- soccerdata library (FBref scraper) — set piece and style metrics
- No external specs beyond code — requirements fully captured in decisions above

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `WCMatchModel._elo_logistic()` in `wc_model.py` — the Elo win probability formula. The UCL Elo model reuses this directly.
- `WCMatchModel._draw_prob()` in `wc_model.py` — dynamic draw algorithm (Phase 8). Reuse for UCL draw probability estimation.
- `SoccerModel._credibility_filter()` — market divergence dampener. Keep for XGBoost EPL layer; UCL Elo model doesn't need it (Elo is already independent).
- `SoccerModel._remove_vig_3way()` — 3-way vig removal. Reuse for UCL Elo model to compare against market.
- `NBAStatsCache` pattern in `nba_stats_cache.py` — 6h TTL caching. Club Elo ratings should use same pattern.
- `EVCalculator` in `alpha/engines/sports/ev_calculator.py` — used by all models for EV computation. No changes needed.

### Established Patterns
- **Model separation**: WC games never route through `SoccerModel`. Same principle: UCL games route through `UCLEloModel`, EPL games through XGBoost-based `SoccerModel`. Guard in `soccer_scanner.py`.
- **Fallback chain**: `XGBoost → market_implied` (current). New chain: EPL = `XGBoost → market_implied`, UCL = `UCLEloModel → market_implied`.
- **Feature schema helper**: `mlb_model.py` and `nba_model.py` both have a `_build_game_features()` method. The EPL XGBoost feature builder follows the same private method pattern.
- **Test pattern**: Unit tests mock stat fetchers and assert on probabilities, not data. Same for new pipelines.

### Integration Points
- `soccer_scanner.py` — add `league_key` routing branch: `if game.get('league') == 'ucl': use UCLEloModel`
- `SoccerSGPBuilder.build()` — add draw leg type alongside existing `PropLeg` dataclass
- `football_data_client.py` — extend `FootballDataClient` with `fetch_team_matches(team_id, n=5)` for H2H/form

</code_context>

<specifics>
## Specific Ideas

- **Form signal:** W/D/L record encoded as points (W=3, D=1, L=0) over last 5. Also track goal difference.
- **H2H signal:** Win/draw/loss record for home team in last 5 meetings specifically at home. Captures venue-specific patterns.
- **UCL Elo source:** clubelo.com publishes CSV downloads by date. Fetch once at scanner startup, cache to `data/.soccer_cache/club_elo.csv` with daily TTL.
- **Draw legs in parlay:** Annotate with `*DRAW RISK*` similar to WC's `*ELO EDGE*` annotation, so user can identify draw legs at a glance.

</specifics>

<deferred>
## Deferred Ideas

- **validate_soccer_picks.py** — accuracy grader for soccer predictions. User noted this is desirable but deferred. Should be added after the first soccer season of predictions to have data to grade.
- **European game fatigue flag** — midweek UCL/EL game before weekend EPL match. User chose days-rest only for now; can be added as a binary feature later.
- **Soccer player props** — no free odds source; requires paid API tier. Deferred indefinitely.
- **Travel distance fatigue** — geocoded stadium distances for away trips. Too complex for this milestone; deferred.
- **In-play model** — deferred (pregame only for this milestone).

</deferred>

---

*Milestone: v1.4 — Soccer Mode Upgrade*
*Context gathered: 2026-06-19*
