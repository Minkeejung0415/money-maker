"""Tests for alpha/engines/sports/soccer_prop_model.py."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from alpha.engines.sports.soccer_prop_model import (
    SoccerPropModel,
    _HIGH_GAP,
    _MEDIUM_GAP,
    _MIN_GAMES,
)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def test_soccer_prop_model_init():
    model = SoccerPropModel()
    assert model._league_key == "epl"


def test_soccer_prop_model_custom_league():
    model = SoccerPropModel(league_key="ucl")
    assert model._league_key == "ucl"


# ---------------------------------------------------------------------------
# _classify_confidence
# ---------------------------------------------------------------------------

def test_classify_confidence_high():
    model = SoccerPropModel()
    # Gap >= _HIGH_GAP
    conf = model._classify_confidence(0.75, 0.64)
    assert conf == "HIGH"


def test_classify_confidence_medium():
    model = SoccerPropModel()
    # Gap between _MEDIUM_GAP (0.08) and _HIGH_GAP (0.10)
    # Use gap = 0.09 to land in MEDIUM zone
    conf = model._classify_confidence(0.70, 0.61)
    assert conf == "MEDIUM"


def test_classify_confidence_low():
    model = SoccerPropModel()
    # Gap < _MEDIUM_GAP
    conf = model._classify_confidence(0.53, 0.52)
    assert conf == "LOW"


# ---------------------------------------------------------------------------
# _american_to_implied
# ---------------------------------------------------------------------------

def test_american_to_implied_negative_odds():
    implied = SoccerPropModel._american_to_implied(-110)
    assert implied == pytest.approx(110 / 210, abs=0.001)


def test_american_to_implied_positive_odds():
    implied = SoccerPropModel._american_to_implied(200)
    assert implied == pytest.approx(100 / 300, abs=0.001)


# ---------------------------------------------------------------------------
# _weighted_avg
# ---------------------------------------------------------------------------

def test_weighted_avg_returns_correct_value():
    model = SoccerPropModel()
    values = [2.0, 2.0, 2.0, 2.0, 2.0,   # last5 avg=2.0
              3.0, 3.0, 3.0, 3.0, 3.0]   # last10 avg=2.5
    result = model._weighted_avg(values)
    # 0.5*2.0 + 0.5*2.5 = 2.25
    assert result == pytest.approx(2.25)


def test_weighted_avg_handles_short_list():
    model = SoccerPropModel()
    values = [2.0, 3.0, 4.0]
    result = model._weighted_avg(values)
    assert result > 0


# ---------------------------------------------------------------------------
# predict_prop — unknown market
# ---------------------------------------------------------------------------

def test_predict_prop_unknown_market_returns_none():
    model = SoccerPropModel()
    result = model.predict_prop("Erling Haaland", "unknown_market", 0.5)
    assert result is None


# ---------------------------------------------------------------------------
# predict_prop — insufficient data
# ---------------------------------------------------------------------------

def test_predict_prop_returns_none_when_no_player_found(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.soccer_prop_model._CACHE_DIR", tmp_path)
    with patch("alpha.data.ingestion.soccer_stats.get_player_per90_stats", return_value=[]):
        model = SoccerPropModel()
        result = model.predict_prop("Unknown Player", "player_goals", 0.5)
    assert result is None


# ---------------------------------------------------------------------------
# predict_prop — successful path
# ---------------------------------------------------------------------------

def test_predict_prop_returns_correct_structure(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.soccer_prop_model._CACHE_DIR", tmp_path)
    fake_player_stats = [{
        "player": "Erling Haaland",
        "team": "Man City",
        "league": "epl",
        "goals_per90": 1.2,
        "assists_per90": 0.3,
        "shots_per90": 4.5,
        "xG_per90": 1.0,
        "minutes_90s": 30.0,
    }]
    with patch("alpha.data.ingestion.soccer_stats.get_player_per90_stats",
               return_value=fake_player_stats):
        model = SoccerPropModel()
        result = model.predict_prop("Erling Haaland", "player_goals", 0.5)
    assert result is not None
    assert result["player"] == "Erling Haaland"
    assert result["market"] == "player_goals"
    assert 0.0 < result["model_prob"] < 1.0
    assert result["confidence"] in ("HIGH", "MEDIUM", "LOW")
    assert result["source"] == "soccer_stats"


def test_predict_prop_model_prob_clipped(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.engines.sports.soccer_prop_model._CACHE_DIR", tmp_path)
    fake_player_stats = [{
        "player": "Erling Haaland",
        "team": "Man City",
        "league": "epl",
        "goals_per90": 5.0,   # very high — should still clip p_over < 0.99
        "assists_per90": 0.3,
        "shots_per90": 10.0,
        "xG_per90": 4.0,
        "minutes_90s": 30.0,
    }]
    with patch("alpha.data.ingestion.soccer_stats.get_player_per90_stats",
               return_value=fake_player_stats):
        model = SoccerPropModel()
        result = model.predict_prop("Erling Haaland", "player_goals", 0.5, over_odds=-200)
    assert result is not None
    assert result["model_prob"] <= 0.99
    assert result["model_prob"] >= 0.01
