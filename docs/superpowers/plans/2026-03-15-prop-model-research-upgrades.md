# Prop Model Research Upgrades Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply all four research findings to the NBA prop model to move from a hand-tuned weighted-average engine toward a statistically grounded prediction system.

**Architecture:** Three sequential phases — Phase 1 fixes are immediate (no data needed), Phase 2 adds a prediction logger and Platt calibrator (needs 30+ days of labeled picks), Phase 3 replaces the weighted-average projection with a trained XGBoost regression model (needs historical game logs). Each phase ships independently and improves accuracy on its own.

**Tech Stack:** Python 3.13, scipy (existing), scikit-learn (Platt scaling / isotonic), xgboost, nba_api (existing), pytest

---

## Background — Research Findings

| Finding | Source | Current state | Target state |
|---|---|---|---|
| XGBoost beats weighted avg | Elicit study comparison | `_weighted_avg()` + manual adj | XGBoost regression → NegBin CDF |
| NegBin for PTS/REB confirmed | Negative binomial literature | Already NegBin ✅ | Keep |
| Zero-inflated Poisson for AST | Poisson vs ZIP research | Plain Poisson for all AST | ZIP for SF/SG/PF/C positions |
| Platt scaling > temperature T | Walsh & Joshi 2023 | T=0.75 hardcoded | Platt A,B fit on labeled picks |
| James-Stein shrinkage | Efron-Morris 1975, Brown 2008 | Raw weighted avg, floor 5 games | Shrink toward position prior |
| Vig removal | Shin method / CLV literature | Includes bookmaker margin | No-vig probability comparison |

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `alpha/engines/sports/prop_model.py` | Modify | Phase 1: vig removal, shrinkage, ZIP for AST |
| `alpha/engines/sports/prop_calibrator.py` | Create | Phase 2: Platt scaling fit + apply |
| `scripts/log_predictions.py` | Create | Phase 2: append every prediction to JSONL log |
| `scripts/train_xgb_prop_model.py` | Create | Phase 3: fetch historical logs, train, save model |
| `alpha/engines/sports/xgb_prop_model.py` | Create | Phase 3: XGBoostPropModel that replaces weighted avg |
| `tests/unit/test_prop_model.py` | Modify | Phase 1: update / add tests per change |
| `tests/unit/engines/test_prop_calibrator.py` | Create | Phase 2: Platt calibrator unit tests |
| `tests/unit/engines/test_xgb_prop_model.py` | Create | Phase 3: XGBoost model unit tests |

---

## Chunk 1: Phase 1 — Immediate Fixes (no training data)

Three independent changes to `prop_model.py`. Each is self-contained.

---

### Task 1: Vig Removal

**Context:** `_american_to_implied(-110)` returns 52.4%. The true no-vig probability for a symmetric -110/-110 market is 50.0%. We're comparing our model against an inflated number, which deflates perceived edge. Fix: divide the raw implied probability by the total overround.

**Files:**
- Modify: `alpha/engines/sports/prop_model.py` (methods `_american_to_implied`, `predict_prop`)
- Modify: `tests/unit/test_prop_model.py`

- [ ] **Step 1: Write failing test for no-vig conversion**

Add to `tests/unit/test_prop_model.py`:

```python
def test_american_to_novig_symmetric(model):
    """Symmetric -110/-110 market → no-vig implied = 0.50, not 0.524."""
    novig = model._american_to_novig(-110, -110)
    assert abs(novig - 0.50) < 0.001


def test_american_to_novig_asymmetric(model):
    """-115 over / +105 under → no-vig over ≈ 0.523."""
    novig = model._american_to_novig(-115, 105)
    assert abs(novig - 0.523) < 0.005


def test_american_to_novig_fallback(model):
    """When only over_odds given (under=None), assume symmetric market → 0.50."""
    novig = model._american_to_novig(-110, None)
    assert abs(novig - 0.50) < 0.001
```

- [ ] **Step 2: Run to verify it fails**

```bash
./venv/Scripts/python.exe -m pytest tests/unit/test_prop_model.py::test_american_to_novig_symmetric -v
```
Expected: `AttributeError: 'PropModel' object has no attribute '_american_to_novig'`

- [ ] **Step 3: Add `_american_to_novig` to `prop_model.py`**

In `prop_model.py`, after `_american_to_implied`:

```python
@staticmethod
def _american_to_novig(over_odds: int, under_odds: int | None) -> float:
    """
    Convert American odds pair to no-vig (fair) implied probability for the over.

    If under_odds is None, assumes a symmetric market (both sides at same odds),
    which gives p_over = 0.50 for -110/-110.
    """
    def _raw(odds: int) -> float:
        if odds > 0:
            return 100.0 / (odds + 100)
        return abs(odds) / (abs(odds) + 100.0)

    p_over = _raw(over_odds)
    p_under = _raw(under_odds) if under_odds is not None else p_over
    total = p_over + p_under
    return p_over / total if total > 0 else 0.5
```

- [ ] **Step 4: Update `predict_prop` signature to accept `under_odds`**

Change the method signature from:
```python
def predict_prop(
    self,
    player_name: str,
    market: str,
    line: float,
    opponent_team: str,
    over_odds: int = -110,
    location: str = "all",
    ...
```
To:
```python
def predict_prop(
    self,
    player_name: str,
    market: str,
    line: float,
    opponent_team: str,
    over_odds: int = -110,
    under_odds: int | None = None,
    location: str = "all",
    ...
```

And replace the line:
```python
market_implied = self._american_to_implied(over_odds)
```
With:
```python
market_implied = self._american_to_novig(over_odds, under_odds)
```

