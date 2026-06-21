"""Tests for scripts/wc_scanner.py."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from alpha.data.ingestion.wc_market_odds import WCMarketOdds

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_enriched_game(
    home: str = "Brazil",
    away: str = "Germany",
    win_prob: float = 0.60,
    home_odds: int = -130,
    elo_edge: bool = False,
    knockout: bool = False,
    event_id: str = "1001",
) -> dict:
    return {
        "home_team": home,
        "away_team": away,
        "home_odds": home_odds,
        "away_odds": 110,
        "league": "wc",
        "event_id": event_id,
        "commence_time": "2026-07-01T18:00:00Z",
        "stage": "QUARTER_FINALS" if knockout else "GROUP_STAGE",
        "group": "" if knockout else "Group A",
        "win_prob": win_prob,
        "draw_prob": 0.0 if knockout else 0.25,
        "loss_prob": round(1.0 - win_prob - (0.0 if knockout else 0.25), 4),
        "elo_edge": elo_edge,
        "knockout": knockout,
        "model_name": "wc_elo_logistic",
        "elo_diff": 120.0,
        "home_elo": 2100,
        "away_elo": 1980,
    }


# ---------------------------------------------------------------------------
# main() integration tests (monkeypatched data layer)
# ---------------------------------------------------------------------------

def test_main_exits_when_no_api_key(capsys):
    """If FOOTBALL_API_KEY not set, scanner prints message and exits."""
    from scripts.wc_scanner import main
    test_args = ["wc_scanner.py", "--mode", "parlay"]
    with patch("sys.argv", test_args), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.is_configured",
               return_value=False):
        with pytest.raises(SystemExit):
            main()
    captured = capsys.readouterr()
    assert "FOOTBALL_API_KEY" in captured.out or "FOOTBALL_API_KEY" in captured.err


def test_main_exits_when_no_games(capsys):
    """If no WC games found, scanner prints message and exits."""
    from scripts.wc_scanner import main
    test_args = ["wc_scanner.py", "--mode", "parlay"]
    with patch("sys.argv", test_args), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.is_configured",
               return_value=True), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.fetch_wc_games",
               return_value=[]):
        with pytest.raises(SystemExit):
            main()
    captured = capsys.readouterr()
    assert "No WC games" in captured.out or "No WC games" in captured.err or \
           "no" in captured.out.lower()


def test_main_elo_edge_annotation_in_output(capsys):
    """When a game has elo_edge=True, *ELO EDGE* appears in scanner output."""
    g1 = _make_enriched_game("Brazil", "Germany", win_prob=0.72, elo_edge=True, event_id="101")
    g2 = _make_enriched_game("France", "Argentina", win_prob=0.65, elo_edge=False, event_id="102")

    from scripts.wc_scanner import main
    test_args = ["wc_scanner.py", "--mode", "parlay", "--min-edge", "0.0"]
    with patch("sys.argv", test_args), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.is_configured",
               return_value=True), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.fetch_wc_games",
               return_value=[g1, g2]), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.predict", side_effect=lambda game: game):
        # wc_priors.json may not exist in CI — patch WCMatchModel constructor
        with patch("alpha.engines.sports.wc_model.WCMatchModel.__init__", return_value=None), \
             patch("alpha.engines.sports.wc_model.WCMatchModel.predict", side_effect=lambda g: g):
            main()
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "ELO EDGE" in output


def test_main_output_contains_scanner_header(capsys):
    """Scanner output contains the WC SCANNER header line."""
    g1 = _make_enriched_game("Brazil", "Germany", win_prob=0.65, event_id="101")
    g2 = _make_enriched_game("France", "Argentina", win_prob=0.60, event_id="102")

    from scripts.wc_scanner import main
    test_args = ["wc_scanner.py", "--mode", "parlay", "--min-edge", "0.0"]
    with patch("sys.argv", test_args), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.is_configured",
               return_value=True), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.fetch_wc_games",
               return_value=[g1, g2]), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.__init__", return_value=None), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.predict", side_effect=lambda g: g):
        main()
    captured = capsys.readouterr()
    assert "WC SCANNER" in captured.out


def test_main_no_combos_message_when_high_edge(capsys):
    """When min_edge is very high, scanner prints 'No combinations found'."""
    g1 = _make_enriched_game("Brazil", "Germany", win_prob=0.55, event_id="101")
    g2 = _make_enriched_game("France", "Argentina", win_prob=0.52, event_id="102")

    from scripts.wc_scanner import main
    test_args = ["wc_scanner.py", "--mode", "parlay", "--min-edge", "0.99"]
    with patch("sys.argv", test_args), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.is_configured",
               return_value=True), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.fetch_wc_games",
               return_value=[g1, g2]), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.__init__", return_value=None), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.predict", side_effect=lambda g: g):
        main()
    captured = capsys.readouterr()
    assert "No combinations" in captured.out or "no" in captured.out.lower()


def test_parse_args_accepts_true_sgp_mode():
    from scripts.wc_scanner import _parse_args
    with patch("sys.argv", ["wc_scanner.py", "--mode", "sgp"]):
        assert _parse_args().mode == "sgp"


def test_main_sgp_prints_same_game_market_legs(capsys):
    game = _make_enriched_game("Brazil", "Germany", win_prob=0.60, event_id="101")
    odds = WCMarketOdds(
        "Brazil|Germany",
        {
            "home_win": 2.2,
            "away_win": 4.0,
            "over_2_5": 2.1,
            "under_2_5": 1.8,
            "btts_yes": 2.0,
        },
    )
    from scripts.wc_scanner import main
    test_args = ["wc_scanner.py", "--mode", "sgp", "--min-edge", "-1.0"]
    with patch("sys.argv", test_args), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.is_configured", return_value=True), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.fetch_wc_games", return_value=[game]), \
         patch("alpha.data.ingestion.wc_market_odds.load_wc_market_odds", return_value={"Brazil|Germany": odds}), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.__init__", return_value=None), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.predict", side_effect=lambda item: item):
        main()
    output = capsys.readouterr().out
    assert "Mode: SGP" in output
    assert "Over 2.5 goals" in output or "Under 2.5 goals" in output
    assert "Exact scoreline joint model" in output


def test_main_sgp_explains_missing_market_prices(capsys):
    game = _make_enriched_game("Brazil", "Germany", event_id="101")
    from scripts.wc_scanner import main
    with patch("sys.argv", ["wc_scanner.py", "--mode", "sgp"]), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.is_configured", return_value=True), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.fetch_wc_games", return_value=[game]), \
         patch("alpha.data.ingestion.wc_market_odds.load_wc_market_odds", return_value={}), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.__init__", return_value=None), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.predict", side_effect=lambda item: item):
        main()
    assert "at least two compatible market families" in capsys.readouterr().out
