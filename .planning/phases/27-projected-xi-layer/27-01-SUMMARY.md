# Phase 27-01 Summary: Projected XI Layer

**Status:** Complete
**Date:** 2026-06-24

## What was built

- `alpha/engines/sports/wc_lineup.py` — `LineupProjector` + `PlayerInfo` + `LineupFeatures` + `build_mock_squad()`
- `tests/unit/engines/test_wc_lineup.py` — 16 tests covering all 4 LINEUP requirements
- `scripts/wc_eval.py` — extended with lineup projector demo section

## Key design decisions

- Line scores use SUM (not mean) — 11-player line scores higher than 10-player (LINEUP-02 ✅)
- Absence impact = max(0, value − replacement_value) — non-negative (LINEUP-03 ✅)
- Uncertainty band = std dev of p_start values; HIGH if >0.35 (LINEUP-04 ✅)
- Continuity modifier = −0.05 per GK/CB change from reference lineup (LINEUP-05 ✅)
- API designed for Phase 30 to plug in real FBref/Understat player values

## Requirements coverage

| Req | Description | Status |
|-----|-------------|--------|
| LINEUP-01 | Starter probability per player from squad data | ✅ |
| LINEUP-02 | Line scores by SUM not mean | ✅ |
| LINEUP-03 | Replacement-adjusted absence impact | ✅ |
| LINEUP-04 | Uncertainty variance when probs low | ✅ |
| LINEUP-05 | Back-line and midfield continuity modifiers | ✅ |