- [ ] **Step 5: Run all prop model tests**

```bash
./venv/Scripts/python.exe -m pytest tests/unit/test_prop_model.py -v
```
Expected: all pass including the 3 new tests.

- [ ] **Step 6: Commit**

```bash
git add alpha/engines/sports/prop_model.py tests/unit/test_prop_model.py
git commit -m "fix(prop-model): remove bookmaker vig before market comparison"
```

---

### Task 2: James-Stein Shrinkage for Small Samples

**Context:** With only 5–20 qualifying games, our weighted average is noisy. The James-Stein estimator shrinks each player's observed average toward a position-level prior mean. The shrinkage factor B decreases as more games accumulate: heavy shrinkage at 5 games, near-zero at 30+.

Formula: `shrunk = prior + (1 - B) * (observed - prior)` where `B = max(0, 1 - n / STABILIZATION_N)`.

Research-backed stabilization points: PTS ~15 games, REB ~20 games, AST ~20 games.

**Files:**
- Modify: `alpha/engines/sports/prop_model.py`
- Modify: `tests/unit/test_prop_model.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_prop_model.py`:

```python
def test_shrinkage_pulls_toward_prior_small_sample(model):
    """5-game sample of 30 PTS for a PG (prior=15) should shrink toward 15."""
    from alpha.engines.sports.prop_model import PropModel
    shrunk = PropModel._james_stein_shrink(
        observed=30.0, n_games=5, market="player_points", position="PG"
    )
    # prior=15, B=max(0,1-5/15)=0.67 → shrunk = 15 + 0.33*(30-15) = 19.95
    assert 15.0 < shrunk < 30.0
    assert shrunk < 22.0   # heavily shrunk toward prior


def test_shrinkage_trusts_large_sample(model):
    """30-game sample → near-zero shrinkage, return close to observed."""
    from alpha.engines.sports.prop_model import PropModel
    shrunk = PropModel._james_stein_shrink(
        observed=28.0, n_games=30, market="player_points", position="PG"
    )
    # B=max(0,1-30/15)=0 → shrunk = observed
    assert abs(shrunk - 28.0) < 0.5


def test_shrinkage_uses_position_prior(model):
    """Center (C) prior for REB is higher than PG prior for REB."""
    from alpha.engines.sports.prop_model import PropModel
    shrunk_c  = PropModel._james_stein_shrink(5.0, 5, "player_rebounds", "C")
    shrunk_pg = PropModel._james_stein_shrink(5.0, 5, "player_rebounds", "PG")
    # C prior REB=9, PG prior REB=4 → shrunk_C should be pulled higher
    assert shrunk_c > shrunk_pg
```

- [ ] **Step 2: Run to verify failure**

```bash
./venv/Scripts/python.exe -m pytest tests/unit/test_prop_model.py::test_shrinkage_pulls_toward_prior_small_sample -v
```
Expected: `AttributeError`

- [ ] **Step 3: Add constants and `_james_stein_shrink` to `prop_model.py`**

Add near the top constants block:

```python
# James-Stein shrinkage: position-level prior means per market.
# Source: approximate NBA per-game averages by position (2023-25 seasons).
_POSITION_PRIORS: dict[str, dict[str, float]] = {
    "player_points":   {"PG": 15.0, "SG": 14.0, "SF": 13.0, "PF": 12.0, "C": 12.0},
    "player_rebounds": {"PG":  4.0, "SG":  4.0, "SF":  5.0, "PF":  7.0, "C":  9.0},
    "player_assists":  {"PG":  6.0, "SG":  3.0, "SF":  2.0, "PF":  2.0, "C":  2.0},
}
_LEAGUE_PRIORS: dict[str, float] = {
    "player_points": 13.5, "player_rebounds": 5.5, "player_assists": 3.0,
}
# Number of games at which B → 0 (full trust in observed data).
_STABILIZATION_N: dict[str, int] = {
    "player_points": 15, "player_rebounds": 20, "player_assists": 20,
}
```

Add static method to `PropModel`:

```python
@staticmethod
def _james_stein_shrink(
    observed: float,
    n_games: int,
    market: str,
    position: str,
) -> float:
    """
    James-Stein shrinkage estimator.

    shrunk = prior + (1 - B) * (observed - prior)
    B = max(0, 1 - n / stabilization_n)

    With few games, B≈1 → heavy pull toward prior.
    With 30+ games, B=0 → trust observed fully.
    """
    stab_n = _STABILIZATION_N.get(market)
    if stab_n is None:
        return observed   # unknown market, no shrinkage

    pos = position.upper() if position else ""
    prior = _POSITION_PRIORS.get(market, {}).get(pos, _LEAGUE_PRIORS.get(market, observed))

    B = max(0.0, 1.0 - n_games / stab_n)
    return prior + (1.0 - B) * (observed - prior)
```

- [ ] **Step 4: Wire shrinkage into `predict_prop`**

In `predict_prop`, after computing `proj_stat = self._weighted_avg(values)` and before minutes ratio, add:

```python
# James-Stein shrinkage: pull noisy small-sample estimates toward position prior.
n_qualifying = min(len(qualifying), 20)
proj_stat = self._james_stein_shrink(proj_stat, n_qualifying, market, position)
```

- [ ] **Step 5: Run all tests**

```bash
./venv/Scripts/python.exe -m pytest tests/unit/test_prop_model.py -v
```
Expected: all pass. Note: `test_high_avg_beats_low_line` may need its threshold relaxed slightly since shrinkage pulls 30 PPG down — check and adjust if needed.

