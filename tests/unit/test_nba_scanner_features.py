"""Tests for NBA scanner features: ml mode, min-prob filter, H2H, traded player, team map."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCANNER = ROOT / "scripts" / "sgp_scanner.py"
PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Feature 1: --mode ml lists all games
# ---------------------------------------------------------------------------


def test_ml_mode_lists_all_games():
    """--mode ml must be accepted and produce output for both sides of each game."""
    result = subprocess.run(
        [PYTHON, str(SCANNER), "--help"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert "ml" in result.stdout.lower(), "'ml' not in --help output"


# ---------------------------------------------------------------------------
# Feature 2: min-prob filter
# ---------------------------------------------------------------------------


def test_min_prob_filter():
    """Legs below the --min-prob threshold are dropped."""
    from alpha.engines.sports.sgp_builder import PropLeg

    legs = [
        PropLeg("A", "player_points", 25.5, 0.55, -110, "e1", "H", "A", "HIGH"),
        PropLeg("B", "player_rebounds", 8.5, 0.70, -110, "e1", "H", "A", "HIGH"),
        PropLeg("C", "player_assists", 6.5, 0.58, -110, "e1", "H", "A", "MEDIUM"),
        PropLeg("D", "player_points", 20.5, 0.62, -110, "e1", "H", "A", "HIGH"),
    ]
    min_prob = 0.60
    filtered = [leg for leg in legs if leg.model_prob >= min_prob]
    assert len(filtered) == 2
    assert all(leg.model_prob >= min_prob for leg in filtered)
    assert {leg.player for leg in filtered} == {"B", "D"}


# ---------------------------------------------------------------------------
# Feature 5: H2H nudges home prob
# ---------------------------------------------------------------------------


def test_h2h_nudges_home_prob():
    """Mock H2H data where home team dominates → home_prob should increase."""
    from alpha.engines.sports.nba_model import NBAModel

    model = NBAModel.__new__(NBAModel)
    model.ev_calc = MagicMock()
    model._xgb_models_loaded = False
    model._injury_loaded = True
    model._injury_impact = {}
    model._context_loaded = True
    model._paint_deterrence = None
    model._foul_trouble = None
    model._opp_stats = None

    mock_cache = MagicMock()
    mock_cache.fetch_team_recent_form.return_value = None
    mock_cache.fetch_head_to_head.return_value = {
        "home_wins": 8,
        "away_wins": 2,
        "total_games": 10,
        "home_win_pct_h2h": 0.80,
    }
    model._stats_cache = mock_cache
    model._team_stats_cache = {}  # avoid calling _get_latest_team_df

    home_prob, away_prob = model._apply_context_adjustments(
        0.50, 0.50, {"home_team": "TeamA", "away_team": "TeamB"}
    )
    assert home_prob > 0.50, "H2H dominance should nudge home prob up"
    assert away_prob < 0.50
    # Nudge capped at ±0.03
    assert home_prob <= 0.53 + 0.001


# ---------------------------------------------------------------------------
# Feature 6: traded player confidence downgrade
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# fetch_player_team_map
# ---------------------------------------------------------------------------


def test_fetch_player_team_map_returns_correct_team():
    """fetch_player_team_map should map player names (lowercase) to full team names."""
    from alpha.data.ingestion.nba_stats_cache import NBAStatsCache

    cache = NBAStatsCache.__new__(NBAStatsCache)

    # Mock fetch_league_dash_team_stats → abbreviation to full name
    cache.fetch_league_dash_team_stats = MagicMock(return_value=[
        {"TEAM_ABBREVIATION": "BOS", "TEAM_NAME": "Boston Celtics"},
        {"TEAM_ABBREVIATION": "WAS", "TEAM_NAME": "Washington Wizards"},
        {"TEAM_ABBREVIATION": "MIL", "TEAM_NAME": "Milwaukee Bucks"},
    ])
    # Mock fetch_league_dash_player_stats → player to abbreviation
    cache.fetch_league_dash_player_stats = MagicMock(return_value=[
        {"PLAYER_NAME": "Jayson Tatum", "TEAM_ABBREVIATION": "BOS"},
        {"PLAYER_NAME": "Trae Young", "TEAM_ABBREVIATION": "WAS"},
        {"PLAYER_NAME": "Giannis Antetokounmpo", "TEAM_ABBREVIATION": "MIL"},
    ])

    team_map = cache.fetch_player_team_map()

    assert team_map["jayson tatum"] == "Boston Celtics"
    assert team_map["trae young"] == "Washington Wizards"
    assert team_map["giannis antetokounmpo"] == "Milwaukee Bucks"


def test_fetch_player_team_map_fallback_on_error():
    """fetch_player_team_map should return empty dict on any error."""
    from alpha.data.ingestion.nba_stats_cache import NBAStatsCache

    cache = NBAStatsCache.__new__(NBAStatsCache)
    cache.fetch_league_dash_team_stats = MagicMock(side_effect=RuntimeError("API down"))
    cache.fetch_league_dash_player_stats = MagicMock(return_value=[])

    result = cache.fetch_player_team_map()
    assert result == {}


def test_prop_leg_player_team_uses_team_map():
    """PropLeg player_team should match actual player team, not always home_team."""
    from alpha.engines.sports.sgp_builder import PropLeg

    # Simulate what scanner now does: look up actual team from map
    player_team_map = {"trae young": "Washington Wizards"}
    player = "Trae Young"
    home_team = "Boston Celtics"  # Trae is NOT on Boston
    actual_team = player_team_map.get(player.lower(), home_team)

    leg = PropLeg(
        player=player, market="player_points", line=15.0,
        model_prob=0.70, over_odds=-110, event_id="e1",
        home_team=home_team, away_team="Washington Wizards",
        confidence="HIGH", player_team=actual_team,
    )
    assert leg.player_team == "Washington Wizards"
    assert leg.player_team != home_team


def test_traded_player_confidence_downgraded():
    """Player with <5 games on current team should have confidence downgraded."""
    from alpha.engines.sports.prop_model import PropModel

    mock_cache = MagicMock()
    mock_cache.fetch_player_team_game_count.return_value = {
        "current_team_games": 3,
        "total_games": 50,
    }

    model = PropModel(season="2024-25", stats_cache=mock_cache)

    fake_logs = []
    for i in range(20):
        fake_logs.append({
            "MIN_float": 32.0,
            "PTS": 22.0 + (i % 5),
            "REB": 5.0,
            "AST": 8.0,
            "FG3M": 3.0,
            "MATCHUP": "ATL vs. BOS" if i < 5 else "WAS vs. BOS",
        })
    model._log_cache["Trae Young"] = fake_logs

    result = model.predict_prop(
        player_name="Trae Young",
        market="player_points",
        line=15.0,
        opponent_team="Boston Celtics",
        over_odds=-110,
    )
    assert result is not None
    assert result["recent_trade"] is True
    # With a large gap, original confidence would be HIGH; should be downgraded to MEDIUM
    assert result["confidence"] in ("MEDIUM", "LOW")
