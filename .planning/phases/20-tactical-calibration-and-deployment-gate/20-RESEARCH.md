# Phase 20 Research

## Diagnosis

The v1.6 comparison uses seven manually chosen weights and applies them on top of Elo, recent form, and team attack/defense priors. Several tactical inputs, especially chance creation, possession, and defensive block, correlate with team strength already represented by those baselines. The layer therefore risks double counting. Full-match statistics are also affected by score state, red cards, opponent strength, and match context.

The 35-match backtest is useful as a holdout but is too small to estimate seven effects reliably. Raw accuracy is particularly unstable because a small probability movement can cross 0.50 without meaningfully improving the forecast.

## Recommended Design

1. Build historical rows from completed international fixtures and ESPN summaries, deduplicated by event ID. Each profile is reconstructed as of the target kickoff from prior matches only.
2. Prefer competitive senior internationals. Record competition, neutral venue, red-card availability, sample depth, and data-quality exclusions so domain shifts are visible.
3. Treat the baseline forecast as fixed. Optimize only a bounded tactical residual with L2 regularization rather than retraining the World Cup model.
4. Use expanding-window folds for model selection and keep 2026 World Cup matches out of all fitting and tuning.
5. Fit an outcome residual against 1X2 log loss and a coherent home/away goal-rate residual against scoreline likelihood. Totals and BTTS remain derived from that scoreline model.
6. Compare four variants: no tactics, current fixed weights, learned residual, and baseline-only recalibration. The recalibration control reveals whether apparent gains come from tactics or merely correcting baseline confidence.
7. Estimate paired metric deltas with match-level bootstrap intervals. Promotion requires sufficient coverage, a positive probability-quality result, and no material regression in the companion metric.

## Deployment Gates

- Minimum 200 eligible development matches and 50 untouched holdout matches. Failure blocks promotion rather than weakening the threshold.
- Primary gate per market: lower holdout Brier score and log loss than the no-tactics baseline, with the configured bootstrap interval excluding a material regression.
- Secondary diagnostics: accuracy, calibration slope/intercept, reliability bins, maximum adjustment, and subgroup results by strength gap and competition type.
- 1X2, Over/Under 2.5, and BTTS receive separate pass/fail states. Totals and BTTS may share a coherent scoreline artifact but not a promotion decision.

## Existing Tools

The project already includes NumPy, SciPy, pandas, scikit-learn, and joblib. No dependency is required. Existing `wc_tactics.py`, `wc_tactical_matchup.py`, `wc_model.py`, and `validate_wc_tactics.py` provide ingestion, explainable components, bounded integration, and chronological evaluation surfaces.

## Risks

- ESPN endpoints are undocumented and historical summary coverage may be uneven. Cache immutable event summaries and generate explicit coverage reports.
- International friendlies differ from World Cup matches. Prefer competitive fixtures and report subgroup metrics rather than silently pooling everything.
- A small holdout cannot prove a narrow gain. The system must be allowed to conclude that no tactical market is ready.
