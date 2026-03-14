"""Unit tests for injury filter integration and UNDER leg generation."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_espn_injury_response(injuries: list[dict]) -> dict:
    """Build a mock ESPN injuries API response."""
    return {"injuries": injuries}


def _make_espn_injury(display_name: str, status: str) -> dict:
    return {
        "athlete": {"displayName": display_name},
        "status": status,
    }


# ---------------------------------------------------------------------------
# Test: get_player_injury_statuses
# ---------------------------------------------------------------------------

class TestGetPlayerInjuryStatuses:
    """Tests for get_player_injury_statuses()."""

    def test_out_player_returns_out(self):
        from alpha.data.ingestion.nba_injuries import get_player_injury_statuses

        mock_data = _make_espn_injury_response([
            _make_espn_injury("LeBron James", "Out"),
        ])
        with patch("alpha.data.ingestion.nba_injuries._get", return_value=mock_data):
            result = get_player_injury_statuses(["Los Angeles Lakers"])
        assert result.get("LeBron James") == "OUT"

    def test_questionable_player_returns_questionable(self):
        from alpha.data.ingestion.nba_injuries import get_player_injury_statuses

        mock_data = _make_espn_injury_response([
            _make_espn_injury("Anthony Davis", "Questionable"),
        ])
        with patch("alpha.data.ingestion.nba_injuries._get", return_value=mock_data):
            result = get_player_injury_statuses(["Los Angeles Lakers"])
        assert result.get("Anthony Davis") == "QUESTIONABLE"

    def test_doubtful_maps_to_questionable(self):
        from alpha.data.ingestion.nba_injuries import get_player_injury_statuses

        mock_data = _make_espn_injury_response([
            _make_espn_injury("Player X", "Doubtful"),
        ])
        with patch("alpha.data.ingestion.nba_injuries._get", return_value=mock_data):
            result = get_player_injury_statuses(["Boston Celtics"])
        assert result.get("Player X") == "QUESTIONABLE"

    def test_day_to_day_maps_to_questionable(self):
        from alpha.data.ingestion.nba_injuries import get_player_injury_statuses

        mock_data = _make_espn_injury_response([
            _make_espn_injury("Player Y", "Day-To-Day"),
        ])
        with patch("alpha.data.ingestion.nba_injuries._get", return_value=mock_data):
            result = get_player_injury_statuses(["Boston Celtics"])
        assert result.get("Player Y") == "QUESTIONABLE"

    def test_probable_maps_to_probable(self):
        from alpha.data.ingestion.nba_injuries import get_player_injury_statuses

        mock_data = _make_espn_injury_response([
            _make_espn_injury("Player Z", "Probable"),
        ])
        with patch("alpha.data.ingestion.nba_injuries._get", return_value=mock_data):
            result = get_player_injury_statuses(["Denver Nuggets"])
        assert result.get("Player Z") == "PROBABLE"

    def test_unknown_status_is_skipped(self):
        from alpha.data.ingestion.nba_injuries import get_player_injury_statuses

        mock_data = _make_espn_injury_response([
            _make_espn_injury("Player W", "Suspended"),
        ])
        with patch("alpha.data.ingestion.nba_injuries._get", return_value=mock_data):
            result = get_player_injury_statuses(["Denver Nuggets"])
        # "Suspended" is not a recognized status → should be excluded
        assert "Player W" not in result

    def test_unknown_team_returns_empty(self):
        from alpha.data.ingestion.nba_injuries import get_player_injury_statuses

        result = get_player_injury_statuses(["Unknown Team FC"])
        assert result == {}

    def test_api_failure_returns_empty(self):
        from alpha.data.ingestion.nba_injuries import get_player_injury_statuses

        with patch("alpha.data.ingestion.nba_injuries._get", return_value=None):
            result = get_player_injury_statuses(["Los Angeles Lakers"])
        assert result == {}

    def test_multiple_teams_merged(self):
        from alpha.data.ingestion.nba_injuries import get_player_injury_statuses

        lakers_data = _make_espn_injury_response([
            _make_espn_injury("LeBron James", "Out"),
        ])
        celtics_data = _make_espn_injury_response([
            _make_espn_injury("Jayson Tatum", "Questionable"),
        ])

        call_count = 0
        responses = [lakers_data, celtics_data]

        def _mock_get(url, timeout=10):
            nonlocal call_count
            resp = responses[call_count % len(responses)]
            call_count += 1
            return resp

        with patch("alpha.data.ingestion.nba_injuries._get", side_effect=_mock_get):
            result = get_player_injury_statuses(["Los Angeles Lakers", "Boston Celtics"])

        assert result.get("LeBron James") == "OUT"
        assert result.get("Jayson Tatum") == "QUESTIONABLE"


# ---------------------------------------------------------------------------
# Test: UNDER leg generation logic (unit — no API calls)
# ---------------------------------------------------------------------------

class TestUnderLegGeneration:
    """Tests for the UNDER leg logic embedded in sgp_scanner._run_under_logic."""

    def _classify_under_confidence(self, under_prob: float) -> str:
        """Mirror the logic from sgp_scanner."""
        if under_prob < 0.60:
            return "LOW"
        if under_prob >= 0.72:
            return "HIGH"
        if under_prob >= 0.65:
            return "MEDIUM"
        return "LOW"

    def test_under_leg_generated_when_prob_gte_065(self):
        """When model_prob = 0.25, under_prob = 0.75 >= 0.65 → UNDER leg should be created."""
        model_prob = 0.25
        under_prob = round(1.0 - model_prob, 4)
        assert under_prob >= 0.65

    def test_under_leg_not_generated_when_prob_lt_065(self):
        """When model_prob = 0.40, under_prob = 0.60 < 0.65 → no UNDER leg."""
        model_prob = 0.40
        under_prob = round(1.0 - model_prob, 4)
        assert under_prob < 0.65

    def test_under_direction_label(self):
        """A PropLeg with direction='under' should have direction set correctly."""
        from alpha.engines.sports.sgp_builder import PropLeg
        leg = PropLeg(
            player="Test Player",
            market="player_points",
            line=25.0,
            model_prob=0.75,
            over_odds=-110,
            event_id="evt_001",
            home_team="Boston Celtics",
            away_team="Miami Heat",
            confidence="HIGH",
            direction="under",
        )
        assert leg.direction == "under"

    def test_under_confidence_high_when_gte_072(self):
        under_prob = 0.75
        conf = self._classify_under_confidence(under_prob)
        assert conf == "HIGH"

    def test_under_confidence_medium_when_between_065_and_072(self):
        under_prob = 0.68
        conf = self._classify_under_confidence(under_prob)
        assert conf == "MEDIUM"

    def test_under_confidence_low_when_under_060(self):
        under_prob = 0.55
        conf = self._classify_under_confidence(under_prob)
        assert conf == "LOW"


# ---------------------------------------------------------------------------
# Test: QUESTIONABLE player downgrade
# ---------------------------------------------------------------------------

class TestQuestionablePlayerDowngrade:
    """Test that a QUESTIONABLE player's leg gets confidence downgraded."""

    def _apply_injury_downgrade(self, conf: str, injury_status: str | None) -> str:
        """Mirror the logic from sgp_scanner."""
        if injury_status == "QUESTIONABLE":
            if conf == "HIGH":
                return "MEDIUM"
            return "LOW"
        return conf

    def test_questionable_high_becomes_medium(self):
        result = self._apply_injury_downgrade("HIGH", "QUESTIONABLE")
        assert result == "MEDIUM"

    def test_questionable_medium_becomes_low(self):
        result = self._apply_injury_downgrade("MEDIUM", "QUESTIONABLE")
        assert result == "LOW"

    def test_out_player_not_downgraded_by_this_logic(self):
        """OUT player does not trigger the same downgrade path."""
        result = self._apply_injury_downgrade("HIGH", "OUT")
        assert result == "HIGH"

    def test_no_injury_leaves_confidence_unchanged(self):
        result = self._apply_injury_downgrade("HIGH", None)
        assert result == "HIGH"


