# Phase 6: Match Model - Pattern Map

**Mapped:** 2026-06-18
**Files analyzed:** 2 (1 new model file, 1 new test file)
**Analogs found:** 2 / 2

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `alpha/engines/sports/wc_model.py` | model/service | request-response | `alpha/engines/sports/soccer_model.py` | exact (same sport vertical, same EVCalculator wiring) |
| `tests/unit/engines/test_wc_model.py` | test | request-response | `tests/unit/engines/test_mlb_model.py` | exact (same monkeypatch-at-init pattern, same evaluate_bet / predict coverage structure) |

---

## Pattern Assignments

### `alpha/engines/sports/wc_model.py` (model, request-response)

**Analog:** `alpha/engines/sports/soccer_model.py`

**Imports pattern** (`soccer_model.py` lines 15-22):
```python
from __future__ import annotations

import logging
from pathlib import Path

from alpha.engines.sports.ev_calculator import EVCalculator

logger = logging.getLogger(__name__)
```

For `wc_model.py` replace the Path import with the two data-layer imports. The `from __future__ import annotations` and logger setup are copied verbatim:
```python
from __future__ import annotations

import logging

from alpha.engines.sports.ev_calculator import EVCalculator
from alpha.data.ingestion.wc_elo import load_wc_elo_ratings, get_elo_rating
from alpha.data.ingestion.wc_stats import get_wc_team_stats

logger = logging.getLogger(__name__)
```

**Module-level constants** (`soccer_model.py` lines 24-25, adapted for WC):
```python
# soccer_model.py pattern (copy structure, change values):
MARKET_BLEND = 0.0
MAX_XGB_CONF = 0.70
```
WC version uses:
```python
_WC_DRAW_RATE: float = 0.25          # group stage historical WC draw frequency
_XG_ELO_SCALE: float = 35.0          # 1 xG/game difference = 35 Elo points
_XG_ADJ_CAP: float = 200.0           # cap adjusted Elo diff at ±200
KNOCKOUT_STAGES = {
    "LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "THIRD_PLACE", "FINAL"
}
```

**Class constructor pattern** (`soccer_model.py` lines 35-46):
```python
class SoccerModel:
    def __init__(self, min_edge: float = 0.04, kelly_fraction: float = 0.25):
        self.ev_calc = EVCalculator(min_edge=min_edge)
        self._kelly_fraction = kelly_fraction

        self._xgb_model = None
        self._xgb_models_loaded: bool = False
        self._injury_impact: dict = {}
        self._injury_loaded: bool = False

        self._load_xgb_models()
```

For `wc_model.py` copy the `EVCalculator` wiring and constructor signature, replace the `_load_xgb_models()` call with Elo/stats loading:
```python
class WCMatchModel:
    def __init__(self, min_edge: float = 0.04):
        self.ev_calc = EVCalculator(min_edge=min_edge)

        # Loaded at init — raises FileNotFoundError if wc_priors.json missing
        self._elo_ratings: dict[str, int] = load_wc_elo_ratings()

        # Graceful catch — model works with Elo-only if StatsBomb cache absent
        try:
            self._wc_stats: dict[str, dict] = get_wc_team_stats()
        except FileNotFoundError:
            logger.warning("WC stats cache not found — running Elo-only mode")
            self._wc_stats = {}
```

**predict() method signature and output-mutation pattern** (`soccer_model.py` lines 52-108):

`soccer_model.py` returns a *new* dict. `wc_model.py` must *mutate the input game dict* (per CONTEXT.md decision). Pattern contrast:
```python
# soccer_model.py — creates new dict (DO NOT copy this for wc_model)
return {
    "home_team": home_team,
    "away_team": away_team,
    "home_win_prob": round(h_prob, 4),
    ...
}

# wc_model.py — append keys to existing game dict (CONTEXT decision)
def predict(self, game: dict) -> dict:
    if game.get("league") != "wc":
        raise ValueError("WC model only accepts WC game dicts (league='wc')")
    # ... compute probs ...
    game["win_prob"] = round(p_home, 4)
    game["draw_prob"] = round(p_draw, 4)
    game["loss_prob"] = round(p_away, 4)
    game["elo_edge"] = elo_edge
    game["knockout"] = knockout
    game["model_name"] = "wc_elo_logistic"
    game["elo_diff"] = round(elo_adj, 2)
    return game
```