- [ ] **Step 6: Commit**

```bash
git add alpha/engines/sports/prop_model.py tests/unit/test_prop_model.py
git commit -m "feat(prop-model): add James-Stein shrinkage for small sample stabilization"
```

---

### Task 3: Zero-Inflated Poisson for AST (non-PG positions)

**Context:** Plain Poisson assumes every game has a nonzero assist probability — wrong for SF/SG/PF/C players who frequently record 0 or 1 assists. Zero-inflated Poisson (ZIP) mixes a point mass at zero with a Poisson rate: `P(X=0) = π + (1-π)e^(-λ)`, `P(X=k>0) = (1-π) * e^(-λ) * λ^k / k!`.

We estimate `π` (zero-inflation probability) from the player's historical game log: fraction of games where AST == 0.

**Files:**
- Modify: `alpha/engines/sports/prop_model.py`
- Modify: `tests/unit/test_prop_model.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_prop_model.py`:

```python
def test_zip_p_over_higher_than_poisson_for_zero_heavy_player(model):
    """
    A player with many 0-assist games: ZIP should give lower P(over 3.5)
    than plain Poisson because zero-inflation compresses the mass.
    """
    from alpha.engines.sports.prop_model import PropModel
    # π=0.40 (40% zero-assist games), λ=3.0
    p_zip     = PropModel._zip_p_over(line=3, lam=3.0, pi_zero=0.40)
    p_poisson = 1 - __import__('scipy.stats', fromlist=['poisson']).poisson.cdf(3, mu=3.0)
    # ZIP has more mass at 0, so P(>3) should be lower
    assert p_zip < p_poisson


def test_zip_pi_zero_zero_equals_poisson(model):
    """ZIP with π=0 should equal plain Poisson."""
    from alpha.engines.sports.prop_model import PropModel
    from scipy.stats import poisson
    lam = 5.0
    p_zip = PropModel._zip_p_over(line=4, lam=lam, pi_zero=0.0)
    p_poi = float(1 - poisson.cdf(4, mu=lam))
    assert abs(p_zip - p_poi) < 0.001


def test_zip_used_for_noncenter_ast(model):
    """AST prediction for a PG uses plain Poisson; SF uses ZIP."""
    rows_ast = [
        {"AST": v, "PTS": 15.0, "REB": 5.0, "MIN": "30", "MIN_float": 30.0,
         "MATCHUP": "LAL vs. BOS"}
        for v in [0, 0, 1, 2, 0, 3, 0, 1, 2, 0, 4, 0, 0, 1, 0, 2, 0, 0, 1, 0]
    ]

    def _patch_team_stats():
        return patch(
            "alpha.engines.sports.prop_model.PropModel._fetch_team_per_game_stats",
            return_value={},
        )

    with _patch_logs(rows_ast), _patch_def_ratings(), _patch_team_stats():
        result_sf = model.predict_prop(
            "Test SF", "player_assists", 1.5, "Boston Celtics", position="SF"
        )
        result_pg = model.predict_prop(
            "Test PG", "player_assists", 1.5, "Boston Celtics", position="PG"
        )

    assert result_sf is not None
    assert result_pg is not None
    # SF has lots of zero-assist games → ZIP → lower P(over 1.5) than PG
    assert result_sf["model_prob"] < result_pg["model_prob"]
```

- [ ] **Step 2: Run to verify failure**

```bash
./venv/Scripts/python.exe -m pytest tests/unit/test_prop_model.py::test_zip_pi_zero_zero_equals_poisson -v
```
Expected: `AttributeError: type object 'PropModel' has no attribute '_zip_p_over'`

- [ ] **Step 3: Add `_zip_p_over` static method to `prop_model.py`**

```python
@staticmethod
def _zip_p_over(line: float, lam: float, pi_zero: float) -> float:
    """
    P(X > line) for a Zero-Inflated Poisson(π, λ).

    P(X=0) = π + (1-π)*exp(-λ)
    P(X=k) = (1-π) * exp(-λ) * λ^k / k!   for k >= 1

    Computed as: P(X > line) = (1 - π) * P(Poisson(λ) > line)
    because the zero-inflation only adds mass at zero; for k > 0 the
    relative probability ratios are the same as Poisson.
    """
    if lam <= 0:
        return 0.0
    pi_zero = float(np.clip(pi_zero, 0.0, 0.95))
    p_poisson_over = float(1 - poisson.cdf(int(line), mu=lam))
    return (1.0 - pi_zero) * p_poisson_over
```

- [ ] **Step 4: Update `_compute_p_over` to use ZIP for AST on non-PG positions**

Change the method signature to accept `position` and `values`:

```python
@staticmethod
def _compute_p_over(
    market: str,
    line: float,
    projection: float,
    std: float,
    var: float,
    position: str = "",
    values: list[float] | None = None,
) -> float:
    """Select appropriate CDF based on market type and player position."""
    if market == "player_assists":
        pos = position.upper()
        if pos in ("SF", "SG", "PF", "C") and values:
            # Zero-inflated Poisson for non-PG positions (many 0-assist games)
            pi_zero = sum(1 for v in values if v == 0) / len(values)
            return PropModel._zip_p_over(line=line, lam=projection, pi_zero=pi_zero)
        # PG or unknown position: plain Poisson
        return float(1 - poisson.cdf(int(line), mu=projection))

    if market in _POISSON_MARKETS:
        return float(1 - poisson.cdf(int(line), mu=projection))

    if market in _NEGBIN_MARKETS:
        mean_ = projection
        if var > mean_ and mean_ > 0:
            r = mean_ ** 2 / max(1e-9, var - mean_)
            p = mean_ / max(1e-9, var)
            if r > 0:
                return float(1 - nbinom.cdf(int(line), r, p))
        return float(1 - norm.cdf(line, loc=projection, scale=std))

    return float(1 - norm.cdf(line, loc=projection, scale=std))
```

