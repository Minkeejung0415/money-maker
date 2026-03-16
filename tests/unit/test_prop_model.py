"""Unit tests for PropModel."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_log_rows(pts_values: list[float], min_val: float = 30.0) -> list[dict]:
    """Build a list of fake game-log dicts."""
    return [
        {"PTS": v, "REB": 5.0, "AST": 5.0, "FG3M": 2.0, "MIN": str(int(min_val)), "MIN_float": min_val}
        for v in pts_values
    ]


@pytest.fixture
def model():
    from alpha.engines.sports.prop_model import PropModel
    # Disable XGBoost models so unit tests use the weighted-avg path only.
    # XGBoost pkl files on disk should not affect unit test assertions.
    with patch("alpha.engines.sports.xgb_prop_model.XGBoostPropModel.load", return_value=None):
        m = PropModel(season="2024-25")
    m._xgb_models = {}
    return m


def _patch_logs(log_rows: list[dict]):
    """Patch _fetch_game_logs to return the given rows."""
    return patch(
        "alpha.engines.sports.prop_model.PropModel._fetch_game_logs",
        return_value=log_rows,
    )


def _patch_def_ratings(ratings: dict | None = None):
    return patch(
        "alpha.engines.sports.prop_model.PropModel._fetch_def_ratings",
        return_value=ratings or {},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_high_avg_beats_low_line(model):
    """30-point average player against a 25-point line → model_prob > 0.70."""
    rows = _make_log_rows([30.0] * 20)
    with _patch_logs(rows), _patch_def_ratings():
        result = model.predict_prop("Test Player", "player_points", 25.0, "Boston Celtics")
    assert result is not None
    assert result["model_prob"] > 0.70


def test_low_avg_misses_high_line(model):
    """20-point average player against a 25-point line → model_prob < 0.30."""
    rows = _make_log_rows([20.0] * 20)
    with _patch_logs(rows), _patch_def_ratings():
        result = model.predict_prop("Test Player", "player_points", 25.0, "Boston Celtics")
    assert result is not None
    assert result["model_prob"] < 0.30


def test_returns_none_on_empty_logs(model):
    """Empty game log → None returned."""
    with _patch_logs([]):
        result = model.predict_prop("Ghost Player", "player_points", 20.0, "Boston Celtics")
    assert result is None


def test_filters_low_minute_games(model):
    """Games with < 20 minutes are excluded; only high-minute games count."""
    # 3 low-minute games that would be filtered out, 5 legit 35-point games
    low_min_rows = _make_log_rows([50.0] * 3, min_val=15.0)   # should be excluded
    high_min_rows = _make_log_rows([35.0] * 15, min_val=35.0)  # should count
    rows = low_min_rows + high_min_rows
    with _patch_logs(rows), _patch_def_ratings():
        result = model.predict_prop("Test Player", "player_points", 30.0, "Boston Celtics")
    assert result is not None
    # proj_stat should reflect the high-minute rows (~35), not the inflated 50-pt rows
    assert result["proj_stat"] < 45.0


def test_weighted_avg_favors_recent(model):
    """Last 5 games averaging 35 pts should pull projection above simple 20-game avg."""
    # last 5 = 35 pts, next 15 = 15 pts → simple avg ≈ 20; weighted should be > 20
    recent = _make_log_rows([35.0] * 5)
    older  = _make_log_rows([15.0] * 15)
    rows = recent + older
    with _patch_logs(rows), _patch_def_ratings():
        result = model.predict_prop("Test Player", "player_points", 20.0, "Boston Celtics")
    assert result is not None
    # proj_stat = 0.5*35 + 0.3*avg(first10) + 0.2*avg(first20)
    # avg(first10) = (5*35 + 5*15)/10 = 25
    # avg(first20) = (5*35 + 15*15)/20 = 20
    # weighted = (0.5*35 + 0.3*25 + 0.2*20) / 1.0 = 17.5+7.5+4.0 = 29.0
    assert result["proj_stat"] > 20.0


def test_market_col_mapping(model):
    assert model._market_col("player_points")   == "PTS"
    assert model._market_col("player_rebounds") == "REB"
    assert model._market_col("player_assists")  == "AST"
    assert model._market_col("player_threes")   is None
    assert model._market_col("player_steals")   is None


def test_confidence_high_when_large_gap(model):
    """Model ~84%, market 52% → gap=32% → HIGH confidence."""
    rows = _make_log_rows([26.0] * 20)
    with _patch_logs(rows), _patch_def_ratings():
        # over_odds=-110 → market_implied ≈ 52.4%
        # With avg=26 and line=25 and std≈1.0, p_over ≈ 0.84 → gap large
        # (line=25 avoids CONF-02 low-line skepticism gate)
        result = model.predict_prop("Test Player", "player_points", 25.0, "Boston Celtics",
                                    over_odds=-110)
    assert result is not None
    assert result["confidence"] == "HIGH"


def test_confidence_low_when_small_gap(model):
    """Model ≈ market probability → LOW confidence."""
    # line = mean so model_prob ≈ 0.50, no-vig market_implied = 0.50 for -110/-110
    # gap = |0.50 - 0.50| = 0.00 < 0.04 → LOW
    rows = _make_log_rows([25.0] * 20)
    with _patch_logs(rows), _patch_def_ratings():
        result = model.predict_prop("Test Player", "player_points", 25.0, "Boston Celtics",
                                    over_odds=-110)
    assert result is not None
    assert result["confidence"] == "LOW"


# ---------------------------------------------------------------------------
# Vig removal tests
# ---------------------------------------------------------------------------

def test_american_to_novig_symmetric(model):
    """Symmetric -110/-110 market → no-vig implied = 0.50."""
    novig = model._american_to_novig(-110, -110)
    assert abs(novig - 0.50) < 0.001


def test_american_to_novig_asymmetric(model):
    """-115 over / +105 under → no-vig over ≈ 0.523."""
    novig = model._american_to_novig(-115, 105)
    assert abs(novig - 0.523) < 0.005


def test_american_to_novig_fallback(model):
    """When under_odds=None, assumes symmetric market → 0.50 for -110."""
    novig = model._american_to_novig(-110, None)
    assert abs(novig - 0.50) < 0.001


# ---------------------------------------------------------------------------
# James-Stein shrinkage tests
# ---------------------------------------------------------------------------

def test_shrinkage_pulls_toward_prior_small_sample():
    """5-game sample of 30 PTS for a PG (prior=15) → shrunk toward 15."""
    from alpha.engines.sports.prop_model import PropModel
    shrunk = PropModel._james_stein_shrink(
        observed=30.0, n_games=5, market="player_points", position="PG"
    )
    # prior=15, B=max(0,1-5/15)=0.667 → shrunk = 15 + 0.333*(30-15) ≈ 20.0
    assert 15.0 < shrunk < 30.0
    assert shrunk < 23.0  # heavily shrunk


def test_shrinkage_trusts_large_sample():
    """30-game sample → B=0, return observed unchanged."""
    from alpha.engines.sports.prop_model import PropModel
    shrunk = PropModel._james_stein_shrink(
        observed=28.0, n_games=30, market="player_points", position="PG"
    )
    # B = max(0, 1-30/15) = 0 → shrunk = observed
    assert abs(shrunk - 28.0) < 0.01


def test_shrinkage_uses_position_prior():
    """C prior REB=9 > PG prior REB=4 → same observed pulled differently."""
    from alpha.engines.sports.prop_model import PropModel
    shrunk_c  = PropModel._james_stein_shrink(5.0, 5, "player_rebounds", "C")
    shrunk_pg = PropModel._james_stein_shrink(5.0, 5, "player_rebounds", "PG")
    # C prior=9 → shrunk up from 5; PG prior=4 → shrunk down from 5
    assert shrunk_c > shrunk_pg


# ---------------------------------------------------------------------------
# Zero-Inflated Poisson tests
# ---------------------------------------------------------------------------

def test_zip_pi_zero_zero_equals_poisson():
    """ZIP with π=0 should equal plain Poisson."""
    from alpha.engines.sports.prop_model import PropModel
    from scipy.stats import poisson
    lam = 5.0
    p_zip = PropModel._zip_p_over(line=4, lam=lam, pi_zero=0.0)
    p_poi = float(1 - poisson.cdf(4, mu=lam))
    assert abs(p_zip - p_poi) < 0.001


def test_zip_reduces_probability_vs_poisson():
    """High zero-inflation (π=0.40) → lower P(over) than plain Poisson."""
    from alpha.engines.sports.prop_model import PropModel
    from scipy.stats import poisson
    lam = 3.0
    p_zip     = PropModel._zip_p_over(line=3, lam=lam, pi_zero=0.40)
    p_poisson = float(1 - poisson.cdf(3, mu=lam))
    # ZIP has extra mass at 0 → P(X>3) lower
    assert p_zip < p_poisson


def test_zip_used_for_sf_not_pg(model):
    """AST prediction: SF with many 0-assist games gets lower P(over) than PG."""
    from unittest.mock import patch

    # 40% zero-assist games — typical for a wing
    ast_values = [0, 0, 1, 2, 0, 3, 0, 1, 2, 0, 4, 0, 0, 1, 0, 2, 0, 0, 1, 0]
    rows_ast = [
        {"AST": v, "PTS": 15.0, "REB": 5.0, "FG3M": 1.0,
         "MIN": "30", "MIN_float": 30.0, "MATCHUP": "LAL vs. BOS"}
        for v in ast_values
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
    # SF uses ZIP with pi_zero>0 → lower P(over 1.5) than PG using plain Poisson
    assert result_sf["model_prob"] < result_pg["model_prob"]