**evaluate_bet() pattern** (`soccer_model.py` lines 110-149):
```python
def evaluate_bet(self, game: dict) -> dict:
    probs = self.predict(game)
    home_odds = game.get("home_odds", -110)
    away_odds = game.get("away_odds", -110)

    home_dec = self.ev_calc.american_to_decimal(home_odds)
    away_dec = self.ev_calc.american_to_decimal(away_odds)

    home_ev = self.ev_calc.expected_value(probs["home_win_prob"], home_dec)
    away_ev = self.ev_calc.expected_value(probs["away_win_prob"], away_dec)

    if home_ev >= away_ev and self.ev_calc.has_edge(probs["home_win_prob"], home_dec):
        return { "bet_side": "home", "team": probs["home_team"],
                 "model_prob": probs["home_win_prob"], "decimal_odds": home_dec,
                 "ev": round(home_ev, 4) }
    elif self.ev_calc.has_edge(probs["away_win_prob"], away_dec):
        return { "bet_side": "away", "team": probs["away_team"],
                 "model_prob": probs["away_win_prob"], "decimal_odds": away_dec,
                 "ev": round(away_ev, 4) }
    return { "bet_side": "no_bet", "team": "", "model_prob": 0.0,
             "decimal_odds": 0.0, "ev": max(home_ev, away_ev) }
```

For `wc_model.py` the method signature is `evaluate_bet(self, game: dict) -> dict | None` (returns None when no edge, per CONTEXT.md). Adapt as:
```python
def evaluate_bet(self, game: dict) -> dict | None:
    game = self.predict(game)           # mutates + returns game dict
    home_odds = game.get("home_odds", -110)
    home_dec = self.ev_calc.american_to_decimal(home_odds)
    win_ev = self.ev_calc.expected_value(game["win_prob"], home_dec)
    if self.ev_calc.has_edge(game["win_prob"], home_dec):
        return game                     # caller reads win_prob/elo_edge from dict
    return None
```

**EVCalculator market-implied helper** (`soccer_model.py` lines 158-160, `ev_calculator.py` lines 36-46):
```python
# Pattern: american -> decimal -> implied
def _implied_from_american(self, american_odds: int | float) -> float:
    decimal = self.ev_calc.american_to_decimal(american_odds)
    return self.ev_calc.implied_prob(decimal)
```

For `wc_model.py` elo_edge computation (CONTEXT MODEL-04):
```python
# Inside predict(), after computing p_home:
market_implied = self.ev_calc.implied_prob(
    self.ev_calc.american_to_decimal(game.get("home_odds", -110))
)
elo_edge = abs(p_home - market_implied) > 0.05
```

**Defensive loading pattern** (`soccer_model.py` lines 306-319):
```python
def _load_injuries(self) -> None:
    if self._injury_loaded:
        return
    self._injury_loaded = True
    try:
        from alpha.data.ingestion.soccer_injuries import get_team_injury_impact
        self._injury_impact = get_team_injury_impact()
    except Exception as exc:
        logger.warning("Soccer injury load failed: %s", exc)
        self._injury_impact = {}
```

`wc_model.py` uses the same try/except + `logger.warning` + empty-dict fallback pattern in `__init__` (not deferred to a separate `_load_*` method since stats are static at init time).

**evaluate_batch() pattern** (`soccer_model.py` line 151-152):
```python
def evaluate_batch(self, games: list[dict]) -> list[dict]:
    return [self.evaluate_bet(g) for g in games]
```
Copy verbatim, adjust return type to `list[dict | None]`.

---

### `tests/unit/engines/test_wc_model.py` (test, request-response)

**Analog:** `tests/unit/engines/test_mlb_model.py`
**Secondary analog for monkeypatch style:** `tests/unit/test_wc_priors_loader.py` and `tests/unit/test_wc_stats.py`

**Imports pattern** (`test_mlb_model.py` lines 1-8):
```python
"""Tests for alpha/engines/sports/wc_model.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from alpha.engines.sports.wc_model import WCMatchModel, _WC_DRAW_RATE, KNOCKOUT_STAGES
```

**Mock at init — suppress real file I/O** (`test_mlb_model.py` lines 15-19):
```python
def test_mlb_model_init():
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel()
    assert hasattr(model, "ev_calc")
    assert not model._xgb_models_loaded
```