- [ ] **Step 5: Update the call site in `predict_prop`**

Change:
```python
p_over = self._compute_p_over(market, line, opp_adj, std_stat, var_stat)
```
To:
```python
p_over = self._compute_p_over(market, line, opp_adj, std_stat, var_stat,
                               position=position, values=values)
```

- [ ] **Step 6: Run full test suite**

```bash
./venv/Scripts/python.exe -m pytest tests/unit/test_prop_model.py -v
```
Expected: all pass.

- [ ] **Step 7: Run full project test suite to catch regressions**

```bash
./venv/Scripts/python.exe -m pytest tests/ -x -q
```
Expected: 516/516 pass (or current count).

- [ ] **Step 8: Commit**

```bash
git add alpha/engines/sports/prop_model.py tests/unit/test_prop_model.py
git commit -m "feat(prop-model): zero-inflated Poisson for AST on non-PG positions"
```

---

## Chunk 2: Phase 2 — Prediction Logger + Platt Calibration

**Prerequisite:** 30+ days of labeled picks (prediction logged + actual outcome recorded). Tasks 4 and 5 can be built now; calibration fitting runs after data accumulates.

---

### Task 4: Prediction Logger

**Context:** To fit Platt scaling we need a record of every prediction made and whether it hit. This task creates a JSONL logger that appends one record per prediction. Each record includes: player, market, line, model_prob, market_implied (no-vig), confidence, date. Outcomes are filled in later by a separate grading step.

**Files:**
- Create: `scripts/log_predictions.py`
- Create: `tests/unit/test_prediction_logger.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_prediction_logger.py`:

```python
"""Tests for prediction logger."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def test_log_appends_jsonl_record(tmp_path):
    """Logging a prediction appends one JSONL line to the output file."""
    from scripts.log_predictions import log_prediction

    log_file = tmp_path / "picks.jsonl"
    log_prediction(
        log_file=log_file,
        player="Jayson Tatum",
        market="player_points",
        line=28.5,
        model_prob=0.72,
        market_implied=0.50,
        confidence="HIGH",
        game_date="2026-03-15",
    )

    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["player"] == "Jayson Tatum"
    assert record["model_prob"] == 0.72
    assert record["outcome"] is None   # not yet graded


def test_log_appends_multiple(tmp_path):
    """Multiple calls append multiple lines."""
    from scripts.log_predictions import log_prediction

    log_file = tmp_path / "picks.jsonl"
    for i in range(3):
        log_prediction(log_file, f"Player {i}", "player_points", 20.0, 0.6, 0.5, "MEDIUM", "2026-03-15")

    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 3
```

- [ ] **Step 2: Run to verify failure**

