"""
Tests for ParlayConstructor — parlay math, EV, Kelly, and bet type recommendations.
"""
from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest

from alpha.engines.sports.parlay_constructor import (
    BetRecommendation,
    ParlayConstructor,
    PickOutput,
)


@pytest.fixture
def ctor():
    return ParlayConstructor(
        bankroll=10_000.0,
        kelly_fraction=0.25,
        max_legs=4,
        min_edge=0.04,
    )


# ---------------------------------------------------------------------------
# Combined probability
# ---------------------------------------------------------------------------


class TestCombinedProbability:
    def test_product_of_two(self):
        assert ParlayConstructor.true_combined_probability([0.60, 0.60]) == pytest.approx(0.36)

    def test_product_of_three(self):
        result = ParlayConstructor.true_combined_probability([0.60, 0.60, 0.60])
        assert result == pytest.approx(0.216, rel=1e-3)

    def test_product_of_five(self):
        result = ParlayConstructor.true_combined_probability([0.60] * 5)
        assert result == pytest.approx(0.60**5, rel=1e-6)

    def test_product_of_nine(self):
        result = ParlayConstructor.true_combined_probability([0.60] * 9)
        assert result == pytest.approx(0.60**9, rel=1e-6)
        # Should be ~1% — matches the spec's example
        assert result < 0.015

    def test_single_leg(self):
        assert ParlayConstructor.true_combined_probability([0.65]) == 0.65

    def test_empty(self):
        assert ParlayConstructor.true_combined_probability([]) == 1.0

    def test_certainty(self):
        assert ParlayConstructor.true_combined_probability([1.0, 1.0]) == 1.0

    def test_impossibility(self):
        assert ParlayConstructor.true_combined_probability([0.0, 0.50]) == 0.0


# ---------------------------------------------------------------------------
# Combined odds
# ---------------------------------------------------------------------------


class TestCombinedOdds:
    def test_product_of_decimal_odds(self):
        result = ParlayConstructor.combined_decimal_odds([1.909, 1.909])
        assert result == pytest.approx(1.909 * 1.909, rel=1e-3)

    def test_single_odds(self):
        assert ParlayConstructor.combined_decimal_odds([2.50]) == 2.50


# ---------------------------------------------------------------------------
# Expected Value
# ---------------------------------------------------------------------------


class TestExpectedValue:
    def test_ev_positive_when_edge(self):
        ev = ParlayConstructor.expected_value(0.60, 2.0)
        # ev = 0.60 * (2.0-1) - 0.40 = 0.60 - 0.40 = 0.20
        assert ev == pytest.approx(0.20)

    def test_ev_negative_when_no_edge(self):
        ev = ParlayConstructor.expected_value(0.40, 2.0)
        # ev = 0.40 * 1.0 - 0.60 = -0.20
        assert ev == pytest.approx(-0.20)

    def test_ev_zero_at_fair_odds(self):
        ev = ParlayConstructor.expected_value(0.50, 2.0)
        assert ev == pytest.approx(0.0)

    def test_ev_per_100_scales(self):
        ev100 = ParlayConstructor.ev_per_100(0.60, 2.0)
        assert ev100 == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Kelly fraction
# ---------------------------------------------------------------------------


class TestKellyFraction:
    def test_kelly_positive_with_edge(self, ctor):
        # Full Kelly: f = (bp - q) / b = (1*0.60 - 0.40)/1 = 0.20
        # Fractional (0.25x): 0.20 * 0.25 = 0.05
        k = ctor.kelly_fraction_calc(0.60, 2.0)
        assert k == pytest.approx(0.05, abs=0.001)

    def test_kelly_zero_without_edge(self, ctor):
        k = ctor.kelly_fraction_calc(0.40, 2.0)
        assert k == 0.0

    def test_kelly_stake_in_dollars(self, ctor):
        stake = ctor.kelly_stake(0.60, 2.0)
        assert stake > 0
        assert stake <= 500  # max 5% of $10k

    def test_kelly_never_negative(self, ctor):
        k = ctor.kelly_fraction_calc(0.10, 2.0)
        assert k >= 0.0


# ---------------------------------------------------------------------------
# Leg count advisor
# ---------------------------------------------------------------------------


