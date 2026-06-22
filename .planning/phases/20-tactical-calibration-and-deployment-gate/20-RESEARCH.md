# Phase 20 Research

## Diagnosis

The v1.6 comparison uses seven manually chosen weights and applies them on top of Elo, recent form, and team attack/defense priors. Several tactical inputs, especially chance creation, possession, and defensive block, correlate with team strength already represented by those baselines. The layer therefore risks double counting. Full-match statistics are also affected by score state, red cards, opponent strength, and match context.

The 35-match backtest is useful as a holdout but is too small to estimate seven effects reliably. Raw accuracy is particularly unstable because a small probability movement can cross 0.50 without meaningfully improving the forecast.

## Recommended Design

1. Build historical rows from completed international fixtures and ESPN summaries, deduplicated by event ID. Each profile is reconstructed as of the target kickoff from prior matches only.
2. Prefer competitive senior internationals. Record competition, neutral venue, red-card availability, sample depth, and data-quality exclusions so domain shifts are visible.
3. Treat the baseline forecast as fixed. Optimize only a bounded tactical residual with L2 regularization rather than retraining the World Cup model.
4. Use expanding-window folds for model selection, reserve at least 50 later pre-tournament matches for chronological validation, and keep the sealed 2026 World Cup audit out of all fitting, tuning, and threshold selection.
5. Fit an outcome residual against 1X2 log loss and a coherent home/away goal-rate residual against scoreline likelihood. Totals and BTTS remain derived from that scoreline model.
6. Compare four variants: no tactics, current fixed weights, learned residual, and baseline-only recalibration. The recalibration control reveals whether apparent gains come from tactics or merely correcting baseline confidence.
7. Estimate paired metric deltas with 10,000 deterministic match-level bootstrap replicates, two-sided 95% intervals, and Holm correction across the three market families. Promotion requires an absolute improvement of at least 0.002 in both Brier and log loss against no tactics and baseline-only recalibration, with the corrected upper confidence bound below zero for both comparisons.

## Deployment Gates

- First run a coverage audit over candidate ESPN competitions, event counts, required summary fields, card status, and usable profile depth. Do not begin fitting unless the expected gates are attainable.
- Minimum 200 eligible development matches, 50 later pre-tournament chronological validation matches, and 30 sealed 2026 World Cup external-audit matches. Failure blocks promotion rather than weakening a threshold.
- Primary gate per market: Brier and log loss each improve by at least 0.002 against both no tactics and baseline-only recalibration, and both corrected 95% upper confidence bounds for paired deltas are below zero.
- Secondary diagnostics: accuracy, calibration slope/intercept, reliability bins, maximum adjustment, and subgroup results by strength gap and competition type.
- 1X2, Over/Under 2.5, and BTTS receive separate single-market pass/fail states. An SGP tactical-joint gate passes only when all constituent market families are approved on the same scoreline artifact; otherwise the entire combination uses the baseline distribution.

## Existing Tools

The project already includes NumPy, SciPy, pandas, scikit-learn, and joblib. No dependency is required. Existing `wc_tactics.py`, `wc_tactical_matchup.py`, `wc_model.py`, and `validate_wc_tactics.py` provide ingestion, explainable components, bounded integration, and chronological evaluation surfaces.

## Risks

- ESPN endpoints are undocumented and historical summary coverage may be uneven. Cache immutable event summaries and generate explicit coverage reports.
- International friendlies differ from World Cup matches. Prefer competitive fixtures and report subgroup metrics rather than silently pooling everything.
- A small holdout cannot prove a narrow gain. The system must be allowed to conclude that no tactical market is ready.
