# Phase 25: Evaluation Framework - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — discuss skipped)

<domain>
## Phase Boundary

Set up the chronological backtest infrastructure — expanding-window splits, Brier/log-loss/accuracy/A-grade metrics, isotonic calibration on validation fold — so every subsequent phase can be measured against the Elo-only baseline.

This phase delivers:
- `scripts/wc_eval.py` — chronological expanding-window backtest runner
- `alpha/engines/sports/wc_calibration.py` — isotonic regression calibration
- Promotion gate function: PASS/FAIL comparison of two model result dicts
- Baseline metrics for current Elo-only WCMatchModel

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — pure infrastructure phase.

Key constraints from ROADMAP:
- EVAL-01: Chronological expanding-window backtest — features frozen at pre-kickoff timestamp
- EVAL-02: Metrics: accuracy, multiclass Brier, log loss, calibration curves, A-grade hit rate (top-class >= 0.65)
- EVAL-03: Isotonic regression calibration fitted on validation fold only (never post-hoc on full dataset)
- EVAL-04: Promotion gate: player-aware model must beat Elo-only on both Brier + log loss; guard against trivial pass for identical models

Historical data source: Use embedded WC 2018 + 2022 match results (128 matches available from StatsBomb via wc_stats.py cache, or construct synthetic historical dict from known results). If StatsBomb data unavailable, construct minimal test dataset of real WC 2018/2022 group + knockout results.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `alpha/engines/sports/wc_model.py` — `WCMatchModel.predict(game)` returns `win_prob`, `draw_prob`, `loss_prob`
- `alpha/data/ingestion/wc_elo.py` — `load_wc_elo_ratings()`, `get_elo_rating()`
- `data/wc_priors.json` — current Elo ratings for WC 2026 teams
- `alpha/engines/sports/ev_calculator.py` — `EVCalculator.implied_prob()`, `american_to_decimal()`

### Established Patterns
- Test structure: `tests/unit/engines/test_wc_model.py` shows unit test patterns
- Scripts: `scripts/wc_scanner.py` shows standalone script patterns
- All sports engines are standalone — no shared base class
- Metrics: scikit-learn for Brier score, log loss is available in venv

### Integration Points
- `wc_eval.py` must NOT import wc_scanner or any live-data fetcher (backtest only)
- Calibration must be kept separate from prediction — `WCMatchModel.predict()` unchanged
- Phase 26+ will call the eval framework to compare model versions

</code_context>

<specifics>
## Specific Ideas

- Historical match data: embed a hardcoded dict of WC 2018 + 2022 group stage results (team names, scores, stage) — avoids any network calls in the backtest
- Expanding window: chronological split by tournament year (2018 train → 2022 test, then 2018+2022 train → 2026 live)
- A-grade: top predicted class probability >= 0.65 AND prediction is correct
- Calibration plot: can be a simple logged output (not matplotlib figure) to keep script CI-friendly

</specifics>

<deferred>
## Deferred Ideas

- Live odds integration in backtest (Phase 32 concern)
- Automated promotion gate in CI pipeline (post-milestone)

</deferred>