For `wc_model.py` the init loads Elo ratings directly (no `_load_*` method), so mock the two ingestion functions at their module path:
```python
_FAKE_ELO = {"Brazil": 2100, "Germany": 1980, "France": 2050, "Argentina": 2070}
_FAKE_STATS = {
    "Brazil": {"avg_goals": 2.1, "avg_xG": 1.9, "avg_shots": 14.5, "defense_score": 0.7},
    "Germany": {"avg_goals": 1.8, "avg_xG": 1.7, "avg_shots": 12.0, "defense_score": 0.9},
}

@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(
        "alpha.engines.sports.wc_model.load_wc_elo_ratings",
        lambda: _FAKE_ELO,
    )
    monkeypatch.setattr(
        "alpha.engines.sports.wc_model.get_wc_team_stats",
        lambda: _FAKE_STATS,
    )
    return WCMatchModel()
```

**predict() coverage pattern** (`test_mlb_model.py` lines 61-78, adapted):
```python
def test_predict_returns_required_keys(model):
    game = {"home_team": "Brazil", "away_team": "Germany",
            "home_odds": -130, "away_odds": 110, "league": "wc"}
    result = model.predict(game)
    for key in ("win_prob", "draw_prob", "loss_prob", "elo_edge",
                "knockout", "model_name", "elo_diff"):
        assert key in result

def test_predict_probs_sum_to_one_group_stage(model):
    game = {"home_team": "Brazil", "away_team": "Germany",
            "home_odds": -130, "away_odds": 110, "league": "wc",
            "stage": "GROUP_STAGE"}
    result = model.predict(game)
    total = result["win_prob"] + result["draw_prob"] + result["loss_prob"]
    assert total == pytest.approx(1.0, abs=0.001)

def test_predict_raises_for_non_wc_league(model):
    game = {"home_team": "Chelsea", "away_team": "Arsenal", "league": "epl"}
    with pytest.raises(ValueError, match="league='wc'"):
        model.predict(game)
```

**Knockout stage gate pattern** (new — no analog, but follows same assert structure):
```python
def test_knockout_suppresses_draw(model):
    game = {"home_team": "Brazil", "away_team": "Germany",
            "home_odds": -150, "away_odds": 130,
            "league": "wc", "stage": "QUARTER_FINALS"}
    result = model.predict(game)
    assert result["draw_prob"] == 0.0
    assert result["knockout"] is True

def test_group_stage_has_nonzero_draw(model):
    game = {"home_team": "Brazil", "away_team": "Germany",
            "home_odds": -150, "away_odds": 130,
            "league": "wc", "stage": "GROUP_STAGE"}
    result = model.predict(game)
    assert result["draw_prob"] > 0.0
    assert result["knockout"] is False
```

**FileNotFoundError on missing Elo** (pattern from `test_wc_priors_loader.py` lines 32-40):
```python
def test_init_raises_when_elo_missing(monkeypatch):
    monkeypatch.setattr(
        "alpha.engines.sports.wc_model.load_wc_elo_ratings",
        lambda: (_ for _ in ()).throw(FileNotFoundError("wc_priors.json missing")),
    )
    with pytest.raises(FileNotFoundError):
        WCMatchModel()
```

**Graceful fallback when stats missing** (pattern from soccer model defensive loading):
```python
def test_init_succeeds_when_stats_missing(monkeypatch):
    monkeypatch.setattr(
        "alpha.engines.sports.wc_model.load_wc_elo_ratings",
        lambda: _FAKE_ELO,
    )
    monkeypatch.setattr(
        "alpha.engines.sports.wc_model.get_wc_team_stats",
        lambda: (_ for _ in ()).throw(FileNotFoundError("wc_stats.pkl missing")),
    )
    model = WCMatchModel()          # must not raise
    assert model._wc_stats == {}
```

**evaluate_bet() no-edge pattern** (`test_mlb_model.py` lines 85-91):
```python
def test_evaluate_bet_returns_no_bet_when_no_edge(model):
    with patch("alpha.engines.sports.mlb_model.MLBModel._load_xgb_models"):
        model = MLBModel(min_edge=0.99)
    game = {"home_team": "NYY", "away_team": "BOS",
            "home_odds": -200, "away_odds": 170}
    result = model.evaluate_bet(game)
    assert result["bet_side"] == "no_bet"
```