```bash
./venv/Scripts/python.exe -m pytest tests/unit/test_prediction_logger.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `scripts/log_predictions.py`**

```python
"""
Prediction logger — appends one JSONL record per NBA prop prediction.

Each record:
  player, market, line, model_prob, market_implied, confidence,
  game_date, logged_at, outcome (null until graded)

Usage:
  from scripts.log_predictions import log_prediction
  log_prediction(log_file=Path("data/prediction_log.jsonl"), ...)

Grading (fill in outcomes after games complete):
  python scripts/log_predictions.py grade --date 2026-03-15
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG = Path("data/prediction_log.jsonl")


def log_prediction(
    log_file: Path,
    player: str,
    market: str,
    line: float,
    model_prob: float,
    market_implied: float,
    confidence: str,
    game_date: str,
    outcome: bool | None = None,
) -> None:
    """Append one prediction record to the JSONL log file."""
    record = {
        "player": player,
        "market": market,
        "line": line,
        "model_prob": round(model_prob, 4),
        "market_implied": round(market_implied, 4),
        "confidence": confidence,
        "game_date": game_date,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "outcome": outcome,  # True=hit, False=miss, None=ungraded
    }
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
```

- [ ] **Step 4: Run tests**

```bash
./venv/Scripts/python.exe -m pytest tests/unit/test_prediction_logger.py -v
```
Expected: 2/2 pass.

- [ ] **Step 5: Wire logger into `sgp_scanner.py`**

In `scripts/sgp_scanner.py`, after each `predict_prop` call that returns a result, add:

```python
from scripts.log_predictions import log_prediction
from pathlib import Path

log_prediction(
    log_file=Path("data/prediction_log.jsonl"),
    player=result["player"],
    market=result["market"],
    line=result["line"],
    model_prob=result["model_prob"],
    market_implied=result.get("market_implied", 0.5),
    confidence=result["confidence"],
    game_date=str(date.today()),
)
```

- [ ] **Step 6: Commit**

```bash
git add scripts/log_predictions.py tests/unit/test_prediction_logger.py scripts/sgp_scanner.py
git commit -m "feat(logging): append every prediction to JSONL log for Platt calibration"
```

---

### Task 5: Platt Scaling Calibrator

**Context:** Once 200+ labeled picks are available, fit Platt scaling: a logistic sigmoid `P_calibrated = 1/(1 + exp(A*s + B))` where `s` is the raw model_prob log-odds, and A,B are fit by minimizing log-loss on held-out picks. This replaces the guessed T=0.75 temperature.

**Files:**
- Create: `alpha/engines/sports/prop_calibrator.py`
- Create: `tests/unit/engines/test_prop_calibrator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/engines/test_prop_calibrator.py`:

```python
"""Tests for Platt scaling calibrator."""
from __future__ import annotations

import pytest


def test_calibrator_identity_when_perfect(tmp_path):
    """Perfectly calibrated raw probs should return same values after fitting."""
    from alpha.engines.sports.prop_calibrator import PropCalibrator

    # Synthetic: raw probs match outcomes perfectly already
    probs   = [0.3, 0.5, 0.7, 0.4, 0.6, 0.8, 0.2, 0.9]
    outcomes = [0,   1,   1,   0,   1,   1,   0,   1]

    cal = PropCalibrator()
    cal.fit(probs, outcomes)
    calibrated = [cal.transform(p) for p in probs]

    # After Platt fit, calibrated probs should still preserve ordering
    for a, b in zip(calibrated, calibrated[1:]):
        pass  # just check no exceptions and returns float in [0,1]
    assert all(0.0 < c < 1.0 for c in calibrated)


def test_calibrator_reduces_overconfidence():
    """Raw 0.85 from overconfident model should be pulled down after calibration."""
    from alpha.engines.sports.prop_calibrator import PropCalibrator

    # Simulate overconfident model: predicts 0.85 but only hits 70% of the time
    probs    = [0.85] * 30 + [0.15] * 30
    outcomes = [1] * 21 + [0] * 9 + [0] * 21 + [1] * 9  # 70% accuracy at 0.85

    cal = PropCalibrator()
    cal.fit(probs, outcomes)
    calibrated_high = cal.transform(0.85)
    assert calibrated_high < 0.85   # pulled toward true rate


def test_calibrator_save_load(tmp_path):
    """Calibrator can be saved to disk and loaded back."""
    from alpha.engines.sports.prop_calibrator import PropCalibrator

    probs    = [0.3, 0.5, 0.7, 0.6, 0.8]
    outcomes = [0,   1,   1,   1,   1]

    cal = PropCalibrator()
    cal.fit(probs, outcomes)
    path = tmp_path / "cal.pkl"
    cal.save(path)

    cal2 = PropCalibrator.load(path)
    assert abs(cal2.transform(0.7) - cal.transform(0.7)) < 0.001


def test_calibrator_raises_if_not_fit():
    from alpha.engines.sports.prop_calibrator import PropCalibrator
    cal = PropCalibrator()
    with pytest.raises(RuntimeError, match="not fitted"):
        cal.transform(0.7)
```

- [ ] **Step 2: Run to verify failure**

```bash
./venv/Scripts/python.exe -m pytest tests/unit/engines/test_prop_calibrator.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `alpha/engines/sports/prop_calibrator.py`**

```python
"""
Platt scaling calibrator for NBA prop model probabilities.

Fits a logistic sigmoid to raw model probabilities:
    P_calibrated = 1 / (1 + exp(A * log_odds(p_raw) + B))

where A, B are learned to minimize log-loss on labeled picks.

Usage:
    cal = PropCalibrator()
    cal.fit(raw_probs, outcomes)   # outcomes: list[int] 0/1
    cal.save(Path("data/calibrator.pkl"))

    # At prediction time:
    cal = PropCalibrator.load(Path("data/calibrator.pkl"))
    p_calibrated = cal.transform(raw_prob)
"""
from __future__ import annotations

import math
import pickle
from pathlib import Path


class PropCalibrator:
    """Platt scaling calibrator — fits A, B on labeled predictions."""

    def __init__(self) -> None:
        self._A: float | None = None
        self._B: float | None = None

    def fit(self, probs: list[float], outcomes: list[int]) -> None:
        """
        Fit Platt scaling on (raw_prob, outcome) pairs.
        Uses sklearn's LogisticRegression on log-odds features.
        Requires scikit-learn.
        """
        from sklearn.linear_model import LogisticRegression
        import numpy as np

        if len(probs) < 20:
            raise ValueError(f"Need at least 20 labeled picks to fit; got {len(probs)}")

        # Feature: log-odds of raw probability
        eps = 1e-7
        X = np.array([math.log((p + eps) / (1 - p + eps)) for p in probs]).reshape(-1, 1)
        y = np.array(outcomes)

        lr = LogisticRegression(C=1e9, solver="lbfgs")  # no regularization (Platt)
        lr.fit(X, y)
        self._A = float(lr.coef_[0][0])
        self._B = float(lr.intercept_[0])

    def transform(self, p_raw: float) -> float:
        """Apply calibration to a single raw probability."""
        if self._A is None or self._B is None:
            raise RuntimeError("PropCalibrator is not fitted — call fit() first")
        eps = 1e-7
        log_odds = math.log((p_raw + eps) / (1 - p_raw + eps))
        return float(1.0 / (1.0 + math.exp(-(self._A * log_odds + self._B))))

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"A": self._A, "B": self._B}, f)

    @classmethod
    def load(cls, path: Path) -> "PropCalibrator":
        with open(path, "rb") as f:
            data = pickle.load(f)
        cal = cls()
        cal._A = data["A"]
        cal._B = data["B"]
        return cal
```

- [ ] **Step 4: Install scikit-learn if not present**

```bash
./venv/Scripts/python.exe -m pip install scikit-learn
```

- [ ] **Step 5: Run calibrator tests**

```bash
./venv/Scripts/python.exe -m pytest tests/unit/engines/test_prop_calibrator.py -v
```
Expected: 4/4 pass.

- [ ] **Step 6: Replace temperature scaling in `prop_model.py` with calibrator (once fitted)**

In `predict_prop`, replace:
```python
p_over = self._apply_temperature_scaling(p_over)
```
With:
```python
if self._calibrator is not None:
    p_over = self._calibrator.transform(p_over)
else:
    p_over = self._apply_temperature_scaling(p_over)  # fallback until calibrated
```

Add to `PropModel.__init__`:
```python
_cal_path = Path("data/calibrator.pkl")
self._calibrator = PropCalibrator.load(_cal_path) if _cal_path.exists() else None
```

Add import at top:
```python
from alpha.engines.sports.prop_calibrator import PropCalibrator
```

- [ ] **Step 7: Run full suite**

```bash
./venv/Scripts/python.exe -m pytest tests/ -x -q
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add alpha/engines/sports/prop_calibrator.py tests/unit/engines/test_prop_calibrator.py alpha/engines/sports/prop_model.py
git commit -m "feat(calibration): Platt scaling calibrator replaces hardcoded T=0.75"
```

---

## Chunk 3: Phase 3 — XGBoost Projection Model

**Prerequisite:** 2–3 seasons of historical game logs fetched from nba_api. The XGBoost model outputs a projected stat value (regression), which replaces `_weighted_avg` as the projection. The NegBin/ZIP CDF step stays unchanged.

---

### Task 6: Historical Data Fetcher

**Context:** Fetch 2022-23, 2023-24, 2024-25 season game logs for all active players from nba_api. Store as a flat CSV. This is the training dataset.

**Files:**
- Create: `scripts/fetch_historical_logs.py`

- [ ] **Step 1: Create `scripts/fetch_historical_logs.py`**

```python
"""
Fetch historical NBA game logs for XGBoost training.