class TestLegCountAdvisor:
    def test_leg_count_table(self, ctor):
        table = ctor.leg_count_table(0.60)
        assert table[1] == pytest.approx(0.60)
        assert table[2] == pytest.approx(0.36)
        assert table[3] == pytest.approx(0.216, rel=1e-3)
        assert table[5] == pytest.approx(0.60**5, rel=1e-3)
        assert table[9] < 0.015

    def test_recommend_max_4_by_default(self, ctor):
        probs = [0.60] * 6
        assert ctor.recommend_max_legs(probs) <= 4

    def test_recommend_higher_when_all_high_conf(self, ctor):
        probs = [0.72] * 6
        assert ctor.recommend_max_legs(probs) > 4

    def test_recommend_2_for_empty(self, ctor):
        assert ctor.recommend_max_legs([]) == 2

    def test_should_split_large_parlay(self, ctor):
        legs = [{"model_prob": 0.65 - i * 0.01} for i in range(6)]
        groups = ctor.should_split_parlay(legs, max_per_parlay=3)
        assert len(groups) == 2
        for g in groups:
            assert len(g) <= 3
            assert len(g) >= 2

    def test_small_parlay_not_split(self, ctor):
        legs = [{"model_prob": 0.65}, {"model_prob": 0.60}]
        groups = ctor.should_split_parlay(legs)
        assert len(groups) == 1


# ---------------------------------------------------------------------------
# Bet type recommendations
# ---------------------------------------------------------------------------



# Eligibility fields for picks that should pass the real-money gates
# (validated XGB-backed): required since the detailed-pick safety gating.
_ELIGIBLE = {"source": "xgb", "recommendation_eligible": True,
             "refusal_reasons": [], "projected_minutes": 33.0,
             "low_minutes_risk": 0.0}


class TestBetTypeRecommendations:
    def test_returns_recommendations(self, ctor):
        picks = [
            {"player": "A", "market": "player_points", "model_prob": 0.65,
             "adjusted_prob": 0.65, "over_odds": -110, "ev": 0.10, "edge": 0.12, **_ELIGIBLE},
            {"player": "B", "market": "player_rebounds", "model_prob": 0.60,
             "adjusted_prob": 0.60, "over_odds": -110, "ev": 0.06, "edge": 0.07, **_ELIGIBLE},
            {"player": "C", "market": "player_assists", "model_prob": 0.62,
             "adjusted_prob": 0.62, "over_odds": -105, "ev": 0.08, "edge": 0.09, **_ELIGIBLE},
        ]
        recs = ctor.recommend_bet_types(picks)
        assert len(recs) == 3  # single, 2-leg, 3-leg
        types = {r.bet_type for r in recs}
        assert "single" in types
        assert "2-leg parlay" in types
        assert "3-leg parlay" in types

    def test_empty_picks_returns_empty(self, ctor):
        assert ctor.recommend_bet_types([]) == []

    def test_single_bet_has_highest_win_prob(self, ctor):
        picks = [
            {"player": "A", "model_prob": 0.70, "adjusted_prob": 0.70,
             "over_odds": -110, "ev": 0.15, "edge": 0.18, **_ELIGIBLE},
            {"player": "B", "model_prob": 0.65, "adjusted_prob": 0.65,
             "over_odds": -110, "ev": 0.10, "edge": 0.12, **_ELIGIBLE},
        ]
        recs = ctor.recommend_bet_types(picks)
        single_recs = [r for r in recs if r.bet_type == "single"]
        parlay_recs = [r for r in recs if "parlay" in r.bet_type]
        assert single_recs[0].combined_win_prob > parlay_recs[0].combined_win_prob

    def test_warns_when_combined_prob_below_15_pct(self, ctor):
        picks = [
            {"player": f"P{i}", "model_prob": 0.40, "adjusted_prob": 0.40,
             "over_odds": -110, "ev": 0.01, "edge": 0.01, **_ELIGIBLE}
            for i in range(3)
        ]
        ctor._min_edge = 0.0  # allow all
        recs = ctor.recommend_bet_types(picks)
        three_leg = [r for r in recs if r.bet_type == "3-leg parlay"]
        if three_leg:
            # 0.40^3 = 0.064 < 0.15
            assert any("15%" in w for w in three_leg[0].warnings)

    def test_warns_when_single_ev_higher(self, ctor):
        picks = [
            {"player": "A", "model_prob": 0.80, "adjusted_prob": 0.80,
             "over_odds": -110, "ev": 0.30, "edge": 0.28},
            {"player": "B", "model_prob": 0.45, "adjusted_prob": 0.45,
             "over_odds": +200, "ev": -0.05, "edge": -0.08},
        ]
        ctor._min_edge = 0.0
        recs = ctor.recommend_bet_types(picks)
        parlays = [r for r in recs if "parlay" in r.bet_type]
        # Single should have higher EV; parlay should warn
        for p in parlays:
            if p.ev_per_100 < recs[0].ev_per_100 and recs[0].bet_type == "single":
                assert any("Single bet EV" in w for w in p.warnings)