For `wc_model.py` (returns None instead of dict):
```python
def test_evaluate_bet_returns_none_when_no_edge(monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.wc_model.load_wc_elo_ratings",
                        lambda: _FAKE_ELO)
    monkeypatch.setattr("alpha.engines.sports.wc_model.get_wc_team_stats",
                        lambda: _FAKE_STATS)
    model = WCMatchModel(min_edge=0.99)   # impossibly high threshold
    game = {"home_team": "Brazil", "away_team": "Germany",
            "home_odds": -130, "away_odds": 110, "league": "wc"}
    assert model.evaluate_bet(game) is None
```

**soccer_model import guard test** (new — required by CONTEXT.md grep-check requirement):
```python
def test_wc_model_does_not_import_soccer_model():
    """wc_model.py must never import from soccer_model.py."""
    import inspect
    import alpha.engines.sports.wc_model as wc_mod
    source = inspect.getsource(wc_mod)
    assert "soccer_model" not in source
```

---

## Shared Patterns

### EVCalculator Usage
**Source:** `alpha/engines/sports/ev_calculator.py` (lines 36-46)
**Apply to:** `wc_model.py` — market divergence flag and evaluate_bet
```python
# american -> decimal -> implied probability
home_dec = self.ev_calc.american_to_decimal(home_odds)      # e.g. -110 -> 1.909
market_implied = self.ev_calc.implied_prob(home_dec)         # e.g. 0.524
# edge check
has_edge = self.ev_calc.has_edge(model_prob, home_dec)       # ev >= min_edge
```

### Logger Setup
**Source:** `alpha/engines/sports/soccer_model.py` (line 22)
**Apply to:** `wc_model.py`
```python
logger = logging.getLogger(__name__)
```

### Defensive Data Loading
**Source:** `alpha/engines/sports/soccer_model.py` (lines 306-319)
**Apply to:** `wc_model.py` `__init__` for `get_wc_team_stats()` call
```python
try:
    self._wc_stats = get_wc_team_stats()
except FileNotFoundError:
    logger.warning("WC stats cache not found — running Elo-only mode")
    self._wc_stats = {}
```

### Monkeypatch at Module Level (tests)
**Source:** `tests/unit/test_wc_priors_loader.py` (lines 14-16), `tests/unit/test_wc_stats.py` (lines 13-16)
**Apply to:** `test_wc_model.py` — all test functions that instantiate `WCMatchModel`
```python
monkeypatch.setattr("alpha.engines.sports.wc_model.load_wc_elo_ratings", lambda: _FAKE_ELO)
monkeypatch.setattr("alpha.engines.sports.wc_model.get_wc_team_stats", lambda: _FAKE_STATS)
```
Prefer a `@pytest.fixture` named `model` that applies both patches, then consume `model` as a parameter in test functions (pattern from `test_mlb_model.py` `with patch(...)` blocks).

### Probability Normalization Check (tests)
**Source:** `tests/unit/engines/test_mlb_model.py` (line 36)
**Apply to:** `test_wc_model.py` — group stage and knockout stage prob-sum assertions
```python
assert result["win_prob"] + result["draw_prob"] + result["loss_prob"] == pytest.approx(1.0, abs=0.001)
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| None | — | — | Both files have strong analogs |

### Novel logic with no codebase analog (implement from CONTEXT.md spec directly)

These behaviors are unique to WC model and have no existing analog to copy from:

| Behavior | Source |
|---|---|
| Elo-logistic formula: `p = 1 / (1 + 10 ** (-elo_adj / 400.0))` | CONTEXT.md specifics |
| Draw decomposition: `p_home = p_home_2way * (1 - _WC_DRAW_RATE)` | CONTEXT.md formula |
| xG modifier: `elo_adj = elo_diff + xg_diff * 35.0`, capped `[-200, 200]` | CONTEXT.md formula |
| Knockout gate: `if knockout: p_draw = 0.0; p_home = p_home_2way` | CONTEXT.md MODEL-02 |
| elo_edge flag: `abs(win_prob - market_implied) > 0.05` | CONTEXT.md MODEL-04 |
| League guard: `raise ValueError` if `game.get("league") != "wc"` | CONTEXT.md decision |

---

## Metadata

**Analog search scope:** `alpha/engines/sports/`, `tests/unit/engines/`, `tests/unit/`
**Files scanned:** 6 (soccer_model.py, ev_calculator.py, wc_elo.py, wc_stats.py, test_mlb_model.py, test_wc_priors_loader.py, test_wc_stats.py)
**Pattern extraction date:** 2026-06-18
