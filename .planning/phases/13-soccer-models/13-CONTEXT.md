# Phase 13: Soccer Model Upgrade — Context

**Gathered:** 2026-06-19
**Milestone:** v1.4 — Soccer Mode Upgrade
**Status:** Ready for planning

<domain>
## Phase Boundary

Two model deliverables:
1. **EPL XGBoost retrain** — retrain with 5 new feature categories (form, H2H, days-rest, set pieces, existing xG) on 3 seasons EPL data (~1,140 games)
2. **UCLEloModel** — new Club Elo-logistic model for UCL, mirrors WCMatchModel pattern

This phase consumes the data modules built in Phase 12 and produces trained model artifacts + a new `UCLEloModel` class. No scanner changes yet (Phase 14).

</domain>

<decisions>
## Implementation Decisions

### D-08 EPL model
Retrain XGBoost classifier on 3 seasons of EPL historical data. Feature schema:
- Rolling xG for/against (from Understat via soccer_stats.py) — existing features
- Form: `home_form_points`, `away_form_points`, `home_form_goal_diff`, `away_form_goal_diff`
- H2H: `h2h_home_win_rate` (last 5 meetings)
- Fatigue: `home_rest_days`, `away_rest_days`
- Set pieces: `home_corners_pg`, `away_corners_pg`, `home_aerial_pct`, `away_aerial_pct`

Same train/calibrate/test chronological split pattern as MLB v1.3 (mlb_training.py / train_mlb_moneyline.py).
Calibration: Platt scaling preferred (same as NBA + MLB).
Benchmark against market-implied baseline (Brier score).

### D-09 UCL model
`UCLEloModel` class in `alpha/engines/sports/ucl_model.py`.
- Uses Club Elo ratings from Phase 12's `load_club_elo_ratings()`
- Elo-logistic win probability formula: identical to `WCMatchModel.predict()` (no home boost for UCL — all group stage games at neutral or away venues across Europe)
  - Actually UCL DOES have home/away. Add +40 Elo home advantage (half of standard 80pt since UCL is elite clubs)
- Dynamic draw probability: reuse `_draw_prob()` from wc_model.py
- No knockout mode needed (UCL scanner is group stage only for now)
- Produces `win_prob`, `draw_prob`, `loss_prob`, `elo_edge` fields matching WCMatchModel output schema

### D-10 Architecture separation
- `SoccerModel` (EPL XGBoost) stays in `alpha/engines/sports/soccer_model.py` — update to load new artifact
- `UCLEloModel` is a new class in `alpha/engines/sports/ucl_model.py`
- `soccer_scanner.py` routing: `if game.get('league') == 'ucl': UCLEloModel` (Phase 14 wires this)

### Claude's Discretion
- Exact train/val/test date split for EPL historical data
- Feature normalization / scaling approach for XGBoost
- Whether to serialize UCLEloModel as pkl (probably not — it's runtime-computed from Elo ratings, no pkl needed)
- XGBoost hyperparameters (n_estimators, max_depth, learning_rate — start from NBA/MLB priors)

</decisions>

<canonical_refs>
## Canonical References

- `alpha/engines/sports/wc_model.py` — WCMatchModel: mirror for UCLEloModel (Elo formula, draw algorithm, elo_edge flag)
- `alpha/engines/sports/soccer_model.py` — current SoccerModel (XGBoost + market-implied fallback) — extend, don't replace
- `alpha/engines/sports/mlb_model.py` — artifact loading pattern (schema gate, feature_names check)
- `alpha/engines/sports/mlb_training.py` — build_pregame_rows() / feature_vector() pattern for EPL feature builder
- `scripts/train_mlb_moneyline.py` — training script pattern (chronological split, candidate comparison, Platt calibration, artifact save)
- `alpha/data/ingestion/wc_elo.py` — Elo reader pattern for `load_club_elo_ratings()`

</canonical_refs>

<code_context>
## Existing Code Insights

- `WCMatchModel._draw_prob()` uses `_WC_BASE_DRAW=0.32` and `_WC_DRAW_SCALE=500.0`. UCL draw rate is similar (~25-28%) — may want slightly lower base draw.
- `EVCalculator` in `ev_calculator.py` already handles 3-way market (remove_vig_3way). No changes needed.
- EPL historical data fetch: football-data.org has 3+ seasons of EPL results accessible through existing FootballDataClient
- ProphitBet pkl (`alpha/models/soccer_win_probability.pkl`) — check if it exists or if we're starting fresh

</code_context>

<specifics>
## Specific Notes

- UCL home advantage: +40 Elo points (conservative; standard is +80 but UCL involves elite clubs where home edge is reduced)
- EPL model artifact: save to `alpha/models/epl_win_probability.pkl` + `.meta.json` (same bundle schema as mlb_win_probability)
- Include `model_name` field in output: `"epl_xgboost_v1"` for EPL, `"ucl_elo_logistic"` for UCL
- EPL Brier baseline: market-implied (home-rate baseline typically ~0.248 for EPL)

</specifics>

<deferred>
## Deferred

- UCL XGBoost (per-team UCL game count too sparse — Elo-logistic is correct choice)
- validate_soccer_picks.py accuracy grader (deferred to after first season of data)

</deferred>
