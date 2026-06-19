# Phase 8: Dynamic Draw Algorithm - Context

**Gathered:** 2026-06-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace the flat `_WC_DRAW_RATE = 0.25` constant in `wc_model.py` with a dynamic draw probability function. The function uses exponential decay keyed on |elo_adj| so that closely-matched teams retain a high draw probability and heavily-mismatched teams get a low draw probability. Knockout round behavior (p_draw = 0.0) is unchanged.

This phase touches exactly one model file (`alpha/engines/sports/wc_model.py`) and its test file (`tests/unit/engines/test_wc_model.py`). No new data sources, no new files.

</domain>

<decisions>
## Implementation Decisions

### Formula
- Use exponential decay: `p_draw = max(_WC_MIN_DRAW, _WC_BASE_DRAW * exp(-abs(elo_adj) / _WC_DRAW_SCALE))`
- Input variable: `elo_adj` (the post-xG-modifier Elo difference, same value used in win probability) — consistent with how win prob is computed

### Calibration Parameters
- `_WC_BASE_DRAW = 0.32` — max draw rate at Elo difference = 0 (fits historical ~30-33% for closely-matched WC group games)
- `_WC_MIN_DRAW = 0.05` — floor to prevent impossible 0% draw on any group game
- `_WC_DRAW_SCALE = 500.0` — Elo-points scale factor (Δ=500 gives ~12% draw, Δ=750 gives ~7%, which floors to 0.05 for extreme mismatches)

### Expected output at calibration checkpoints
| Δ | p_draw |
|---|--------|
| 0 | 0.320 |
| 100 | 0.262 |
| 300 | 0.176 |
| 500 | 0.118 |
| 750 | max(0.05, 0.071) = 0.071 |

### Named Constants
- Rename `_WC_DRAW_RATE` → `_WC_BASE_DRAW` (= 0.32)
- Add `_WC_MIN_DRAW = 0.05`
- Add `_WC_DRAW_SCALE = 500.0`
- Update docstring for each constant

### Test Updates
- Remove `test_wc_draw_rate_value()` (asserted `_WC_DRAW_RATE == 0.25` — constant no longer exists by that name)
- Add `pytest.mark.parametrize` test covering Δ=0, 100, 300, 500, 750 verifying draw_prob matches expected values (±0.02 tolerance)
- Keep `test_group_stage_has_nonzero_draw()` — still valid
- Keep `test_knockout_suppresses_draw()` — unchanged behavior
- Keep all other tests — zero regressions required

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `alpha/engines/sports/wc_model.py` — only file being modified
- `_WC_DRAW_RATE: float = 0.25` at line 25 — the constant to replace
- `p_draw = _WC_DRAW_RATE` at line 127 — the single assignment to replace with function call
- `import math` will be needed for `math.exp()`

### Established Patterns
- Module-level constants use `_SCREAMING_SNAKE_CASE` with docstrings
- `math` module available in stdlib (no new deps)
- Tests use `pytest.approx()` with `abs=` tolerance for float comparisons
- Tests use `monkeypatch.setattr` to inject fake Elo/stats — existing pattern continues

### Integration Points
- `wc_model.predict()` is the only call site for draw probability
- `evaluate_bet()` and `evaluate_batch()` call `predict()` — no direct changes needed
- Scanner (`scripts/wc_scanner.py`) reads `game["draw_prob"]` from predict output — no changes needed
- SGP builder reads `draw_prob` from game dict — no changes needed

</code_context>

<specifics>
## Specific Ideas

- Formula: `p_draw = max(_WC_MIN_DRAW, _WC_BASE_DRAW * math.exp(-abs(elo_adj) / _WC_DRAW_SCALE))`
- Extract to a private module-level function `_draw_prob(elo_adj: float) -> float` for testability and clarity
- The function should be pure (no side effects, no state access)

</specifics>

<deferred>
## Deferred Ideas

- Live calibration update using WC 2026 actual results feed (post-tournament)
- Separate draw calibration by tournament phase (group stage vs. third-place play-off)

</deferred>
