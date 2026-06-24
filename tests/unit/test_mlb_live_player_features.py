"""
Unit tests for alpha/data/ingestion/mlb_live_player_features.py
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from alpha.data.ingestion.mlb_live_player_features import (
    _era_to_quality,
    _normalize_pitcher_name,
    build_live_player_features,
    build_quality_from_team_state,
    team_era_quality_map_by_full_name,
)


# ---------------------------------------------------------------------------
# _era_to_quality
# ---------------------------------------------------------------------------

def test_era_to_quality_low_era_gives_high_score():
    assert _era_to_quality(1.5) == pytest.approx(1.0, abs=0.01)


def test_era_to_quality_high_era_gives_low_score():
    assert _era_to_quality(6.5) == pytest.approx(0.0, abs=0.01)


def test_era_to_quality_mid_era():
    # ERA 4.0 → (6.5-4.0)/(6.5-1.5) = 2.5/5.0 = 0.5
    assert _era_to_quality(4.0) == pytest.approx(0.5, abs=0.01)


def test_era_to_quality_clamps_below_zero():
    assert _era_to_quality(10.0) == pytest.approx(0.0, abs=0.01)


def test_era_to_quality_clamps_above_one():
    assert _era_to_quality(0.0) == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# _normalize_pitcher_name
# ---------------------------------------------------------------------------

def test_normalize_comma_format():
    assert _normalize_pitcher_name("Cole, Gerrit") == "Gerrit Cole"


def test_normalize_already_normal():
    assert _normalize_pitcher_name("Gerrit Cole") == "Gerrit Cole"


def test_normalize_strips_whitespace():
    assert _normalize_pitcher_name(" Cole,  Gerrit ") == "Gerrit Cole"


# ---------------------------------------------------------------------------
# build_live_player_features — happy path
# ---------------------------------------------------------------------------

_FAKE_GAMES = [
    {
        "event_id": "g1",
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "commence_time": "2026-06-24",
    },
    {
        "event_id": "g2",
        "home_team": "Los Angeles Dodgers",
        "away_team": "San Francisco Giants",
        "commence_time": "2026-06-24",
    },
]

_FAKE_PITCHERS = {
    "New York Yankees": "Cole, Gerrit",
    "Boston Red Sox":   "Crawford, Kutter",
}

_FAKE_PITCHER_STATS = [
    {"player": "Gerrit Cole",    "team": "NYY", "era": 2.80, "ip": 80.0, "whip": 1.0, "k_per9": 11.0},
    {"player": "Kutter Crawford","team": "BOS", "era": 4.10, "ip": 60.0, "whip": 1.2, "k_per9": 8.5},
]

_FAKE_TEAM_PITCHING = [
    {"team": "LAD", "era": 3.20, "whip": 1.1, "runs_allowed_per_game": 3.5, "k_per9": 9.0},
    {"team": "SF",  "era": 4.00, "whip": 1.25, "runs_allowed_per_game": 4.0, "k_per9": 8.0},
]


def test_build_live_player_features_returns_all_event_ids():
    with (
        patch("alpha.data.ingestion.mlb_stats.get_probable_pitchers", return_value=_FAKE_PITCHERS),
        patch("alpha.data.ingestion.mlb_stats.get_pitcher_stats", return_value=_FAKE_PITCHER_STATS),
        patch("alpha.data.ingestion.mlb_stats.get_team_pitching_stats", return_value=_FAKE_TEAM_PITCHING),
    ):
        result = build_live_player_features(_FAKE_GAMES)

    assert set(result.keys()) == {"g1", "g2"}


def test_build_live_player_features_named_pitcher_used():
    with (
        patch("alpha.data.ingestion.mlb_stats.get_probable_pitchers", return_value=_FAKE_PITCHERS),
        patch("alpha.data.ingestion.mlb_stats.get_pitcher_stats", return_value=_FAKE_PITCHER_STATS),
        patch("alpha.data.ingestion.mlb_stats.get_team_pitching_stats", return_value=_FAKE_TEAM_PITCHING),
    ):
        result = build_live_player_features(_FAKE_GAMES)

    g1 = result["g1"]
    # Gerrit Cole ERA 2.80 → quality = (6.5-2.80)/5.0 = 0.74
    assert g1["home_sp_quality"] == pytest.approx(_era_to_quality(2.80), abs=0.01)
    assert g1["home_sp_missing"] == pytest.approx(0.0)


def test_build_live_player_features_team_fallback_used():
    with (
        patch("alpha.data.ingestion.mlb_stats.get_probable_pitchers", return_value={}),
        patch("alpha.data.ingestion.mlb_stats.get_pitcher_stats", return_value=[]),
        patch("alpha.data.ingestion.mlb_stats.get_team_pitching_stats", return_value=_FAKE_TEAM_PITCHING),
    ):
        result = build_live_player_features(_FAKE_GAMES)

    # g2 = LAD vs SF, team fallback
    g2 = result["g2"]
    assert g2["home_sp_quality"] == pytest.approx(_era_to_quality(3.20), abs=0.01)
    assert g2["home_sp_missing"] == pytest.approx(0.0)


def test_build_live_player_features_missing_team_sets_missing_flag():
    with (
        patch("alpha.data.ingestion.mlb_stats.get_probable_pitchers", return_value={}),
        patch("alpha.data.ingestion.mlb_stats.get_pitcher_stats", return_value=[]),
        patch("alpha.data.ingestion.mlb_stats.get_team_pitching_stats", return_value=[]),
    ):
        result = build_live_player_features(_FAKE_GAMES)

    g1 = result["g1"]
    assert g1["home_sp_missing"] == pytest.approx(1.0)
    assert g1["player_feature_missing_flag"] == pytest.approx(1.0)


def test_build_live_player_features_sp_quality_diff():
    with (
        patch("alpha.data.ingestion.mlb_stats.get_probable_pitchers", return_value=_FAKE_PITCHERS),
        patch("alpha.data.ingestion.mlb_stats.get_pitcher_stats", return_value=_FAKE_PITCHER_STATS),
        patch("alpha.data.ingestion.mlb_stats.get_team_pitching_stats", return_value=_FAKE_TEAM_PITCHING),
    ):
        result = build_live_player_features(_FAKE_GAMES)

    g1 = result["g1"]
    expected_diff = g1["home_sp_quality"] - g1["away_sp_quality"]
    assert g1["sp_quality_diff"] == pytest.approx(expected_diff, abs=0.001)


def test_build_live_player_features_default_workload_and_rest():
    with (
        patch("alpha.data.ingestion.mlb_stats.get_probable_pitchers", return_value=_FAKE_PITCHERS),
        patch("alpha.data.ingestion.mlb_stats.get_pitcher_stats", return_value=_FAKE_PITCHER_STATS),
        patch("alpha.data.ingestion.mlb_stats.get_team_pitching_stats", return_value=_FAKE_TEAM_PITCHING),
    ):
        result = build_live_player_features(_FAKE_GAMES)

    g1 = result["g1"]
    assert g1["home_sp_workload"] == pytest.approx(90.0)
    assert g1["home_sp_rest_days"] == pytest.approx(5.0)
    assert g1["sp_workload_diff"] == pytest.approx(0.0)


def test_build_live_player_features_empty_games():
    result = build_live_player_features([])
    assert result == {}


def test_build_live_player_features_no_event_id_skipped():
    games = [{"home_team": "NYY", "away_team": "BOS"}]  # no event_id
    with (
        patch("alpha.data.ingestion.mlb_stats.get_probable_pitchers", return_value={}),
        patch("alpha.data.ingestion.mlb_stats.get_pitcher_stats", return_value=[]),
        patch("alpha.data.ingestion.mlb_stats.get_team_pitching_stats", return_value=[]),
    ):
        result = build_live_player_features(games)
    assert result == {}


# ---------------------------------------------------------------------------
# team_era_quality_map_by_full_name
# ---------------------------------------------------------------------------

def test_team_era_quality_map_keys_are_full_names():
    with patch(
        "alpha.data.ingestion.mlb_stats.get_team_pitching_stats",
        return_value=[{"team": "NYY", "era": 3.50, "whip": 1.1, "runs_allowed_per_game": 3.8, "k_per9": 9.0}],
    ):
        result = team_era_quality_map_by_full_name(2025)
    assert "New York Yankees" in result
    assert result["New York Yankees"] == pytest.approx(_era_to_quality(3.50), abs=0.01)


def test_team_era_quality_map_unknown_abbr_skipped():
    with patch(
        "alpha.data.ingestion.mlb_stats.get_team_pitching_stats",
        return_value=[{"team": "ZZZZZ", "era": 4.00, "whip": 1.2, "runs_allowed_per_game": 4.0, "k_per9": 8.5}],
    ):
        result = team_era_quality_map_by_full_name(2025)
    assert result == {}


# ---------------------------------------------------------------------------
# build_quality_from_team_state
# ---------------------------------------------------------------------------

def test_build_quality_from_team_state_basic():
    team_state = {
        "New York Yankees": {"games": 100, "wins": 60, "runs_for": 500.0, "runs_against": 350.0, "elo": 1540.0, "last_date": "2025-06-20"},
        "Boston Red Sox":   {"games": 100, "wins": 45, "runs_for": 420.0, "runs_against": 480.0, "elo": 1460.0, "last_date": "2025-06-20"},
    }
    result = build_quality_from_team_state(team_state)
    # NYY allows 3.5/game → quality = (8-3.5)/6 = 0.75
    assert result["New York Yankees"] == pytest.approx(0.75, abs=0.01)
    # BOS allows 4.8/game → quality = (8-4.8)/6 = 0.533
    assert result["Boston Red Sox"] == pytest.approx(0.533, abs=0.01)


def test_build_quality_from_team_state_clamps_bounds():
    team_state = {
        "Team A": {"games": 10, "wins": 9, "runs_for": 100.0, "runs_against": 5.0, "elo": 1600.0, "last_date": ""},
        "Team B": {"games": 10, "wins": 0, "runs_for": 20.0, "runs_against": 120.0, "elo": 1400.0, "last_date": ""},
    }
    result = build_quality_from_team_state(team_state)
    assert result["Team A"] == pytest.approx(1.0, abs=0.01)  # 0.5/game - clamps to 1.0
    assert result["Team B"] == pytest.approx(0.0, abs=0.01)  # 12/game - clamps to 0.0


def test_build_quality_from_team_state_skips_zero_games():
    team_state = {
        "Team A": {"games": 0, "wins": 0, "runs_for": 0.0, "runs_against": 0.0, "elo": 1500.0, "last_date": ""},
    }
    result = build_quality_from_team_state(team_state)
    assert result == {}


def test_build_live_player_features_uses_team_quality_override():
    override = {"New York Yankees": 0.85, "Boston Red Sox": 0.45}
    with (
        patch("alpha.data.ingestion.mlb_stats.get_probable_pitchers", return_value={}),
        patch("alpha.data.ingestion.mlb_stats.get_pitcher_stats", return_value=[]),
        patch("alpha.data.ingestion.mlb_stats.get_team_pitching_stats", return_value=[]),
    ):
        result = build_live_player_features(
            _FAKE_GAMES[:1],  # only g1: NYY vs BOS
            team_quality_override=override,
        )
    g1 = result["g1"]
    assert g1["home_sp_quality"] == pytest.approx(0.85, abs=0.01)
    assert g1["away_sp_quality"] == pytest.approx(0.45, abs=0.01)
    assert g1["home_sp_missing"] == pytest.approx(0.0)