# ---------------------------------------------------------------------------
# Correlated parlay EV
# ---------------------------------------------------------------------------


class TestCorrelatedParlayEv:
    def test_without_correlation_engine(self, ctor):
        legs = [
            {"player": "A", "model_prob": 0.65, "over_odds": -110, "market": "player_points"},
            {"player": "B", "model_prob": 0.60, "over_odds": -110, "market": "player_rebounds"},
        ]
        result = ctor.correlated_parlay_ev(legs)
        assert result["combined_prob"] == pytest.approx(0.65 * 0.60, rel=1e-3)
        assert "ev_per_100" in result
        assert "edge" in result

    def test_with_correlation_engine(self, ctor):
        corr = MagicMock()
        corr.adjust_multi_leg_prob.return_value = 0.42  # higher than naive 0.39
        legs = [
            {"player": "A", "model_prob": 0.65, "over_odds": -110, "market": "player_points"},
            {"player": "B", "model_prob": 0.60, "over_odds": -110, "market": "player_rebounds"},
        ]
        result = ctor.correlated_parlay_ev(legs, correlation_engine=corr)
        assert result["combined_prob"] == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


class TestOutputFormatting:
    def test_format_pick(self, ctor):
        prop = {
            "player": "Player X",
            "market": "player_points",
            "line": 24.5,
            "model_prob": 0.673,
            "adjusted_prob": 0.673,
            "over_odds": -110,
            "flags": {"pace_adjustment": 0.021, "paint_deterrence_pct": 0.0},
            # Kelly is only formatted for recommendation-eligible picks.
            **_ELIGIBLE,
        }
        output = ctor.format_pick(prop)
        assert "Player X" in output
        assert "Over 24.5 pts" in output
        assert "67.3%" in output
        assert "Kelly" in output

    def test_format_recommendation(self, ctor):
        rec = BetRecommendation(
            bet_type="2-leg parlay",
            legs=[],
            combined_win_prob=0.39,
            combined_decimal_odds=3.65,
            ev_per_100=8.50,
            edge=0.12,
            kelly_pct=0.03,
            kelly_stake=300.0,
            implied_prob=0.274,
        )
        output = ctor.format_recommendation(rec)
        assert "2-LEG PARLAY" in output
        assert "39.0%" in output

    def test_format_leg_count_table(self, ctor):
        output = ctor.format_leg_count_table(0.60)
        assert "60%" in output
        assert "2-leg" in output
        assert "recommended max" in output

    def test_pick_output_format(self):
        pick = PickOutput(
            player="Shai Gilgeous-Alexander",
            description="Over 30.5 pts",
            model_confidence=0.673,
            implied_odds_prob=0.524,
            edge=0.149,
            ev_per_100=8.20,
            kelly_pct=0.031,
            kelly_stake=310.0,
            flags={"pace_boost": 0.021},
        )
        text = pick.format()
        assert "Shai Gilgeous-Alexander" in text
        assert "Over 30.5 pts" in text
        assert "67.3%" in text
        assert "52.4%" in text
        assert "+14.9%" in text


# ---------------------------------------------------------------------------
# SGP Builder category diversity (integration sanity check)
# ---------------------------------------------------------------------------


