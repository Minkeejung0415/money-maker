"""
Tests for NBA contextual evaluators:
  - PositionFilter
  - SharedMinutesFilter
  - PaintDeterrenceEvaluator
  - FoulTroubleRiskEvaluator
  - AdvancedOpponentStats
  - PropContextEvaluator
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from alpha.engines.sports.nba_context import (
    AdvancedOpponentStats,
    ContextFlags,
    FoulTroubleRiskEvaluator,
    PaintDeterrenceEvaluator,
    PositionFilter,
    PropContextEvaluator,
    SharedMinutesFilter,
)


# ---------------------------------------------------------------------------
# Helpers — mock cache
# ---------------------------------------------------------------------------


def _mock_cache():
    cache = MagicMock()
    cache.resolve_player_id.return_value = 12345
    cache.fetch_player_info.return_value = {
        "player_id": 12345,
        "position": "Guard",
        "team_id": 1,
        "team_name": "Test Team",
        "team_abbreviation": "TST",
    }
    cache.fetch_league_dash_player_stats.return_value = [
        {
            "PLAYER_NAME": "Test Guard",
            "PLAYER_ID": 12345,
            "TEAM_ABBREVIATION": "TST",
            "TEAM_NAME": "Test Team",
            "REB": 3.5,
            "PTS": 18.0,
            "AST": 5.0,
            "BLK": 0.5,
            "PF": 2.5,
            "FTA": 3.0,
            "FGA": 12.0,
            "FG3_PCT": 0.38,
            "MIN": 30.0,
        },
        {
            "PLAYER_NAME": "Rim Runner",
            "PLAYER_ID": 99999,
            "TEAM_ABBREVIATION": "OPP",
            "TEAM_NAME": "Opponent Team",
            "REB": 8.0,
            "PTS": 14.0,
            "AST": 1.0,
            "BLK": 0.3,
            "PF": 3.8,
            "FTA": 5.0,
            "FGA": 10.0,
            "FG3_PCT": 0.10,
            "MIN": 28.0,
        },
        {
            "PLAYER_NAME": "Elite Blocker",
            "PLAYER_ID": 88888,
            "TEAM_ABBREVIATION": "DEF",
            "TEAM_NAME": "Defense Team",
            "REB": 10.0,
            "PTS": 12.0,
            "AST": 1.5,
            "BLK": 4.0,
            "PF": 2.0,
            "FTA": 2.0,
            "FGA": 8.0,
            "FG3_PCT": 0.00,
            "MIN": 32.0,
        },
        {
            "PLAYER_NAME": "FT Drawer",
            "PLAYER_ID": 77777,
            "TEAM_ABBREVIATION": "ATK",
            "TEAM_NAME": "Attack Team",
            "REB": 4.0,
            "PTS": 28.0,
            "AST": 8.0,
            "BLK": 0.2,
            "PF": 1.5,
            "FTA": 9.0,
            "FGA": 20.0,
            "FG3_PCT": 0.34,
            "MIN": 36.0,
        },
        {
            "PLAYER_NAME": "Foul Prone Defender",
            "PLAYER_ID": 66666,
            "TEAM_ABBREVIATION": "DEF",
            "TEAM_NAME": "Defense Team",
            "REB": 5.0,
            "PTS": 10.0,
            "AST": 2.0,
            "BLK": 1.0,
            "PF": 4.2,
            "FTA": 2.0,
            "FGA": 8.0,
            "FG3_PCT": 0.30,
            "MIN": 28.0,
        },
    ]
    cache.fetch_league_dash_team_stats.return_value = [
        {
            "TEAM_NAME": "Test Team",
            "TEAM_ABBREVIATION": "TST",
            "PACE": 102.0,
            "DEF_RATING": 110.0,
            "FGA": 85.0,
            "FG3A": 30.0,
            "OPP_FTA": 22.0,
            "OPP_FGA": 85.0,
            "OPP_PTS_PAINT": 50.0,
            "W_PCT": 0.55,
        },
        {
            "TEAM_NAME": "Defense Team",
            "TEAM_ABBREVIATION": "DEF",
            "PACE": 96.0,
            "DEF_RATING": 105.0,
            "FGA": 80.0,
            "FG3A": 25.0,
            "OPP_FTA": 18.0,
            "OPP_FGA": 80.0,
            "OPP_PTS_PAINT": 42.0,
            "W_PCT": 0.60,
        },
    ]
    cache.fetch_league_dash_pt_defend.return_value = [
        {
            "PLAYER_NAME": "Elite Blocker",
            "CLOSE_DEF_PERSON_ID": 88888,
            "D_FG_PCT": 0.52,
        },
    ]
    cache.fetch_player_game_logs.return_value = [
        {"MIN": "32:00", "PTS": 18, "REB": 4, "AST": 5}
    ] * 20
    cache.fetch_player_dash_pt_shots.return_value = [
        {"SHOT_DIST_RANGE": "Less Than 6 Ft", "FGA": 80},
        {"SHOT_DIST_RANGE": "6-10 Ft", "FGA": 30},
        {"SHOT_DIST_RANGE": "10-16 Ft", "FGA": 20},
        {"SHOT_DIST_RANGE": "16+ Ft", "FGA": 20},
    ]
    return cache


# ---------------------------------------------------------------------------
# PositionFilter
# ---------------------------------------------------------------------------


class TestPositionFilter:
    def test_non_rebound_market_passes(self):
        pf = PositionFilter(cache=_mock_cache())
        assert pf.should_filter("Test Guard", "player_points") is False

    def test_guard_low_reb_avg_filtered(self):
        cache = _mock_cache()
        cache.fetch_player_info.return_value = {"position": "Guard"}
        pf = PositionFilter(cache=cache)
        assert pf.should_filter("Test Guard", "player_rebounds") is True

    def test_guard_high_reb_avg_passes(self):
        cache = _mock_cache()
        cache.fetch_player_info.return_value = {"position": "Guard"}
        cache.fetch_league_dash_player_stats.return_value = [
            {"PLAYER_NAME": "Rebound Guard", "REB": 7.5}
        ]
        pf = PositionFilter(cache=cache)
        assert pf.should_filter("Rebound Guard", "player_rebounds") is False

    def test_center_reb_not_filtered(self):
        cache = _mock_cache()
        cache.fetch_player_info.return_value = {"position": "Center"}
        pf = PositionFilter(cache=cache)
        assert pf.should_filter("Big Center", "player_rebounds") is False

    def test_sf_low_reb_filtered(self):
        cache = _mock_cache()
        cache.fetch_player_info.return_value = {"position": "Small Forward"}
        pf = PositionFilter(cache=cache)
        assert pf.should_filter("Test Guard", "player_rebounds") is True

    def test_no_cache_does_not_filter(self):
        pf = PositionFilter(cache=None)
        assert pf.should_filter("Anyone", "player_rebounds") is False


# ---------------------------------------------------------------------------
# SharedMinutesFilter
# ---------------------------------------------------------------------------


class TestSharedMinutesFilter:
    def test_default_weight_is_one(self):
        smf = SharedMinutesFilter(cache=None)
        assert smf.get_shared_minutes_weight("Player A") == 1.0

    def test_weight_between_0_and_1(self):
        smf = SharedMinutesFilter(cache=_mock_cache())
        w = smf.get_shared_minutes_weight("Player A", "Defender B")
        assert 0.0 <= w <= 1.0

    def test_no_defender_returns_one(self):
        smf = SharedMinutesFilter(cache=_mock_cache())
        assert smf.get_shared_minutes_weight("Player A", None) == 1.0


# ---------------------------------------------------------------------------
# PaintDeterrenceEvaluator
# ---------------------------------------------------------------------------


class TestPaintDeterrenceEvaluator:
    def test_no_cache_returns_zero(self):
        pde = PaintDeterrenceEvaluator(cache=None)
        assert pde.evaluate("Any Player", "Any Team") == 0.0

    def test_elite_protector_identified(self):
        cache = _mock_cache()
        pde = PaintDeterrenceEvaluator(cache=cache)
        protectors = pde._get_elite_protectors()
        assert "Elite Blocker" in protectors

    def test_rim_dependent_vs_protector_gets_discount(self):
        cache = _mock_cache()
        cache.resolve_player_id.return_value = 99999
        pde = PaintDeterrenceEvaluator(cache=cache)
        discount = pde.evaluate("Rim Runner", "Defense Team", shared_minutes=25.0)
        assert discount >= 0.08
        assert discount <= 0.18

    def test_no_protector_no_discount(self):
        cache = _mock_cache()
        cache.fetch_league_dash_player_stats.return_value = [
            {"PLAYER_NAME": "Nobody", "BLK": 0.5, "TEAM_ABBREVIATION": "XXX"}
        ]
        pde = PaintDeterrenceEvaluator(cache=cache)
        discount = pde.evaluate("Rim Runner", "No Protector Team")
        assert discount == 0.0

    def test_low_shared_minutes_no_discount(self):
        cache = _mock_cache()
        cache.resolve_player_id.return_value = 99999
        pde = PaintDeterrenceEvaluator(cache=cache)
        discount = pde.evaluate("Rim Runner", "Defense Team", shared_minutes=10.0)
        assert discount == 0.0

    def test_team_rim_dependency(self):
        cache = _mock_cache()
        pde = PaintDeterrenceEvaluator(cache=cache)
        dep = pde.get_team_rim_dependency("Test Team")
        assert 0.0 <= dep <= 1.0

    def test_severity_calc_bounded(self):
        result = PaintDeterrenceEvaluator._calc_severity(
            {"blk_per36": 5.0}, rim_pct=0.65, shared_minutes=30.0
        )
        assert 0.08 <= result <= 0.18


# ---------------------------------------------------------------------------
# FoulTroubleRiskEvaluator
# ---------------------------------------------------------------------------


class TestFoulTroubleRiskEvaluator:
    def test_no_cache_returns_low(self):
        fte = FoulTroubleRiskEvaluator(cache=None)
        result = fte.evaluate_defender("Defender", "Matchup")
        assert result["risk"] == "LOW"

    def test_foul_prone_vs_ft_drawer_is_high(self):
        cache = _mock_cache()
        fte = FoulTroubleRiskEvaluator(cache=cache)
        result = fte.evaluate_defender("Foul Prone Defender", "FT Drawer")
        assert result["risk"] == "HIGH"
        assert result["discount"] > 0
        assert result["boost"] > 0

    def test_non_foul_prone_vs_non_drawer_is_low(self):
        cache = _mock_cache()
        fte = FoulTroubleRiskEvaluator(cache=cache)
        result = fte.evaluate_defender("Test Guard", "Elite Blocker")
        # Test Guard PF=2.5 (not foul-prone), Elite Blocker FTA/FGA=2/8=0.25 (not drawer)
        assert result["risk"] == "LOW"
        assert result["discount"] == 0.0

    def test_team_foul_exposure_without_handler(self):
        cache = _mock_cache()
        fte = FoulTroubleRiskEvaluator(cache=cache)
        result = fte.get_team_foul_exposure("Defense Team")
        assert result["risk"] == "LOW"

    def test_team_foul_exposure_with_handler(self):
        cache = _mock_cache()
        fte = FoulTroubleRiskEvaluator(cache=cache)
        result = fte.get_team_foul_exposure("Defense Team", "FT Drawer")
        assert result["risk"] in ("MEDIUM", "HIGH")


# ---------------------------------------------------------------------------
# AdvancedOpponentStats
# ---------------------------------------------------------------------------


class TestAdvancedOpponentStats:
    def test_no_cache_returns_defaults(self):
        aos = AdvancedOpponentStats(cache=None)
        adj = aos.get_opponent_adjustments("Any Team")
        assert adj["pace_factor"] == 1.0
        assert adj["def_factor"] == 1.0

    def test_pace_adjustment_positive_for_fast_team(self):
        cache = _mock_cache()
        aos = AdvancedOpponentStats(cache=cache)
        adj = aos.get_pace_adjustment("Test Team")
        # Test Team has pace=102 vs avg=100 → positive adjustment
        assert adj > 0

    def test_pace_adjustment_negative_for_slow_team(self):
        cache = _mock_cache()
        aos = AdvancedOpponentStats(cache=cache)
        adj = aos.get_pace_adjustment("Defense Team")
        # Defense Team has pace=96 vs avg=100 → negative adjustment
        assert adj < 0

    def test_def_rating_adjustment(self):
        cache = _mock_cache()
        aos = AdvancedOpponentStats(cache=cache)
        adj = aos.get_def_rating_adjustment("Defense Team")
        # Defense Team has DEF_RATING=105 (good) vs avg=112
        # League avg / opp = 112/105 > 1 → positive (offense benefits against bad D)
        assert adj > 0

    def test_opponent_adjustments_returns_all_keys(self):
        cache = _mock_cache()
        aos = AdvancedOpponentStats(cache=cache)
        adj = aos.get_opponent_adjustments("Test Team")
        assert "pace" in adj
        assert "pace_factor" in adj
        assert "def_rating" in adj
        assert "def_factor" in adj
        assert "opp_fta_rate" in adj
        assert "opp_pitp_factor" in adj


# ---------------------------------------------------------------------------
# ContextFlags
# ---------------------------------------------------------------------------


class TestContextFlags:
    def test_total_adjustment_default_zero(self):
        flags = ContextFlags()
        assert flags.total_adjustment == 0.0

    def test_total_adjustment_combines(self):
        flags = ContextFlags(
            paint_deterrence_pct=0.10,
            pace_adjustment=0.05,
            foul_trouble_boost=0.03,
        )
        expected = -0.10 + 0.05 + 0.03
        assert abs(flags.total_adjustment - expected) < 1e-6

    def test_as_dict_has_all_keys(self):
        flags = ContextFlags()
        d = flags.as_dict()
        assert "position_filtered" in d
        assert "shared_minutes_weight" in d
        assert "paint_deterrence_pct" in d
        assert "total_adjustment" in d


# ---------------------------------------------------------------------------
# PropContextEvaluator (integration)
# ---------------------------------------------------------------------------


class TestPropContextEvaluator:
    def test_evaluate_returns_none_for_filtered_prop(self):
        cache = _mock_cache()
        cache.fetch_player_info.return_value = {"position": "Guard"}
        pce = PropContextEvaluator(cache=cache)
        result = pce.evaluate_single({
            "player": "Test Guard",
            "market": "player_rebounds",
            "line": 4.5,
            "model_prob": 0.55,
            "over_odds": -110,
            "opponent_team": "Any Team",
        })
        assert result is None

    def test_evaluate_returns_adjusted_prob(self):
        cache = _mock_cache()
        cache.fetch_player_info.return_value = {"position": "Center"}
        pce = PropContextEvaluator(cache=cache)
        result = pce.evaluate_single({
            "player": "Big Center",
            "market": "player_points",
            "line": 20.5,
            "model_prob": 0.65,
            "over_odds": -110,
            "opponent_team": "Defense Team",
        })
        assert result is not None
        assert "adjusted_prob" in result
        assert "ev" in result
        assert "edge" in result
        assert "flags" in result
        assert 0.01 <= result["adjusted_prob"] <= 0.99

    def test_evaluate_props_batch(self):
        cache = _mock_cache()
        cache.fetch_player_info.return_value = {"position": "Center"}
        pce = PropContextEvaluator(cache=cache)
        props = [
            {
                "player": "Player A",
                "market": "player_points",
                "line": 22.5,
                "model_prob": 0.60,
                "over_odds": -110,
                "opponent_team": "Test Team",
            },
            {
                "player": "Player B",
                "market": "player_assists",
                "line": 5.5,
                "model_prob": 0.55,
                "over_odds": -115,
                "opponent_team": "Defense Team",
            },
        ]
        results = pce.evaluate_props(props)
        assert len(results) == 2
        for r in results:
            assert "adjusted_prob" in r
            assert "ev" in r

    def test_no_cache_still_works(self):
        pce = PropContextEvaluator(cache=None)
        result = pce.evaluate_single({
            "player": "Anyone",
            "market": "player_points",
            "line": 20.5,
            "model_prob": 0.60,
            "over_odds": -110,
            "opponent_team": "Any Team",
        })
        assert result is not None
        assert abs(result["adjusted_prob"] - 0.60) < 0.05

    def test_foul_trouble_high_when_defender_resolved(self):
        """Bug 1 regression: resolved foul-prone defender + elite FT drawer → HIGH."""
        cache = _mock_cache()
        cache.fetch_player_info.return_value = {"position": "Center"}
        cache.fetch_matchup_defender = MagicMock(return_value="Foul Prone Defender")

        per36 = cache.fetch_league_dash_player_stats.return_value
        for row in per36:
            if row["PLAYER_NAME"] == "Foul Prone Defender":
                row["PF"] = 4.5

        ft_drawer_row = {
            "PLAYER_NAME": "Star Scorer",
            "PLAYER_ID": 55555,
            "TEAM_ABBREVIATION": "ATK",
            "TEAM_NAME": "Attack Team",
            "REB": 5.0,
            "PTS": 30.0,
            "AST": 6.0,
            "BLK": 0.1,
            "PF": 1.0,
            "FTA": 10.0,
            "FGA": 22.0,
            "FG3_PCT": 0.37,
            "MIN": 36.0,
        }
        per36.append(ft_drawer_row)

        pce = PropContextEvaluator(cache=cache)
        result = pce.evaluate_single({
            "player": "Star Scorer",
            "market": "player_points",
            "line": 28.5,
            "model_prob": 0.55,
            "over_odds": -110,
            "opponent_team": "Defense Team",
        })
        assert result is not None
        flags = result["flags"]
        assert flags["foul_trouble_risk"] == "HIGH"
        assert flags["foul_trouble_boost"] > 0
