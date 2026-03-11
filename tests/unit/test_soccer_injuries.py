"""Tests for alpha/data/ingestion/soccer_injuries.py (mocked ESPN API calls)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from alpha.data.ingestion.soccer_injuries import (
    LEAGUE_SLUGS,
    _fuzzy_match_player,
    get_espn_out_players,
    get_espn_team_ids,
    get_team_injury_impact,
)


# ---------------------------------------------------------------------------
# LEAGUE_SLUGS
# ---------------------------------------------------------------------------

def test_league_slugs_contains_epl():
    assert "epl" in LEAGUE_SLUGS
    assert "eng" in LEAGUE_SLUGS["epl"]


def test_league_slugs_contains_ucl():
    assert "ucl" in LEAGUE_SLUGS
    assert "UEFA" in LEAGUE_SLUGS["ucl"] or "champions" in LEAGUE_SLUGS["ucl"].lower()


# ---------------------------------------------------------------------------
# get_espn_team_ids — mocked ESPN scoreboard
# ---------------------------------------------------------------------------

def test_get_espn_team_ids_returns_empty_on_unknown_league():
    result = get_espn_team_ids("xyz_unknown")
    assert result == {}


def test_get_espn_team_ids_returns_empty_on_api_failure():
    with patch("alpha.data.ingestion.soccer_injuries._get", return_value=None):
        result = get_espn_team_ids("epl")
    assert result == {}


def test_get_espn_team_ids_parses_scoreboard_correctly():
    fake_scoreboard = {
        "events": [{
            "competitions": [{
                "competitors": [
                    {"team": {"displayName": "Arsenal", "id": "359"}},
                    {"team": {"displayName": "Chelsea", "id": "363"}},
                ]
            }]
        }]
    }
    with patch("alpha.data.ingestion.soccer_injuries._get", return_value=fake_scoreboard):
        result = get_espn_team_ids("epl")
    assert result["Arsenal"] == 359
    assert result["Chelsea"] == 363


def test_get_espn_team_ids_skips_invalid_team_ids():
    fake_scoreboard = {
        "events": [{
            "competitions": [{
                "competitors": [
                    {"team": {"displayName": "Arsenal", "id": "bad_id"}},
                ]
            }]
        }]
    }
    with patch("alpha.data.ingestion.soccer_injuries._get", return_value=fake_scoreboard):
        result = get_espn_team_ids("epl")
    assert "Arsenal" not in result


# ---------------------------------------------------------------------------
# get_espn_out_players
# ---------------------------------------------------------------------------

def test_get_espn_out_players_returns_only_out():
    fake_response = {
        "injuries": [
            {"athlete": {"displayName": "Bukayo Saka"}, "status": "Out"},
            {"athlete": {"displayName": "Kai Havertz"}, "status": "Questionable"},
            {"athlete": {"displayName": "Martin Odegaard"}, "status": "Day-To-Day"},
        ]
    }
    with patch("alpha.data.ingestion.soccer_injuries._get", return_value=fake_response):
        result = get_espn_out_players("Arsenal", 359, "epl")
    assert result == ["Bukayo Saka"]


def test_get_espn_out_players_returns_empty_on_api_failure():
    with patch("alpha.data.ingestion.soccer_injuries._get", return_value=None):
        result = get_espn_out_players("Arsenal", 359, "epl")
    assert result == []


def test_get_espn_out_players_returns_empty_on_unknown_league():
    result = get_espn_out_players("Arsenal", 359, "xyz_unknown")
    assert result == []


def test_get_espn_out_players_returns_empty_when_no_injuries():
    with patch("alpha.data.ingestion.soccer_injuries._get", return_value={"injuries": []}):
        result = get_espn_out_players("Arsenal", 359, "epl")
    assert result == []


# ---------------------------------------------------------------------------
# get_team_injury_impact
# ---------------------------------------------------------------------------

def test_injury_impact_returns_empty_when_no_team_ids():
    with patch("alpha.data.ingestion.soccer_injuries.get_espn_team_ids", return_value={}):
        result = get_team_injury_impact("epl")
    assert result == {}


def test_injury_impact_returns_empty_when_no_players_out():
    fake_team_ids = {"Arsenal": 359, "Chelsea": 363}
    with patch("alpha.data.ingestion.soccer_injuries.get_espn_team_ids",
               return_value=fake_team_ids), \
         patch("alpha.data.ingestion.soccer_injuries.get_espn_out_players",
               return_value=[]):
        result = get_team_injury_impact("epl")
    assert result == {}


def test_injury_impact_aggregates_goals_lost():
    fake_team_ids = {"Arsenal": 359}
    with patch("alpha.data.ingestion.soccer_injuries.get_espn_team_ids",
               return_value=fake_team_ids), \
         patch("alpha.data.ingestion.soccer_injuries.get_espn_out_players",
               return_value=["Bukayo Saka"]), \
         patch("alpha.data.ingestion.soccer_injuries._load_player_stats",
               return_value={"Bukayo Saka": {"goals": 0.5, "assists": 0.3}}):
        result = get_team_injury_impact("epl")
    assert "Arsenal" in result
    assert result["Arsenal"]["goals_lost"] == pytest.approx(0.5)
    assert result["Arsenal"]["assists_lost"] == pytest.approx(0.3)


def test_injury_impact_uses_fallback_for_unknown_player():
    fake_team_ids = {"Arsenal": 359}
    with patch("alpha.data.ingestion.soccer_injuries.get_espn_team_ids",
               return_value=fake_team_ids), \
         patch("alpha.data.ingestion.soccer_injuries.get_espn_out_players",
               return_value=["Unknown Player XYZ"]), \
         patch("alpha.data.ingestion.soccer_injuries._load_player_stats",
               return_value={}):
        result = get_team_injury_impact("epl")
    assert "Arsenal" in result
    assert result["Arsenal"]["goals_lost"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _fuzzy_match_player
# ---------------------------------------------------------------------------

def test_fuzzy_match_player_matches_by_last_name():
    stats_map = {"Bukayo Saka": {"goals": 0.5, "assists": 0.3}}
    result = _fuzzy_match_player("B. Saka", stats_map)
    assert result is not None
    assert result["goals"] == 0.5


def test_fuzzy_match_player_returns_none_on_no_match():
    stats_map = {"Bukayo Saka": {"goals": 0.5}}
    result = _fuzzy_match_player("Erling Haaland", stats_map)
    assert result is None
