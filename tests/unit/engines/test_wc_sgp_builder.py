"""Tests for alpha/engines/sports/wc_sgp_builder.py."""
from __future__ import annotations

import pytest

from alpha.engines.sports.wc_sgp_builder import WCSGPBuilder
from alpha.data.ingestion.wc_market_odds import WCMarketOdds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game(
    home: str = "Brazil",
    away: str = "Germany",
    win_prob: float = 0.60,
    home_odds: int = -130,
    away_odds: int = 110,
    knockout: bool = False,
    elo_edge: bool = False,
    event_id: str = "",
) -> dict:
    """Build an enriched WC game dict as produced by WCMatchModel.predict()."""
    draw_prob = 0.0 if knockout else 0.25
    loss_prob = round(1.0 - win_prob - draw_prob, 4)
    return {
        "home_team": home,
        "away_team": away,
        "home_odds": home_odds,
        "away_odds": away_odds,
        "league": "wc",
        "event_id": event_id or f"{home}-{away}",
        "commence_time": "2026-07-01T18:00:00Z",
        "stage": "QUARTER_FINALS" if knockout else "GROUP_STAGE",
        "group": "" if knockout else "Group A",
        "win_prob": win_prob,
        "draw_prob": draw_prob,
        "loss_prob": loss_prob,
        "elo_edge": elo_edge,
        "knockout": knockout,
        "model_name": "wc_elo_logistic",
        "elo_diff": 120.0,
        "home_elo": 2100,
        "away_elo": 1980,
    }


# ---------------------------------------------------------------------------
# Basic build() interface
# ---------------------------------------------------------------------------

def test_build_returns_list():
    g1 = _make_game("Brazil", "Germany", win_prob=0.65)
    g2 = _make_game("France", "Argentina", win_prob=0.55)
    result = WCSGPBuilder(min_edge=0.0).build([g1, g2])
    assert isinstance(result, list)


def test_build_requires_min_two_games():
    g1 = _make_game("Brazil", "Germany", win_prob=0.65)
    result = WCSGPBuilder(min_edge=0.0).build([g1])
    assert result == []


def test_empty_games_returns_empty():
    result = WCSGPBuilder(min_edge=0.0).build([])
    assert result == []


# ---------------------------------------------------------------------------
# min_edge filter
# ---------------------------------------------------------------------------

def test_min_edge_filter_excludes_all():
    g1 = _make_game("Brazil", "Germany", win_prob=0.55)
    g2 = _make_game("France", "Argentina", win_prob=0.52)
    # At -110 implied ~0.524 each; combined model well below combined market at high threshold
    result = WCSGPBuilder(min_edge=0.99).build([g1, g2])
    assert result == []


def test_no_min_edge_returns_combos():
    g1 = _make_game("Brazil", "Germany", win_prob=0.70, home_odds=-160)
    g2 = _make_game("France", "Argentina", win_prob=0.65, home_odds=-140)
    result = WCSGPBuilder(min_edge=0.0).build([g1, g2])
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Leg content
# ---------------------------------------------------------------------------

def test_classic_parlay_uses_win_prob():
    win_prob = 0.68
    g1 = _make_game("Brazil", "Germany", win_prob=win_prob, home_odds=-150)
    g2 = _make_game("France", "Argentina", win_prob=0.60, home_odds=-130)
    result = WCSGPBuilder(min_edge=0.0).build([g1, g2])
    assert len(result) > 0
    # Find 2-leg combo
    two_leg = next((c for c in result if len(c.legs) == 2), None)
    assert two_leg is not None
    probs = [leg["model_prob"] for leg in two_leg.legs]
    assert win_prob in probs


def test_elo_edge_preserved_in_leg():
    g1 = _make_game("Brazil", "Germany", win_prob=0.70, elo_edge=True, home_odds=-160)
    g2 = _make_game("France", "Argentina", win_prob=0.55, elo_edge=False, home_odds=-110)
    result = WCSGPBuilder(min_edge=0.0).build([g1, g2])
    assert len(result) > 0
    # At least one leg should carry elo_edge=True
    all_elo_edges = [leg.get("elo_edge", False) for combo in result for leg in combo.legs]
    assert True in all_elo_edges


def test_combo_probs_multiply():
    g1 = _make_game("Brazil", "Germany", win_prob=0.60, home_odds=-150)
    g2 = _make_game("France", "Argentina", win_prob=0.55, home_odds=-120)
    result = WCSGPBuilder(min_edge=0.0).build([g1, g2])
    two_leg = next((c for c in result if len(c.legs) == 2), None)
    assert two_leg is not None
    expected = 0.60 * 0.55
    assert two_leg.combined_model_prob == pytest.approx(expected, abs=0.001)


# ---------------------------------------------------------------------------
# Knockout gate (SGP-02)
# ---------------------------------------------------------------------------

def test_knockout_game_no_draw_leg():
    g1 = _make_game("Brazil", "Germany", win_prob=0.65, knockout=True)
    g2 = _make_game("France", "Argentina", win_prob=0.55, knockout=True)
    result = WCSGPBuilder(min_edge=0.0).build([g1, g2])
    # No leg should have type "draw" or market "draw"
    for combo in result:
        for leg in combo.legs:
            if isinstance(leg, dict):
                assert leg.get("type") != "draw"
                assert leg.get("market") != "draw"


# ---------------------------------------------------------------------------
# Sorting and top_n
# ---------------------------------------------------------------------------

def test_results_sorted_by_ev():
    games = [
        _make_game("Brazil", "Germany", win_prob=0.75, home_odds=-200, event_id="g1"),
        _make_game("France", "Argentina", win_prob=0.60, home_odds=-130, event_id="g2"),
        _make_game("Spain", "Morocco", win_prob=0.65, home_odds=-150, event_id="g3"),
    ]
    result = WCSGPBuilder(min_edge=0.0).build(games)
    for i in range(len(result) - 1):
        assert result[i].ev >= result[i + 1].ev