class TestCategoryDiversityCap:
    def test_passes_with_2_same_category(self):
        from alpha.engines.sports.sgp_builder import SGPBuilder, PropLeg
        legs = [
            PropLeg("A", "player_points", 25.5, 0.65, -110, "e1", "H", "A", "HIGH"),
            PropLeg("B", "player_points", 22.5, 0.60, -110, "e1", "H", "A", "HIGH"),
        ]
        assert SGPBuilder._passes_category_diversity(legs) is True

    def test_fails_with_3_same_category(self):
        from alpha.engines.sports.sgp_builder import SGPBuilder, PropLeg
        legs = [
            PropLeg("A", "player_points", 25.5, 0.65, -110, "e1", "H", "A", "HIGH"),
            PropLeg("B", "player_points", 22.5, 0.60, -110, "e1", "H", "A", "HIGH"),
            PropLeg("C", "player_points", 20.5, 0.55, -110, "e1", "H", "A", "HIGH"),
        ]
        assert SGPBuilder._passes_category_diversity(legs) is False

    def test_enforce_drops_weakest(self):
        from alpha.engines.sports.sgp_builder import SGPBuilder, PropLeg
        legs = [
            PropLeg("A", "player_rebounds", 8.5, 0.70, -110, "e1", "H", "A", "HIGH"),
            PropLeg("B", "player_rebounds", 6.5, 0.65, -110, "e1", "H", "A", "HIGH"),
            PropLeg("C", "player_rebounds", 5.5, 0.55, -110, "e1", "H", "A", "HIGH"),
        ]
        enforced = SGPBuilder._enforce_category_diversity(legs)
        assert len(enforced) == 2
        # Should keep the two highest-prob legs
        probs = [l.model_prob for l in enforced]
        assert 0.55 not in probs  # weakest dropped

    def test_mixed_categories_all_kept(self):
        from alpha.engines.sports.sgp_builder import SGPBuilder, PropLeg
        legs = [
            PropLeg("A", "player_points", 25.5, 0.65, -110, "e1", "H", "A", "HIGH"),
            PropLeg("B", "player_rebounds", 8.5, 0.60, -110, "e1", "H", "A", "HIGH"),
            PropLeg("C", "player_assists", 6.5, 0.58, -110, "e1", "H", "A", "HIGH"),
            PropLeg("D", "player_steals", 1.5, 0.55, -110, "e1", "H", "A", "MEDIUM"),
        ]
        enforced = SGPBuilder._enforce_category_diversity(legs)
        assert len(enforced) == 4


# ---------------------------------------------------------------------------
# NBAStatsCache (basic sanity)
# ---------------------------------------------------------------------------


class TestKellyCap:
    """Feature 3: Kelly display cap at 5%."""

    def test_kelly_cap_at_5pct(self):
        """Displayed Kelly never exceeds 5% even with very high model prob."""
        pick = PickOutput(
            player="Super Star",
            description="Over 30.5 pts",
            model_confidence=0.99,
            implied_odds_prob=0.52,
            edge=0.47,
            ev_per_100=90.0,
            kelly_pct=0.235,    # 23.5% raw Kelly — huge
            kelly_stake=2350.0,
            source="xgb",
            recommendation_eligible=True,
            refusal_reasons=[],
        )
        text = pick.format(bankroll=10_000.0)
        assert "5.0% of bankroll" in text
        assert "capped from 23.5%" in text
        assert "23.5% of bankroll" not in text

    def test_kelly_no_cap_when_below_5pct(self):
        pick = PickOutput(
            player="Normal Player",
            description="Over 20.5 pts",
            model_confidence=0.60,
            implied_odds_prob=0.52,
            edge=0.08,
            ev_per_100=5.0,
            kelly_pct=0.03,
            kelly_stake=300.0,
            source="xgb",
            recommendation_eligible=True,
            refusal_reasons=[],
        )
        text = pick.format(bankroll=10_000.0)
        assert "3.0% of bankroll" in text
        assert "capped" not in text


class TestNBAStatsCache:
    def test_cache_creation(self, tmp_path):
        from alpha.data.ingestion.nba_stats_cache import NBAStatsCache
        cache = NBAStatsCache(cache_path=tmp_path / "test_cache.sqlite")
        assert (tmp_path / "test_cache.sqlite").exists()

    def test_get_or_fetch_caches_result(self, tmp_path):
        from alpha.data.ingestion.nba_stats_cache import NBAStatsCache
        cache = NBAStatsCache(cache_path=tmp_path / "test_cache.sqlite")
        call_count = 0

        def fetch():
            nonlocal call_count
            call_count += 1
            return {"data": "test"}

        result1 = cache.get_or_fetch("test_endpoint", {"key": "val"}, fetch)
        result2 = cache.get_or_fetch("test_endpoint", {"key": "val"}, fetch)
        assert result1 == result2
        assert call_count == 1  # only called once due to cache

    def test_clear_stale(self, tmp_path):
        from alpha.data.ingestion.nba_stats_cache import NBAStatsCache
        cache = NBAStatsCache(cache_path=tmp_path / "test_cache.sqlite")
        deleted = cache.clear_stale()
        assert isinstance(deleted, int)
