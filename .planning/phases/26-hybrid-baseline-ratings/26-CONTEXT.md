# Phase 26: Hybrid Baseline Ratings - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — discuss skipped)

<domain>
## Phase Boundary

Replace the pure Elo-logistic backbone with a hybrid baseline that combines:
- Elo-like long-run rating (updated match-by-match on all competitive internationals)
- xG attack state and xG defense state (EWMA of non-penalty xG for/against)
- FIFA SUM rating as an additive feature
- Host-country advantage as a distinct feature (2026 host countries: US, Canada, Mexico)
- Confederation interaction feature for cross-confederation neutral-site matchups

The Phase 25 evaluation framework measures all improvements. wc_scanner.py must continue working unchanged.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — infrastructure phase.

Key constraints from ROADMAP:
- BASELINE-01: Hybrid Elo-like long-run rating updated match-by-match on competitive internationals
- BASELINE-02: xG attack state and xG defense state as EWMA of non-penalty xG for/against, configurable half-life
- BASELINE-03: FIFA SUM rating as feature alongside Elo and xG states
- BASELINE-04: Host-country advantage as distinct feature; all 2026 venues neutral except host cities
- BASELINE-05: Confederation interaction feature for cross-confederation neutral-site matchups

Architecture: New class `WCTeamRatings` that exposes elo, xg_attack, xg_defense, fifa_sum, host_flag, confederation_interaction for any team/date. Lives in `alpha/engines/sports/wc_ratings.py`. Does NOT modify existing wc_model.py — keep WCMatchModel for the scanner.

Data source for historical match results: Use `data/wc_historical_matches.py` (Phase 25) plus additional competitive international results (friendly flag if needed). For xG data: use the StatsBomb-derived cache in `.wc_cache/wc_stats.pkl` as per-team averages; sequential match-by-match xG is not available — use tournament-level averages as EWMA seeds.

FIFA SUM: Embed static FIFA rankings (June 2026) as a dict. Sum = home_rank + away_rank treated as a feature (lower is better).

Host countries 2026: "United States", "Mexico", "Canada" — these get host_flag=1.

Promotion gate: must beat Phase 25 Elo-only baseline (Brier=0.5181, LogLoss=0.8805) on 2022 holdout.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `data/wc_historical_matches.py` — 128 match results with `get_matches(year, stage)` (Phase 25)
- `alpha/engines/sports/wc_calibration.py` — evaluate_model(), promotion_gate(), WCIsotonicCalibrator (Phase 25)
- `alpha/engines/sports/wc_model.py` — WCMatchModel (keep unchanged for scanner)
- `alpha/data/ingestion/wc_elo.py` — load_wc_elo_ratings() for current Elo ratings
- `data/wc_priors.json` — 48 teams with current Elo ratings
- `data/.wc_cache/wc_stats.pkl` — per-team xG averages (avg_xG, defense_score)
- `scripts/wc_eval.py` — backtest runner; extend to also run hybrid model

### Established Patterns
- All sports engines are standalone classes with no shared base
- Model predict(game: dict) → mutates and returns game dict
- Static data embedded as Python modules (see wc_historical_matches.py pattern)

### Integration Points
- `WCTeamRatings` is NOT wired into wc_scanner.py yet (that's Phase 32 full integration)
- `wc_eval.py` extended to benchmark hybrid model vs Elo-only baseline
- Phase 25 promotion gate used to confirm improvement

</code_context>

<specifics>
## Specific Ideas

- FIFA SUM: Use the June 2026 FIFA rankings for the 48 WC 2026 qualified teams. Embed as dict in a new `data/wc_fifa_rankings.py`.
- EWMA half-life: default 5 matches (λ = 0.5^(1/5) ≈ 0.871). Configurable via constructor arg.
- Confederation map: embed in wc_ratings.py as dict {team: confederation}. Confederations: UEFA, CONMEBOL, CONCACAF, CAF, AFC, OFC.
- Sequential update: WCTeamRatings loads historical match data from wc_historical_matches and updates ratings in chronological order within the constructor.

</specifics>

<deferred>
## Deferred Ideas

- Wiring hybrid ratings into wc_scanner.py live predictions (Phase 32)
- Live xG data per match (StatsBomb 2026 mid-tournament data not available)
- Uncertainty bounds on EWMA estimates

</deferred>
