import pytest
from alpha.engines.sports.engine import SportsEngine


_GAMES = [
    {"home_team": "Lakers", "away_team": "Celtics", "home_odds": -150, "away_odds": 130,
     "sport": "basketball", "league": "nba"},
    {"home_team": "Warriors", "away_team": "Heat", "home_odds": 110, "away_odds": -130,
     "sport": "basketball", "league": "nba"},
    {"home_team": "Bucks", "away_team": "Nets", "home_odds": -200, "away_odds": 170,
     "sport": "basketball", "league": "nba"},
]


def test_engine_initializes():
    engine = SportsEngine()
    assert engine is not None


def test_run_returns_bets_list():
    engine = SportsEngine(bankroll=10_000.0)
    result = engine.run(_GAMES, position_scalar=1.0)
    assert "bets" in result
    assert "total_stake" in result
    assert "regime_scalar" in result


def test_bets_have_required_fields():
    engine = SportsEngine(bankroll=10_000.0)
    result = engine.run(_GAMES, position_scalar=1.0)
    for bet in result["bets"]:
        assert "stake" in bet
        assert "ev" in bet
        assert "bet_side" in bet


def test_risk_off_reduces_stakes():
    engine = SportsEngine(bankroll=10_000.0)
    full = engine.run(_GAMES, position_scalar=1.0)
    reduced = engine.run(_GAMES, position_scalar=0.25)
    assert reduced["total_stake"] <= full["total_stake"] + 0.01