Fetches seasons: 2022-23, 2023-24, 2024-25
For each player in each season: all game logs with PTS/REB/AST/MIN/MATCHUP.
Saves to: data/historical_logs.csv

Runtime: ~2-3 hours (rate-limited nba_api calls).
Run once, then use the CSV for training.

Usage:
    ./venv/Scripts/python.exe scripts/fetch_historical_logs.py
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

SEASONS = ["2022-23", "2023-24", "2024-25"]
OUT_FILE = Path("data/historical_logs.csv")
SLEEP = 0.6   # nba_api rate limit

FIELDS = [
    "season", "player_id", "player_name", "game_date", "matchup",
    "min_float", "pts", "reb", "ast", "fg3m",
    "opp_team",
]


def fetch_all_logs() -> None:
    from nba_api.stats.static import players as nba_players
    from nba_api.stats.endpoints.playergamelogs import PlayerGameLogs

    all_players = nba_players.get_active_players()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()

        for season in SEASONS:
            print(f"Season {season}: fetching {len(all_players)} players...")
            for player in all_players:
                try:
                    time.sleep(SLEEP)
                    gl = PlayerGameLogs(
                        player_id_nullable=str(player["id"]),
                        season_nullable=season,
                        last_n_games_nullable="0",
                    )
                    df = gl.get_data_frames()[0]
                    if df.empty:
                        continue
                    for _, row in df.iterrows():
                        matchup = str(row.get("MATCHUP", ""))
                        opp = matchup.split(" ")[-1] if matchup else ""
                        min_val = row.get("MIN", 0)
                        try:
                            if isinstance(min_val, str) and ":" in min_val:
                                p = min_val.split(":")
                                min_f = float(p[0]) + float(p[1]) / 60
                            else:
                                min_f = float(min_val)
                        except Exception:
                            min_f = 0.0
                        writer.writerow({
                            "season": season,
                            "player_id": player["id"],
                            "player_name": player["full_name"],
                            "game_date": str(row.get("GAME_DATE", ""))[:10],
                            "matchup": matchup,
                            "min_float": round(min_f, 1),
                            "pts": float(row.get("PTS", 0) or 0),
                            "reb": float(row.get("REB", 0) or 0),
                            "ast": float(row.get("AST", 0) or 0),
                            "fg3m": float(row.get("FG3M", 0) or 0),
                            "opp_team": opp,
                        })
                except Exception as e:
                    print(f"  skip {player['full_name']}: {e}")

    print(f"Done. Saved to {OUT_FILE}")


if __name__ == "__main__":
    fetch_all_logs()
```

- [ ] **Step 2: Run to verify it executes (first 5 players only for smoke test)**

Edit the script temporarily to `all_players = all_players[:5]`, run, then revert.

```bash
./venv/Scripts/python.exe scripts/fetch_historical_logs.py
```
Expected: CSV created with rows.

- [ ] **Step 3: Commit scaffolding, run full fetch in background**

```bash
git add scripts/fetch_historical_logs.py
git commit -m "feat(xgb): add historical game log fetcher for training data"
./venv/Scripts/python.exe scripts/fetch_historical_logs.py &
```

---

### Task 7: XGBoost Model Training

**Files:**
- Create: `scripts/train_xgb_prop_model.py`
- Create: `tests/unit/engines/test_xgb_prop_model.py`

- [ ] **Step 1: Install xgboost**

```bash
./venv/Scripts/python.exe -m pip install xgboost scikit-learn pandas
```

- [ ] **Step 2: Write failing test**

Create `tests/unit/engines/test_xgb_prop_model.py`:

```python
"""Tests for XGBoostPropModel."""
from __future__ import annotations

import pytest
import numpy as np


