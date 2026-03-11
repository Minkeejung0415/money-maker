"""Tests for nba_injuries ESPN fallback and core functions."""
from unittest.mock import patch
import pytest
from alpha.data.ingestion.nba_injuries import (
    get_espn_out_players,
    get_team_injury_impact,
    _ESPN_TEAM_IDS,
)


# ---------------------------------------------------------------------------
# ESPN team ID mapping
# ---------------------------------------------------------------------------

def test_espn_team_ids_has_all_30_teams():
    assert len(_ESPN_TEAM_IDS) == 30


def test_espn_team_id_timberwolves():
    assert _ESPN_TEAM_IDS["Minnesota Timberwolves"] == 16


def test_espn_team_id_celtics():
    assert _ESPN_TEAM_IDS["Boston Celtics"] == 2


# ---------------------------------------------------------------------------
# get_espn_out_players
# ---------------------------------------------------------------------------

def test_espn_out_players_returns_only_out_status():
    """Only players with status 'out' should be returned."""
    fake_response = {
        "injuries": [
            {"athlete": {"displayName": "Anthony Edwards"}, "status": "Out"},
            {"athlete": {"displayName": "Rudy Gobert"}, "status": "Questionable"},
            {"athlete": {"displayName": "Jaden McDaniels"}, "status": "Day-To-Day"},
        ]
    }
    with patch("alpha.data.ingestion.nba_injuries._get", return_value=fake_response):
        result = get_espn_out_players("Minnesota Timberwolves")
    assert result == ["Anthony Edwards"]


def test_espn_out_players_returns_empty_for_unknown_team():
    """Unknown team name (no ESPN ID) returns [] without calling the API."""
    with patch("alpha.data.ingestion.nba_injuries._get") as mock_get:
        result = get_espn_out_players("Unknown Team XYZ")
    assert result == []
    mock_get.assert_not_called()


def test_espn_out_players_returns_empty_on_api_failure():
    """Network failure should return [] without raising."""
    with patch("alpha.data.ingestion.nba_injuries._get", return_value=None):
        result = get_espn_out_players("Boston Celtics")
    assert result == []


def test_espn_out_players_returns_empty_when_no_injuries():
    with patch("alpha.data.ingestion.nba_injuries._get", return_value={"injuries": []}):
        result = get_espn_out_players("Los Angeles Lakers")
    assert result == []


# ---------------------------------------------------------------------------
# get_team_injury_impact — ESPN supplement wiring
# ---------------------------------------------------------------------------

def test_injury_impact_uses_espn_when_cdn_inactive_list_empty():
    """
    When NBA CDN boxscore has no inactive players (game not started),
    ESPN pre-game report should be used as fallback.
    """
    fake_game_ids = [
        {"game_id": "0022500001", "home": "Minnesota Timberwolves", "away": "Boston Celtics",
         "home_tricode": "MIN", "away_tricode": "BOS"}
    ]
    # CDN boxscore returns nothing (pre-game, inactive list not populated)
    with patch("alpha.data.ingestion.nba_injuries.get_today_game_ids", return_value=fake_game_ids), \
         patch("alpha.data.ingestion.nba_injuries.get_inactive_players", return_value={}), \
         patch("alpha.data.ingestion.nba_injuries.get_player_stats_map", return_value={
             "Anthony Edwards": {"pts": 27.0, "reb": 5.5, "ast": 5.0, "min": 36.0, "team": "MIN"}
         }), \
         patch("alpha.data.ingestion.nba_injuries.get_espn_out_players",
               side_effect=lambda t: ["Anthony Edwards"] if t == "Minnesota Timberwolves" else []):
        result = get_team_injury_impact()

    assert "Minnesota Timberwolves" in result
    assert result["Minnesota Timberwolves"]["pts_lost"] == pytest.approx(27.0)


def test_injury_impact_cdn_takes_precedence_over_espn():
    """
    When NBA CDN boxscore has inactive players, ESPN should not be called
    for that team (CDN is authoritative once the list is populated).
    """
    fake_game_ids = [
        {"game_id": "0022500001", "home": "Minnesota Timberwolves", "away": "Boston Celtics",
         "home_tricode": "MIN", "away_tricode": "BOS"}
    ]
    cdn_inactive = {"Minnesota Timberwolves": ["Anthony Edwards"]}

    with patch("alpha.data.ingestion.nba_injuries.get_today_game_ids", return_value=fake_game_ids), \
         patch("alpha.data.ingestion.nba_injuries.get_inactive_players", return_value=cdn_inactive), \
         patch("alpha.data.ingestion.nba_injuries.get_player_stats_map", return_value={
             "Anthony Edwards": {"pts": 27.0, "reb": 5.5, "ast": 5.0, "min": 36.0, "team": "MIN"}
         }), \
         patch("alpha.data.ingestion.nba_injuries.get_espn_out_players") as mock_espn:
        result = get_team_injury_impact()

    # ESPN should NOT have been called for MIN (CDN already had data)
    for call in mock_espn.call_args_list:
        assert call.args[0] != "Minnesota Timberwolves"
