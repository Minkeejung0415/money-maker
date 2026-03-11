"""Tests for alpha/engines/sports/mlb_prop_model.py."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from alpha.engines.sports.mlb_prop_model import MLBPropModel, _MIN_GAMES


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def test_mlb_prop_model_init():
    model = MLBPropModel()
    assert hasattr(model, "_season")
    assert isinstance(model._season, int)


# ---------------------------------------------------------------------------
# Unknown market
# ---------------------------------------------------------------------------

def test_predict_prop_unknown_market_returns_none():
    model = MLBPropModel()
    result = model.predict_prop("Aaron Judge", "unknown_market", 1.5)
    assert result is None


# ---------------------------------------------------------------------------
# _classify_confidence
# ---------------------------------------------------------------------------

def test_classify_confidence_high():
    model = MLBPropModel()
    assert model._classify_confidence(0.72, 0.60) == "HIGH"


def test_classify_confidence_medium():
    model = MLBPropModel()
    assert model._classify_confidence(0.58, 0.52) == "MEDIUM"


def test_classify_confidence_low():
    model = MLBPropModel()
    assert model._classify_confidence(0.52, 0.51) == "LOW"


# ---------------------------------------------------------------------------
# _weighted_avg
# ---------------------------------------------------------------------------

def test_weighted_avg_basic():
    model = MLBPropModel()
    # All equal values → result should equal the value
    values = [3.0] * 15
    result = model._weighted_avg(values)
    assert result == pytest.approx(3.0)


def test_weighted_avg_higher_weight_on_recent():
    model = MLBPropModel()
    # Last 5 values (2.0) should pull weighted avg down compared to flat
    values = [2.0, 2.0, 2.0, 2.0, 2.0,
              4.0, 4.0, 4.0, 4.0, 4.0,
              4.0, 4.0, 4.0, 4.0, 4.0]
    result = model._weighted_avg(values)
    flat_avg = sum(values) / len(values)
    assert result < flat_avg  # recent underperformance should pull avg down


# ---------------------------------------------------------------------------
# _k9_to_per_start
# ---------------------------------------------------------------------------

def test_k9_to_per_start():
    result = MLBPropModel._k9_to_per_start(9.0, innings_per_start=6.0)
    assert result == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# predict_prop — batter stats
# ---------------------------------------------------------------------------

def test_predict_prop_batter_returns_structure(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.mlb_prop_model._CACHE_DIR", tmp_path)
    fake_batters = [{"player": "Aaron Judge", "team": "NYY",
                     "avg": 0.310, "obp": 0.400, "slg": 0.600,
                     "hr_per_game": 0.040, "pa": 500}]
    with patch("alpha.data.ingestion.mlb_stats.get_batter_stats", return_value=fake_batters):
        model = MLBPropModel(season=2025)
        result = model.predict_prop("Aaron Judge", "batter_hits", 1.5)
    assert result is not None
    assert result["player"] == "Aaron Judge"
    assert result["market"] == "batter_hits"
    assert 0.01 <= result["model_prob"] <= 0.99
    assert result["confidence"] in ("HIGH", "MEDIUM", "LOW")
    assert result["source"] == "mlb_stats"


def test_predict_prop_returns_none_when_player_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.mlb_prop_model._CACHE_DIR", tmp_path)
    with patch("alpha.data.ingestion.mlb_stats.get_batter_stats", return_value=[]):
        model = MLBPropModel(season=2025)
        result = model.predict_prop("Unknown Batter XYZ", "batter_hits", 1.5)
    assert result is None


# ---------------------------------------------------------------------------
# predict_prop — pitcher stats
# ---------------------------------------------------------------------------

def test_predict_prop_pitcher_uses_strikeout_conversion(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.mlb_prop_model._CACHE_DIR", tmp_path)
    fake_pitchers = [{"player": "Gerrit Cole", "team": "NYY",
                      "era": 2.80, "whip": 1.05, "k_per9": 12.0, "ip": 200.0}]
    with patch("alpha.data.ingestion.mlb_stats.get_pitcher_stats", return_value=fake_pitchers):
        model = MLBPropModel(season=2025)
        result = model.predict_prop("Gerrit Cole", "pitcher_strikeouts", 7.5,
                                    is_pitcher=True)
    assert result is not None
    assert result["player"] == "Gerrit Cole"
    assert result["proj_stat"] > 0  # K/9 converted to per-start


def test_predict_prop_pitcher_returns_none_when_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.mlb_prop_model._CACHE_DIR", tmp_path)
    with patch("alpha.data.ingestion.mlb_stats.get_pitcher_stats", return_value=[]):
        model = MLBPropModel(season=2025)
        result = model.predict_prop("Unknown Pitcher", "pitcher_strikeouts", 5.5,
                                    is_pitcher=True)
    assert result is None
