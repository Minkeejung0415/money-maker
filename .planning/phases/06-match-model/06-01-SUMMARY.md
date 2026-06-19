---
plan: 06-01
phase: 06-match-model
status: complete
requirements_addressed:
  - MODEL-01
  - MODEL-02
  - MODEL-03
  - MODEL-04
commits:
  - 26abc53  # test(06-01): add failing WCMatchModel tests
  - 8aa35f2  # feat(06-01): implement WCMatchModel Elo-logistic match model
---

# Plan 06-01 Summary: WCMatchModel Elo-Logistic Match Model

## What Was Built

New file `alpha/engines/sports/wc_model.py` — standalone Elo-logistic W/D/L model for WC 2026:

- **`WCMatchModel(min_edge=0.04)`** — constructor loads Elo ratings (raises FileNotFoundError if missing) and StatsBomb stats (graceful fallback to `{}` on FileNotFoundError)
- **`predict(game: dict) -> dict`** — appends 9 fields to game dict; raises `ValueError` if `game["league"] != "wc"`
- **`evaluate_bet(game: dict) -> dict | None`** — returns game dict if `win_prob` has EV > `min_edge` vs market odds, else `None`
- **`evaluate_batch(games: list[dict]) -> list[dict | None]`** — batch wrapper

### Module-level constants exported
```python
_WC_DRAW_RATE: float = 0.25
_XG_ELO_SCALE: float = 35.0
_XG_ADJ_CAP: float = 200.0
KNOCKOUT_STAGES: frozenset[str] = frozenset({"LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "THIRD_PLACE", "FINAL"})
```

### Elo-logistic formula
```
elo_diff = elo_home - elo_away          # neutral venue — NO +100 home boost
elo_adj  = elo_diff + xg_diff * 35.0   # StatsBomb xG modifier (capped ±200)
p_home_2way = 1 / (1 + 10^(-elo_adj/400))

Group stage:  p_draw=0.25, p_home=p_home_2way*0.75, p_away=(1-p_home_2way)*0.75
Knockout:     p_draw=0.0,  p_home=p_home_2way,       p_away=1-p_home_2way
```

## Key Contracts Delivered

`WCMatchModel().predict(game) -> dict`:
```python
{
    # ... original game fields ...
    "win_prob":   float,  # home team W probability (or Win-to-Advance in knockout)
    "draw_prob":  float,  # 0.0 in knockout rounds
    "loss_prob":  float,  # away team W probability
    "elo_edge":   bool,   # |win_prob - market_implied| > 0.05
    "knockout":   bool,   # True if stage in KNOCKOUT_STAGES
    "model_name": str,    # "wc_elo_logistic"
    "elo_diff":   float,  # adjusted Elo diff used (post-StatsBomb modifier)
    "home_elo":   int,    # home team raw Elo (debug, discretion choice)
    "away_elo":   int,    # away team raw Elo (debug, discretion choice)
}
```

## Test Results

- **18/18 new tests passing** in `tests/unit/engines/test_wc_model.py`
- **609/609 full suite passing** (up from 591; 0 regressions)

## Verification Evidence

```
grep -c "soccer_model" alpha/engines/sports/wc_model.py  →  0
python -c "from alpha.engines.sports.wc_model import _WC_DRAW_RATE, KNOCKOUT_STAGES; ..."  →  "constants ok"
```

All 4 MODEL requirements satisfied:
- **MODEL-01**: `predict()` outputs W/D/L via Elo-logistic, neutral venue (no +100 home boost)
- **MODEL-02**: `knockout=True` when `stage in KNOCKOUT_STAGES` → `draw_prob=0.0`, Win-to-Advance only
- **MODEL-03**: `stage` field from game dict consumed; `knockout` bool added to output
- **MODEL-04**: `elo_edge=True` when `|win_prob - market_implied| > 0.05`

## Discretion Choices Made

Per CONTEXT.md "Claude's Discretion" section:
1. **`home_elo` and `away_elo` stored in output dict** — useful for Phase 7 SGP builder debugging
2. **`logger.info()` on successful init** — reports Elo rating count and team stats count
3. **`evaluate_batch()` returns `list[dict | None]`** — `None` for no-edge games (consistent with evaluate_bet return type)
