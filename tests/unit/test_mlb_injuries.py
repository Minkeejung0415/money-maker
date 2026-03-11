"""Tests for alpha/data/ingestion/mlb_injuries.py (mocked ESPN API calls)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from alpha.data.ingestion.mlb_injuries import (
    _ESPN_TEAM_IDS,
    _fuzzy_match_player,
    get_espn_out_players,
    get_espn_team_ids_dynamic,
    get_team_injury_impact,
)


# ---------------------------------------------------------------------------
# Static ESPN team ID map
# ---------------------------------------------------------------------------

def test_espn_team_ids_has_yankees():
    assert "New York Yankees" in _ESPN_TEAM_IDS
    assert isinstance(_ESPN_TEAM_IDS["New York Yankees"], int)


def test_espn_team_ids_has_30_teams():
    assert len(_ESPN_TEAM_IDS) == 30


def test_espn_team_ids_has_dodgers():
    assert "Los Angeles Dodgers" in _ESPN_TEAM_IDS


# ---------------------------------------------------------------------------
# get_espn_team_ids_dynamic
# ---------------------------------------------------------------------------

def test_dynamic_team_ids_returns_static_on_api_failure():
    with patch("alpha.data.ingestion.mlb_injuries._get", return_value=None):
        result = get_espn_team_ids_dynamic()
    # Should return the static map as fallback
    assert "New York Yankees" in result


def test_dynamic_team_ids_parses_scoreboard():
    fake_scoreboard = {
        "events": [{
            "competitions": [{
                "competitors": [
                    {"team": {"displayName": "New York Yankees", "id": "10"}},
                    {"team": {"displayName": "Boston Red Sox", "id": "2"}},
                ]
            }]
        }]
    }
    with patch("alpha.data.ingestion.mlb_injuries._get", return_value=fake_scoreboard):
        result = get_espn_team_ids_dynamic()
    assert result["New York Yankees"] == 10
    assert result["Boston Red Sox"] == 2


# ---------------------------------------------------------------------------
# get_espn_out_players
# ---------------------------------------------------------------------------

def test_espn_out_players_returns_only_out():
    fake_response = {
        "injuries": [
            {"athlete": {"displayName": "Aaron Judge"}, "status": "Out"},
            {"athlete": {"displayName": "Anthony Rizzo"}, "status": "Questionable"},
            {"athlete": {"displayName": "Gerrit Cole"}, "status": "Day-To-Day"},
        ]
    }
    with patch("alpha.data.ingestion.mlb_injuries._get", return_value=fake_response):
        result = get_espn_out_players("New York Yankees")
    assert result == ["Aaron Judge"]


def test_espn_out_players_returns_empty_for_unknown_team():
    result = get_espn_out_players("Unknown Team XYZ")
    assert result == []


def test_espn_out_players_returns_empty_on_api_failure():
    with patch("alpha.data.ingestion.mlb_injuries._get", return_value=None):
        result = get_espn_out_players("New York Yankees")
    assert result == []


def test_espn_out_players_returns_empty_when_no_injuries():
    with patch("alpha.data.ingestion.mlb_injuries._get", return_value={"injuries": []}):
        result = get_espn_out_players("New York Yankees")
    assert result == []


# ---------------------------------------------------------------------------
# get_team_injury_impact
# ---------------------------------------------------------------------------

def test_injury_impact_returns_empty_when_no_players_out():
    with patch("alpha.data.ingestion.mlb_injuries.get_espn_out_players", return_value=[]):
        result = get_team_injury_impact()
    assert result == {}


def test_injury_impact_includes_team_when_player_out():
    with patch("alpha.data.ingestion.mlb_injuries.get_espn_out_players",
               side_effect=lambda t: ["Aaron Judge"] if t == "New York Yankees" else []), \
         patch("alpha.data.ingestion.mlb_injuries._load_player_stats",
               return_value={"Aaron Judge": {"avg": 0.310, "hr_per_game": 0.040}}):
        result = get_team_injury_impact()
    assert "New York Yankees" in result
    assert result["New York Yankees"]["avg_lost"] == pytest.approx(0.310)
    assert result["New York Yankees"]["hr_lost"] == pytest.approx(0.040)


def test_injury_impact_handles_unknown_player_gracefully():
    with patch("alpha.data.ingestion.mlb_injuries.get_espn_out_players",
               side_effect=lambda t: ["Unknown Player X"] if t == "New York Yankees" else []), \
         patch("alpha.data.ingestion.mlb_injuries._load_player_stats",
               return_value={}):
        result = get_team_injury_impact()
    if "New York Yankees" in result:
        assert result["New York Yankees"]["avg_lost"] == pytest.approx(0.0)


def test_injury_impact_out_list_has_correct_shape():
    with patch("alpha.data.ingestion.mlb_injuries.get_espn_out_players",
               side_effect=lambda t: ["Aaron Judge"] if t == "New York Yankees" else []), \
         patch("alpha.data.ingestion.mlb_injuries._load_player_stats",
               return_value={"Aaron Judge": {"avg": 0.310, "hr_per_game": 0.040}}):
        result = get_team_injury_impact()
    assert "New York Yankees" in result
    out = result["New York Yankees"]["out"]
    assert len(out) == 1
    assert out[0]["name"] == "Aaron Judge"


# ---------------------------------------------------------------------------
# _fuzzy_match_player
# ---------------------------------------------------------------------------

def test_fuzzy_match_player_by_last_name():
    stats_map = {"Aaron Judge": {"avg": 0.310, "hr_per_game": 0.040}}
    result = _fuzzy_match_player("A. Judge", stats_map)
    assert result is not None
    assert result["avg"] == 0.310


def test_fuzzy_match_player_returns_none_on_miss():
    stats_map = {"Aaron Judge": {"avg": 0.310}}
    result = _fuzzy_match_player("Mike Trout", stats_map)
    assert result is None
