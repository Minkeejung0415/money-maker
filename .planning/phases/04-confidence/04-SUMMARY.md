# Phase 4 — Confidence Tuning: Summary

## Changes Implemented

### CONF-01: Blowout Gate (prop_model.py)
- Added `team_win_prob: float = 0.50` parameter to `predict_prop`.
- When `team_win_prob < 0.30`, HIGH confidence is downgraded to MEDIUM.
- Rationale: heavy underdog games have unpredictable minutes distribution;
  starters may rest, bench players may get garbage time, inflating or
  deflating stats unpredictably.

### CONF-02: Low-Line Skepticism (prop_model.py)
- After confidence classification, if `model_prob > 0.85` AND
  `line < projection - 1.5 * std`, confidence is capped at MEDIUM.
- Rationale: a line that is far below the model's projection combined
  with near-certainty from the model suggests the sportsbook knows
  something the model doesn't (injury news, load management, etc.).

### CONF-03: 60% Confidence Floor (prop_model.py + sgp_scanner.py)
- In `predict_prop`, if `model_prob < 0.60`, confidence is forced to LOW.
- In `sgp_scanner.py`, the default `--min-prob` is already 0.60,
  ensuring sub-60% legs are excluded from SGP combos.
- In single-prop display, these legs appear with the LOW label.

### Test Adjustments
- `test_confidence_high_when_large_gap` updated: line changed from 20.0 to
  25.0 to avoid triggering CONF-02 (the test was using a synthetically
  extreme line-projection gap that is exactly the scenario CONF-02 guards
  against).

## Tests
- 493/493 pass (including adjusted test)

## Per-Stat Hit Rates
Unchanged from Phase 3 (confidence tuning affects pick selection, not projections):

| Stat | Hit Rate |
|------|----------|
| pts  | 52.1%    |
| reb  | 45.2%    |
| ast  | 50.7%    |
| 3pm  | 46.6%    |
| **overall** | **48.6%** |