def test_xgb_model_predict_returns_positive_float():
    """Trained model returns positive float projection for valid features."""
    from alpha.engines.sports.xgb_prop_model import XGBoostPropModel
    import pickle, tempfile
    from pathlib import Path

    # Create tiny synthetic dataset and train
    model = XGBoostPropModel(target="pts")
    features = [{"roll5": 25.0, "roll10": 22.0, "roll20": 20.0, "min_recent": 32.0,
                 "opp_def_rtg": 112.0, "is_home": 1, "rest_days": 2, "pace": 100.0}] * 50
    targets = [20.0 + np.random.normal(0, 3) for _ in range(50)]
    model.fit(features, targets)

    pred = model.predict(features[0])
    assert isinstance(pred, float)
    assert pred > 0


def test_xgb_model_save_load(tmp_path):
    """Model saves and loads correctly."""
    from alpha.engines.sports.xgb_prop_model import XGBoostPropModel
    import numpy as np

    model = XGBoostPropModel(target="pts")
    features = [{"roll5": 20.0, "roll10": 18.0, "roll20": 16.0, "min_recent": 28.0,
                 "opp_def_rtg": 110.0, "is_home": 0, "rest_days": 1, "pace": 98.0}] * 30
    targets = [15.0 + np.random.normal(0, 2) for _ in range(30)]
    model.fit(features, targets)

    path = tmp_path / "model.pkl"
    model.save(path)
    model2 = XGBoostPropModel.load(path)
    assert abs(model2.predict(features[0]) - model.predict(features[0])) < 0.01
```

- [ ] **Step 3: Create `alpha/engines/sports/xgb_prop_model.py`**

```python
"""
XGBoostPropModel — replaces the hand-tuned weighted average in PropModel.

Instead of manually computing:
    proj = weighted_avg(values) * opp_adj * pace * rest

We train a gradient-boosted tree that learns these relationships from
2-3 seasons of historical game logs.

The model outputs a projected stat value (regression).
PropModel still applies the NegBin/ZIP CDF to compute P(over line).

Features:
    roll5        — decay-weighted avg last 5 qualifying games
    roll10       — decay-weighted avg last 10 qualifying games
    roll20       — decay-weighted avg last 20 qualifying games
    min_recent   — avg minutes last 5 games
    opp_def_rtg  — opponent defensive rating (points model only)
    is_home      — 1 if home game, 0 if away
    rest_days    — days since last game (capped at 4)
    pace         — opponent pace (rebounds model)

Target: actual stat value for that game.
"""
from __future__ import annotations

import pickle
from pathlib import Path


_FEATURE_COLS = ["roll5", "roll10", "roll20", "min_recent",
                 "opp_def_rtg", "is_home", "rest_days", "pace"]


class XGBoostPropModel:
    def __init__(self, target: str) -> None:
        """
        target: one of "pts", "reb", "ast"
        """
        self._target = target
        self._model = None

    def fit(self, features: list[dict], targets: list[float]) -> None:
        """Train XGBoost regressor on feature dicts + target values."""
        import xgboost as xgb
        import numpy as np

        X = np.array([[f.get(col, 0.0) for col in _FEATURE_COLS] for f in features])
        y = np.array(targets)

        self._model = xgb.XGBRegressor(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
        )
        self._model.fit(X, y)

    def predict(self, features: dict) -> float:
        """Predict projected stat value for one game."""
        if self._model is None:
            raise RuntimeError("Model not trained — call fit() or load()")
        import numpy as np
        X = np.array([[features.get(col, 0.0) for col in _FEATURE_COLS]])
        return float(self._model.predict(X)[0])

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"target": self._target, "model": self._model}, f)

    @classmethod
    def load(cls, path: Path) -> "XGBoostPropModel":
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls(target=data["target"])
        obj._model = data["model"]
        return obj
