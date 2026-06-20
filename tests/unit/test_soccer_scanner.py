"""Tests for scripts/soccer_scanner.py — UCL routing and draw annotation."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_epl_game(
    event_id: str = "1",
    home: str = "Arsenal",
    away: str = "Chelsea",
) -> dict:
    return {
        "league": "epl",
        "home_team": home,
        "away_team": away,
        "event_id": event_id,
        "home_odds": -130,
        "away_odds": 110,
        "home_model_prob": 0.55,
        "away_model_prob": 0.30,
        "draw_prob": 0.15,
        "model_name": "epl_xgboost_v1",
    }


def _make_ucl_game(
    event_id: str = "2",
    home: str = "Bayern",
    away: str = "PSG",
) -> dict:
    return {
        "league": "ucl",
        "home_team": home,
        "away_team": away,
        "event_id": event_id,
        "home_odds": -130,
        "away_odds": 110,
        "win_prob": 0.60,
        "loss_prob": 0.25,
        "draw_prob": 0.15,
        "home_model_prob": 0.60,
        "away_model_prob": 0.25,
        "model_name": "ucl_elo_logistic",
    }


def _make_soccer_model_pred(
    home_win_prob: float = 0.55,
    away_win_prob: float = 0.30,
    draw_prob: float = 0.15,
    model_name: str = "epl_xgboost_v1",
) -> dict:
    """Return dict shaped like SoccerModel.predict() output."""
    return {
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "home_win_prob": home_win_prob,
        "away_win_prob": away_win_prob,
        "draw_prob": draw_prob,
        "source": "epl_xgboost",
        "model_name": model_name,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_scanner_exits_when_no_api_key(capsys):
    """If FOOTBALL_API_KEY not set, scanner prints message and exits."""
    from scripts.soccer_scanner import main
    test_args = ["soccer_scanner.py", "--mode", "parlay"]
    with patch("sys.argv", test_args), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.is_configured",
             return_value=False,
         ):
        with pytest.raises(SystemExit):
            main()
    captured = capsys.readouterr()
    assert "FOOTBALL_API_KEY" in captured.out or "FOOTBALL_API_KEY" in captured.err


def test_scanner_exits_when_no_games(capsys):
    """If no soccer games returned, scanner prints message and exits."""
    from scripts.soccer_scanner import main
    test_args = ["soccer_scanner.py", "--mode", "parlay"]
    with patch("sys.argv", test_args), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.is_configured",
             return_value=True,
         ), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.fetch_today_games",
             return_value=[],
         ):
        with pytest.raises(SystemExit):
            main()
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "No soccer" in output or "no" in output.lower()


def test_epl_games_use_soccer_model(capsys):
    """EPL games call SoccerModel.predict; UCLEloModel.predict is NOT called."""
    from scripts.soccer_scanner import main

    g1 = _make_epl_game("101", "Arsenal", "Chelsea")
    g2 = _make_epl_game("102", "Liverpool", "Man City")

    soccer_pred = _make_soccer_model_pred()

    # Use --league epl so only EPL games are fetched (no UCL routing attempted)
    test_args = ["soccer_scanner.py", "--mode", "parlay", "--min-edge", "0.0", "--league", "epl"]
    with patch("sys.argv", test_args), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.is_configured",
             return_value=True,
         ), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.fetch_today_games",
             return_value=[g1, g2],
         ), \
         patch(
             "alpha.engines.sports.soccer_model.SoccerModel.predict",
             return_value=soccer_pred,
         ) as mock_soccer_predict, \
         patch(
             "alpha.engines.sports.ucl_model.UCLEloModel.__init__",
             return_value=None,
         ), \
         patch(
             "alpha.engines.sports.ucl_model.UCLEloModel.predict",
             side_effect=lambda g: g,
         ) as mock_ucl_predict:
        main()

    # SoccerModel.predict must have been called for the EPL games
    assert mock_soccer_predict.call_count == 2
    # UCLEloModel.predict must NOT have been called (no UCL games in input)
    assert mock_ucl_predict.call_count == 0


def test_ucl_games_use_ucl_model(capsys):
    """UCL games call UCLEloModel.predict; SoccerModel.predict is NOT called for those games."""
    from scripts.soccer_scanner import main

    g1 = _make_ucl_game("201", "Bayern", "PSG")
    g2 = _make_ucl_game("202", "Man City", "Real Madrid")

    def _ucl_side_effect(game: dict) -> dict:
        game["win_prob"] = 0.60
        game["draw_prob"] = 0.15
        game["loss_prob"] = 0.25
        game["home_model_prob"] = 0.60
        game["away_model_prob"] = 0.25
        game["model_name"] = "ucl_elo_logistic"
        return game

    # Use --league ucl so only UCL games are fetched (routing to UCLEloModel)
    test_args = ["soccer_scanner.py", "--mode", "parlay", "--min-edge", "0.0", "--league", "ucl"]
    with patch("sys.argv", test_args), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.is_configured",
             return_value=True,
         ), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.fetch_today_games",
             return_value=[g1, g2],
         ), \
         patch(
             "alpha.engines.sports.soccer_model.SoccerModel.predict",
             return_value=_make_soccer_model_pred(),
         ) as mock_soccer_predict, \
         patch(
             "alpha.engines.sports.ucl_model.UCLEloModel.__init__",
             return_value=None,
         ), \
         patch(
             "alpha.engines.sports.ucl_model.UCLEloModel.predict",
             side_effect=_ucl_side_effect,
         ) as mock_ucl_predict:
        main()

    # UCLEloModel.predict must have been called for each UCL game
    assert mock_ucl_predict.call_count == 2
    # SoccerModel.predict must NOT have been called (all games are UCL)
    assert mock_soccer_predict.call_count == 0


def test_draw_risk_annotation_in_output(capsys):
    """When a combo includes a draw leg (is_draw=True), *DRAW RISK* appears in output."""
    from scripts.soccer_scanner import main
    from alpha.engines.sports.soccer_sgp_builder import ParlayCombination, SGPMode

    draw_leg = {
        "type": "draw",
        "team": "Draw",
        "model_prob": 0.28,
        "decimal_odds": 3.40,
        "event_id": "301",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "is_draw": True,
    }
    ml_leg = {
        "type": "ml",
        "team": "Bayern",
        "model_prob": 0.60,
        "decimal_odds": 1.75,
        "event_id": "302",
        "home_team": "Bayern",
        "away_team": "PSG",
        "is_draw": False,
    }

    combo = ParlayCombination(
        legs=[draw_leg, ml_leg],
        mode=SGPMode.CLASSIC_PARLAY,
        combined_model_prob=0.168,
        combined_market_prob=0.142,
        combined_decimal_odds=5.95,
        ev=1.20,
        edge=0.026,
        stake=10.0,
    )

    g1 = _make_epl_game("301")
    g2 = _make_epl_game("302", "Bayern", "PSG")

    soccer_pred = _make_soccer_model_pred()

    test_args = ["soccer_scanner.py", "--mode", "parlay", "--min-edge", "0.0"]
    with patch("sys.argv", test_args), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.is_configured",
             return_value=True,
         ), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.fetch_today_games",
             return_value=[g1, g2],
         ), \
         patch(
             "alpha.engines.sports.soccer_model.SoccerModel.predict",
             return_value=soccer_pred,
         ), \
         patch(
             "alpha.engines.sports.ucl_model.UCLEloModel.__init__",
             return_value=None,
         ), \
         patch(
             "alpha.engines.sports.soccer_sgp_builder.SoccerSGPBuilder.build",
             return_value=[combo],
         ):
        main()

    captured = capsys.readouterr()
    assert "*DRAW RISK*" in captured.out


def test_draw_risk_not_in_output_for_win_legs(capsys):
    """When combo contains only ML win legs (no is_draw), *DRAW RISK* does NOT appear."""
    from scripts.soccer_scanner import main
    from alpha.engines.sports.soccer_sgp_builder import ParlayCombination, SGPMode

    ml_leg_1 = {
        "type": "ml",
        "team": "Arsenal",
        "model_prob": 0.55,
        "decimal_odds": 1.85,
        "event_id": "401",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
    }
    ml_leg_2 = {
        "type": "ml",
        "team": "Bayern",
        "model_prob": 0.62,
        "decimal_odds": 1.70,
        "event_id": "402",
        "home_team": "Bayern",
        "away_team": "PSG",
    }

    combo = ParlayCombination(
        legs=[ml_leg_1, ml_leg_2],
        mode=SGPMode.CLASSIC_PARLAY,
        combined_model_prob=0.341,
        combined_market_prob=0.312,
        combined_decimal_odds=3.14,
        ev=1.07,
        edge=0.029,
        stake=10.0,
    )

    g1 = _make_epl_game("401")
    g2 = _make_epl_game("402", "Bayern", "PSG")

    soccer_pred = _make_soccer_model_pred()

    test_args = ["soccer_scanner.py", "--mode", "parlay", "--min-edge", "0.0"]
    with patch("sys.argv", test_args), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.is_configured",
             return_value=True,
         ), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.fetch_today_games",
             return_value=[g1, g2],
         ), \
         patch(
             "alpha.engines.sports.soccer_model.SoccerModel.predict",
             return_value=soccer_pred,
         ), \
         patch(
             "alpha.engines.sports.ucl_model.UCLEloModel.__init__",
             return_value=None,
         ), \
         patch(
             "alpha.engines.sports.soccer_sgp_builder.SoccerSGPBuilder.build",
             return_value=[combo],
         ):
        main()

    captured = capsys.readouterr()
    assert "*DRAW RISK*" not in captured.out


def test_scanner_header_in_output(capsys):
    """Running scanner with valid games produces 'SOCCER SCANNER' in output."""
    from scripts.soccer_scanner import main

    g1 = _make_epl_game("501", "Arsenal", "Chelsea")
    g2 = _make_epl_game("502", "Liverpool", "Man City")

    soccer_pred = _make_soccer_model_pred()

    test_args = ["soccer_scanner.py", "--mode", "parlay", "--min-edge", "0.0"]
    with patch("sys.argv", test_args), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.is_configured",
             return_value=True,
         ), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.fetch_today_games",
             return_value=[g1, g2],
         ), \
         patch(
             "alpha.engines.sports.soccer_model.SoccerModel.predict",
             return_value=soccer_pred,
         ), \
         patch(
             "alpha.engines.sports.ucl_model.UCLEloModel.__init__",
             return_value=None,
         ):
        main()

    captured = capsys.readouterr()
    assert "SOCCER SCANNER" in captured.out


def test_draw_prob_column_in_output(capsys):
    """Game probability display includes 'D:' draw probability column."""
    from scripts.soccer_scanner import main

    g1 = _make_epl_game("601", "Arsenal", "Chelsea")
    g2 = _make_epl_game("602", "Liverpool", "Man City")

    soccer_pred = _make_soccer_model_pred()

    test_args = ["soccer_scanner.py", "--mode", "parlay", "--min-edge", "0.0"]
    with patch("sys.argv", test_args), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.is_configured",
             return_value=True,
         ), \
         patch(
             "alpha.data.ingestion.football_data_client.FootballDataClient.fetch_today_games",
             return_value=[g1, g2],
         ), \
         patch(
             "alpha.engines.sports.soccer_model.SoccerModel.predict",
             return_value=soccer_pred,
         ), \
         patch(
             "alpha.engines.sports.ucl_model.UCLEloModel.__init__",
             return_value=None,
         ):
        main()

    captured = capsys.readouterr()
    assert "D:" in captured.out or "D%" in captured.out