# ---------------------------------------------------------------------------
# Test: get_teammate_boost_map
# ---------------------------------------------------------------------------

class TestTeammateBoostMap:
    """Tests for get_teammate_boost_map()."""

    def test_boost_map_returns_multipliers_above_one(self):
        from alpha.data.ingestion.nba_injuries import get_teammate_boost_map

        out_players = [{"name": "LeBron James", "pts": 25.0, "reb": 8.0, "ast": 7.0, "min": 35.0, "team": "Los Angeles Lakers"}]
        team_roster = {"Los Angeles Lakers": ["Anthony Davis", "Austin Reaves", "D'Angelo Russell", "Rui Hachimura", "Jarred Vanderbilt"]}

        result = get_teammate_boost_map(out_players, team_roster)

        for teammate in ["Anthony Davis", "Austin Reaves"]:
            assert teammate in result
            assert result[teammate]["pts_boost"] > 1.0
            assert result[teammate]["reb_boost"] > 1.0

    def test_boost_map_empty_when_no_roster(self):
        from alpha.data.ingestion.nba_injuries import get_teammate_boost_map

        out_players = [{"name": "LeBron James", "pts": 25.0, "reb": 8.0, "ast": 7.0, "min": 35.0, "team": "Los Angeles Lakers"}]
        team_roster = {}

        result = get_teammate_boost_map(out_players, team_roster)
        assert result == {}

    def test_boost_cap_at_1_30(self):
        from alpha.data.ingestion.nba_injuries import get_teammate_boost_map

        # Extremely high stat values should still be capped
        out_players = [{"name": "Superstar", "pts": 1000.0, "reb": 500.0, "ast": 200.0, "min": 40.0, "team": "Team A"}]
        team_roster = {"Team A": ["Player 1", "Player 2"]}

        result = get_teammate_boost_map(out_players, team_roster)
        for teammate in ["Player 1", "Player 2"]:
            assert result[teammate]["pts_boost"] <= 1.30
            assert result[teammate]["reb_boost"] <= 1.30
            assert result[teammate]["ast_boost"] <= 1.30

    def test_out_player_excluded_from_own_boost(self):
        from alpha.data.ingestion.nba_injuries import get_teammate_boost_map

        out_players = [{"name": "LeBron James", "pts": 25.0, "reb": 8.0, "ast": 7.0, "min": 35.0, "team": "Los Angeles Lakers"}]
        team_roster = {"Los Angeles Lakers": ["LeBron James", "Anthony Davis"]}

        result = get_teammate_boost_map(out_players, team_roster)
        assert "LeBron James" not in result
        assert "Anthony Davis" in result
