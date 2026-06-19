---
plan: 07-01
phase: 07-sgp-builder
status: complete
requirements_addressed:
  - SGP-01
  - SGP-02
commits:
  - b09877f  # test(07-01): add failing WCSGPBuilder tests
  - 9766e84  # feat(07-01): implement WCSGPBuilder classic parlay builder
---

# Plan 07-01 Summary: WCSGPBuilder Classic Parlay Builder

## What Was Built

New file `alpha/engines/sports/wc_sgp_builder.py` — WC-specific classic parlay builder:

- **`WCSGPBuilder(bankroll=10_000.0, min_edge=0.05, max_legs=4)`**
- **`build(ml_games: list[dict], top_n: int = 5) -> list[ParlayCombination]`** — generates, scores, and ranks classic parlay combos from WCMatchModel-enriched game dicts
- **`_best_wc_leg(game: dict) -> dict | None`** — extracts Win/Advance leg from enriched game dict using `game["win_prob"]`; never generates Draw legs (SGP-02)
- **`_build_classic_parlay(ml_games: list[dict]) -> list[ParlayCombination]`** — iterates n-leg combinations (2 to max_legs), multiplies probabilities and odds

## Key Contracts Delivered

- Reuses `ParlayCombination` and `SGPMode` from `soccer_sgp_builder.py` (no duplication)
- SGP-02: Draw legs are NEVER generated — `_best_wc_leg()` only returns Win/Advance legs
- Each leg dict carries `elo_edge`, `home_elo`, and `knockout` fields for downstream scanner display

## Test Results

- **11/11 new tests passing** in `tests/unit/engines/test_wc_sgp_builder.py`
- 620/620 full suite (pre-scanner) — no regressions