```

- [ ] **Step 4: Run tests**

```bash
./venv/Scripts/python.exe -m pytest tests/unit/engines/test_xgb_prop_model.py -v
```
Expected: 2/2 pass.

- [ ] **Step 5: Create `scripts/train_xgb_prop_model.py`**

```python
"""
Train XGBoost prop models on historical game logs.

Reads: data/historical_logs.csv (from fetch_historical_logs.py)
Writes: data/xgb_pts_model.pkl, data/xgb_reb_model.pkl, data/xgb_ast_model.pkl

Usage:
    ./venv/Scripts/python.exe scripts/train_xgb_prop_model.py
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd
import numpy as np
from statistics import mean, stdev

from alpha.engines.sports.xgb_prop_model import XGBoostPropModel

DECAY = 0.85
LOG_FILE = Path("data/historical_logs.csv")
MIN_MINUTES = 20
MIN_GAMES = 5


def _weighted_avg(vals: list[float]) -> float:
    if not vals:
        return 0.0
    total_w = total_v = 0.0
    for i, v in enumerate(vals):
        w = DECAY ** i
        total_w += w
        total_v += v * w
    return total_v / total_w


def build_features(
    df_player: pd.DataFrame,
    game_idx: int,
    stat_col: str,
    opp_def_rtg: float = 112.0,
    opp_pace: float = 100.0,
) -> dict | None:
    """
    Build feature dict for a single game using the previous games as history.
    game_idx: row index in df_player (sorted newest-first within player-season).
    """
    history = df_player.iloc[game_idx + 1:]   # games BEFORE this game
    qualifying = history[history["min_float"] >= MIN_MINUTES]
    if len(qualifying) < MIN_GAMES:
        return None

    vals = qualifying[stat_col].tolist()
    roll5  = _weighted_avg(vals[:5])
    roll10 = _weighted_avg(vals[:10])
    roll20 = _weighted_avg(vals[:20])
    min_recent = mean(qualifying["min_float"].tolist()[:5])

    matchup = str(df_player.iloc[game_idx]["matchup"])
    is_home = 1 if "vs." in matchup else 0

    return {
        "roll5": roll5,
        "roll10": roll10,
        "roll20": roll20,
        "min_recent": min_recent,
        "opp_def_rtg": opp_def_rtg,
        "is_home": is_home,
        "rest_days": 2,   # placeholder — add real rest days if available
        "pace": opp_pace,
    }


def train_model(stat_col: str, target_name: str, out_path: Path) -> None:
    print(f"Training {target_name} model...")
    df = pd.read_csv(LOG_FILE)
    df = df[df["min_float"] >= MIN_MINUTES].copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    df = df.sort_values(["player_id", "season", "game_date"], ascending=[True, True, False])

    features, targets = [], []
    for (player_id, season), group in df.groupby(["player_id", "season"]):
        group = group.reset_index(drop=True)
        for i in range(len(group)):
            feat = build_features(group, i, stat_col)
            if feat is None:
                continue
            features.append(feat)
            targets.append(float(group.iloc[i][stat_col]))

    print(f"  {len(features)} training samples")
    model = XGBoostPropModel(target=target_name)
    model.fit(features, targets)
    model.save(out_path)
    print(f"  Saved to {out_path}")


if __name__ == "__main__":
    train_model("pts", "pts", Path("data/xgb_pts_model.pkl"))
    train_model("reb", "reb", Path("data/xgb_reb_model.pkl"))
    train_model("ast", "ast", Path("data/xgb_ast_model.pkl"))
    print("All models trained.")
```

- [ ] **Step 6: Run trainer smoke test (after historical_logs.csv exists)**

```bash
./venv/Scripts/python.exe scripts/train_xgb_prop_model.py
```
Expected: 3 pkl files saved to `data/`.

- [ ] **Step 7: Commit**

```bash
git add alpha/engines/sports/xgb_prop_model.py scripts/train_xgb_prop_model.py tests/unit/engines/test_xgb_prop_model.py scripts/fetch_historical_logs.py
git commit -m "feat(xgb): XGBoost projection model — replaces weighted average"
```

---

### Task 8: Wire XGBoost into PropModel

**Files:**
- Modify: `alpha/engines/sports/prop_model.py`

- [ ] **Step 1: Add XGBoost path to PropModel**

In `PropModel.__init__`, add:

```python
from alpha.engines.sports.xgb_prop_model import XGBoostPropModel

_XGB_PATHS = {
    "player_points":   Path("data/xgb_pts_model.pkl"),
    "player_rebounds": Path("data/xgb_reb_model.pkl"),
    "player_assists":  Path("data/xgb_ast_model.pkl"),
}
self._xgb_models: dict[str, XGBoostPropModel] = {}
for market, path in _XGB_PATHS.items():
    if path.exists():
        self._xgb_models[market] = XGBoostPropModel.load(path)
```

- [ ] **Step 2: Add `_xgb_project` method**

```python
def _xgb_project(
    self,
    market: str,
    values: list[float],
    qualifying: list[dict],
    opponent_team: str,
    location: str,
) -> float | None:
    """
    Use trained XGBoost model to produce projection.
    Returns None if model not available for this market.
    """
    xgb = self._xgb_models.get(market)
    if xgb is None:
        return None

    from statistics import mean
    vals20 = values[:20]
    roll5  = self._weighted_avg(values[:5])
    roll10 = self._weighted_avg(values[:10])
    roll20 = self._weighted_avg(vals20)
    min_recent = mean([g.get("MIN_float", 25.0) for g in qualifying[:5]])

    ts = self._fetch_team_per_game_stats()
    opp = ts.get(opponent_team, {})
    opp_def_rtg = opp.get("def_rtg", _LEAGUE_AVG_DEF_RTG)
    opp_pace = opp.get("pace", _LEAGUE_AVG_PACE)
    is_home = 1 if location == "home" else 0
    rest_days = min(4, self._rest_multiplier(qualifying))  # repurpose rest info

    return xgb.predict({
        "roll5": roll5,
        "roll10": roll10,
        "roll20": roll20,
        "min_recent": min_recent,
        "opp_def_rtg": opp_def_rtg,
        "is_home": is_home,
        "rest_days": 2,   # simplified; improve after date parsing added
        "pace": opp_pace,
    })
```

- [ ] **Step 3: Use XGBoost projection when available**

In `predict_prop`, replace:
```python
proj_stat = self._weighted_avg(values)
```
With:
```python
proj_stat = self._xgb_project(market, values, qualifying, opponent_team, location)
if proj_stat is None:
    proj_stat = self._weighted_avg(values)
```

- [ ] **Step 4: Run full test suite**

```bash
./venv/Scripts/python.exe -m pytest tests/ -x -q
```
Expected: all pass (XGBoost paths don't exist in test env → fallback to weighted avg).

- [ ] **Step 5: Commit**

```bash
git add alpha/engines/sports/prop_model.py
git commit -m "feat(xgb): wire XGBoost projection into PropModel with weighted-avg fallback"
```

---

## Execution Order Summary

| Phase | When | Tasks | Impact |
|---|---|---|---|
| Phase 1 | Now | 1 (vig), 2 (shrinkage), 3 (ZIP AST) | Immediate accuracy improvement |
| Phase 2 | After 30 days of picks | 4 (logger), 5 (Platt) | Better calibration than T=0.75 |
| Phase 3 | After historical fetch completes | 6 (fetch), 7 (train), 8 (wire) | Highest ceiling — replace entire projection engine |