def test_top_n_limits_output():
    games = [
        _make_game("Brazil", "Germany", win_prob=0.70, home_odds=-160, event_id="g1"),
        _make_game("France", "Argentina", win_prob=0.65, home_odds=-140, event_id="g2"),
        _make_game("Spain", "Morocco", win_prob=0.60, home_odds=-130, event_id="g3"),
        _make_game("England", "USA", win_prob=0.58, home_odds=-120, event_id="g4"),
    ]
    result = WCSGPBuilder(min_edge=0.0).build(games, top_n=2)
    assert len(result) <= 2


# ---------------------------------------------------------------------------
# True same-game World Cup combinations
# ---------------------------------------------------------------------------

def _true_sgp_odds(home="Brazil", away="Germany"):
    return WCMarketOdds(
        event_key=f"{home}|{away}",
        prices={
            "home_win": 2.10,
            "draw": 3.40,
            "away_win": 3.80,
            "over_2_5": 2.05,
            "under_2_5": 1.85,
            "btts_yes": 2.00,
            "btts_no": 1.90,
        },
    )


def test_true_sgp_contains_only_one_event_and_two_or_three_legs():
    game = _make_game(win_prob=0.62, event_id="g1")
    result = WCSGPBuilder(min_edge=-1.0, max_legs=3).build_same_game(
        [game], {"Brazil|Germany": _true_sgp_odds()}, top_n=20
    )
    assert result
    for combo in result:
        assert 2 <= len(combo.legs) <= 3
        assert {leg["event_id"] for leg in combo.legs} == {"g1"}


def test_true_sgp_uses_exact_correlated_joint_probability():
    game = _make_game(win_prob=0.62, event_id="g1")
    builder = WCSGPBuilder(min_edge=-1.0)
    combo = next(
        item for item in builder.build_same_game(
            [game], {"Brazil|Germany": _true_sgp_odds()}, top_n=100
        )
        if {leg["market"] for leg in item.legs} == {"home_win", "over_2_5"}
    )
    naive = combo.legs[0]["model_prob"] * combo.legs[1]["model_prob"]
    assert combo.combined_model_prob != pytest.approx(naive, abs=1e-3)
    assert "scoreline" in combo.correlation_note.lower()


def test_true_sgp_skips_games_without_two_real_market_prices():
    game = _make_game(event_id="g1")
    odds = WCMarketOdds("Brazil|Germany", {"home_win": 2.10})
    assert WCSGPBuilder(min_edge=-1.0).build_same_game(
        [game], {"Brazil|Germany": odds}
    ) == []


def test_true_sgp_knockout_excludes_1x2_legs():
    game = _make_game(knockout=True, event_id="g1")
    result = WCSGPBuilder(min_edge=-1.0).build_same_game(
        [game], {"Brazil|Germany": _true_sgp_odds()}, top_n=20
    )
    assert result
    assert all(
        leg["market"] not in {"home_win", "draw", "away_win"}
        for combo in result for leg in combo.legs
    )


def test_probability_sgp_needs_no_market_odds_and_ranks_highest_first():
    games = [
        _make_game("Brazil", "Germany", win_prob=0.62, event_id="g1"),
        _make_game("France", "Argentina", win_prob=0.50, event_id="g2"),
    ]
    results = WCSGPBuilder(team_stats={}, max_legs=3).build_probability_same_game(
        games, top_n=20
    )
    assert results
    assert all(2 <= len(combo.legs) <= 3 for combo in results)
    assert all(combo.fair_decimal_odds > 1.0 for combo in results)
    assert all(
        results[index].combined_model_prob >= results[index + 1].combined_model_prob
        for index in range(len(results) - 1)
    )


def test_probability_sgp_includes_every_side_for_user_selection():
    game = _make_game(event_id="g1")
    results = WCSGPBuilder(team_stats={}).build_probability_same_game([game])
    observed = {leg["market"] for combo in results for leg in combo.legs}
    assert observed == {
        "home_win", "draw", "away_win",
        "over_2_5", "under_2_5",
        "btts_yes", "btts_no",
    }
    # 28 family combinations minus three scoreline-impossible triples.
    assert len(results) == 25


def test_probability_sgp_uses_only_one_selection_per_market_family():
    game = _make_game(win_prob=0.62, event_id="g1")
    results = WCSGPBuilder(team_stats={}).build_probability_same_game([game], top_n=20)
    assert results
    for combo in results:
        markets = {leg["market"] for leg in combo.legs}
        assert not {"over_2_5", "under_2_5"} <= markets
        assert not {"btts_yes", "btts_no"} <= markets
        assert len(markets & {"home_win", "draw", "away_win"}) <= 1


def test_probability_sgp_labels_logically_redundant_third_leg():
    game = _make_game("Spain", "Saudi Arabia", win_prob=0.70, event_id="g1")
    results = WCSGPBuilder(team_stats={}).build_probability_same_game([game], top_n=20)
    redundant = [combo for combo in results if combo.redundant]
    assert redundant
    assert all(len(combo.legs) == 3 for combo in redundant)


def test_probability_sgp_knockout_is_goal_markets_only():
    game = _make_game(knockout=True, event_id="g1")
    results = WCSGPBuilder(team_stats={}).build_probability_same_game([game])
    assert len(results) == 4
    assert all(
        {leg["market"] for leg in combo.legs} <= {
            "over_2_5", "under_2_5", "btts_yes", "btts_no"
        }
        for combo in results
    )
