"""Tests for scripts/wc_scanner.py."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from alpha.data.ingestion.wc_market_odds import WCMarketOdds
from alpha.data.ingestion.wc_tactics import WCTacticalProfile

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


def test_parse_args_accepts_hybrid_model():
    from scripts.wc_scanner import _parse_args
    with patch("sys.argv", ["wc_scanner.py", "--model", "hybrid"]):
        assert _parse_args().model == "hybrid"


def test_parse_args_accepts_runtime_truth_flags():
    from scripts.wc_scanner import _parse_args
    with patch("sys.argv", ["wc_scanner.py", "--model", "auto", "--shadow-model", "hybrid"]):
        args = _parse_args()
    assert args.model == "auto"
    assert args.shadow_model == "hybrid"


def test_main_individual_only_skips_combo_building(capsys):
    game = _make_enriched_game("Brazil", "Germany", event_id="101")
    from scripts.wc_scanner import main
    with patch("sys.argv", ["wc_scanner.py", "--mode", "parlay", "--individual-only"]), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.is_configured", return_value=True), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.fetch_wc_games", return_value=[game]), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.__init__", return_value=None), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.predict", side_effect=lambda g: g):
        main()
    output = capsys.readouterr().out
    assert "WC individual probabilities" in output
    assert "Brazil vs Germany" in output
    assert "skipped SGP/parlay" in output
    assert "Building WC" not in output


def test_main_fixtures_file_individual_only(capsys, tmp_path):
    fixture_file = tmp_path / "fixtures.json"
    fixture_file.write_text(
        """
        {
          "games": [
            {
              "home_team": "Brazil",
              "away_team": "Germany",
              "league": "wc",
              "event_id": "fixture-1",
              "commence_time": "2026-06-29T17:00:00Z",
              "stage": "LAST_32",
              "group": "",
              "home_odds": -110,
              "away_odds": -110
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    from scripts.wc_scanner import main
    with patch("sys.argv", ["wc_scanner.py", "--fixtures-file", str(fixture_file), "--individual-only"]), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.__init__", return_value=None), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.predict", side_effect=lambda g: {
             **g,
             "win_prob": 0.6,
             "draw_prob": 0.0,
             "loss_prob": 0.4,
             "model_name": "wc_elo_logistic",
         }):
        main()

    output = capsys.readouterr().out
    assert "Loaded fixtures from" in output
    assert "Brazil vs Germany" in output
    assert "H/D/A 60.0%/0.0%/40.0%" in output


def test_main_props_only_prints_game_props(capsys, tmp_path):
    fixture_file = tmp_path / "fixtures.json"
    fixture_file.write_text(
        """
        {
          "games": [
            {
              "home_team": "Brazil",
              "away_team": "Germany",
              "league": "wc",
              "event_id": "fixture-1",
              "commence_time": "2026-06-29T17:00:00Z",
              "stage": "LAST_32",
              "group": "",
              "home_odds": -110,
              "away_odds": -110
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    from scripts.wc_scanner import main
    with patch("sys.argv", ["wc_scanner.py", "--fixtures-file", str(fixture_file), "--props-only"]), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.__init__", return_value=None), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.predict", side_effect=lambda g: {
             **g,
             "win_prob": 0.6,
             "draw_prob": 0.0,
             "loss_prob": 0.4,
             "model_name": "wc_elo_logistic",
             "elo_diff": 120.0,
         }):
        main()

    output = capsys.readouterr().out
    assert "WC game prop probabilities" in output
    assert "Player props unavailable" in output
    assert "Over 2.5 goals" in output
    assert "BTTS Yes" in output
    assert "Building WC" not in output


def test_main_hybrid_model_prints_model_label(capsys):
    game = _make_enriched_game("Brazil", "Germany", event_id="101")
    from scripts.wc_scanner import main
    with patch("sys.argv", ["wc_scanner.py", "--mode", "parlay", "--model", "hybrid", "--min-edge", "0.99"]), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.is_configured", return_value=True), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.fetch_wc_games", return_value=[game]), \
         patch("alpha.engines.sports.wc_hybrid_model.WCHybridModel.__init__", return_value=None), \
         patch("alpha.engines.sports.wc_hybrid_model.WCHybridModel.predict", side_effect=lambda g: {**g, "model_name": "wc_hybrid_baseline"}):
        main()
    output = capsys.readouterr().out
    assert "Model: HYBRID" in output
    assert "wc_hybrid_baseline" in output


def test_main_auto_model_missing_artifact_errors(capsys):
    game = _make_enriched_game("Brazil", "Germany", event_id="101")
    from scripts.wc_scanner import main
    with patch("sys.argv", ["wc_scanner.py", "--mode", "parlay", "--model", "auto"]), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.is_configured", return_value=True), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.fetch_wc_games", return_value=[game]):
        with pytest.raises(SystemExit):
            main()
    output = capsys.readouterr().out
    assert "promoted model unavailable" in output
    assert "no silent fallback" in output


def test_main_auto_model_explicit_fallback_is_labeled(capsys):
    game = _make_enriched_game("Brazil", "Germany", event_id="101")
    from scripts.wc_scanner import main
    with patch("sys.argv", ["wc_scanner.py", "--mode", "parlay", "--model", "auto", "--allow-fallback", "--min-edge", "0.99"]), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.is_configured", return_value=True), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.fetch_wc_games", return_value=[game]), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.__init__", return_value=None), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.predict", side_effect=lambda g: g):
        main()
    output = capsys.readouterr().out
    assert "requested_model=auto active_model=elo fallback_used=true" in output
    assert "fallback_reason=artifact_metadata_missing" in output


def test_main_shadow_model_logs_without_affecting_picks(capsys):
    game = _make_enriched_game("Brazil", "Germany", event_id="101")
    from scripts.wc_scanner import main
    with patch("sys.argv", ["wc_scanner.py", "--mode", "parlay", "--shadow-model", "hybrid", "--min-edge", "0.99"]), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.is_configured", return_value=True), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.fetch_wc_games", return_value=[game]), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.__init__", return_value=None), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.predict", side_effect=lambda g: g), \
         patch("alpha.engines.sports.wc_hybrid_model.WCHybridModel.__init__", return_value=None), \
         patch("alpha.engines.sports.wc_hybrid_model.WCHybridModel.predict", side_effect=lambda g: {**g, "model_name": "wc_hybrid_baseline"}), \
         patch("scripts.wc_scanner._write_shadow_predictions", return_value="reports/shadow_predictions/wc_test.jsonl") as write_shadow:
        main()
    output = capsys.readouterr().out
    assert write_shadow.called
    assert "shadow_model=hybrid shadow_affects_picks=false" in output


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
         patch("alpha.data.ingestion.wc_recent_form.WCRecentFormClient.fetch", return_value={"avg_goals": 1.2, "defense_score": 0.8}), \
         patch("alpha.data.ingestion.wc_tactics.WCTacticsClient.resolve_team_ids", return_value={"Brazil": "1", "Germany": "2"}), \
         patch("alpha.data.ingestion.wc_tactics.WCTacticsClient.fetch_profile", side_effect=lambda team, *_: _make_tactical_profile(team)), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.__init__", return_value=None), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.predict", side_effect=lambda item: item):
        main()
    output = capsys.readouterr().out
    assert "Mode: SGP" in output
    assert "Over 2.5 goals" in output or "Under 2.5 goals" in output
    assert "Joint win probability" in output
    assert "Probability only" in output
    assert "Full probability set" in output
    assert "TACTICAL MATCHUPS" in output
    assert "Artifact: fallback" in output
    assert "1x2=FALLBACK" in output
    assert "descriptive only" in output
    assert "1X2 H/D/A" in output
    assert "EV:" not in output


def test_main_sgp_creates_probabilities_without_market_prices(capsys):
    game = _make_enriched_game("Brazil", "Germany", event_id="101")
    from scripts.wc_scanner import main
    with patch("sys.argv", ["wc_scanner.py", "--mode", "sgp"]), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.is_configured", return_value=True), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.fetch_wc_games", return_value=[game]), \
         patch("alpha.data.ingestion.wc_market_odds.load_wc_market_odds", return_value={}), \
         patch("alpha.data.ingestion.wc_recent_form.WCRecentFormClient.fetch", return_value={"avg_goals": 1.2, "defense_score": 0.8}), \
         patch("alpha.data.ingestion.wc_tactics.WCTacticsClient.resolve_team_ids", return_value={"Brazil": "1", "Germany": "2"}), \
         patch("alpha.data.ingestion.wc_tactics.WCTacticsClient.fetch_profile", side_effect=lambda team, *_: _make_tactical_profile(team)), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.__init__", return_value=None), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.predict", side_effect=lambda item: item):
        main()
    output = capsys.readouterr().out
    assert "Joint win probability" in output
    assert "Probability only" in output


def test_main_sgp_fetches_recent_form_for_every_team(capsys):
    games = [
        _make_enriched_game("Brazil", "Germany", event_id="101"),
        _make_enriched_game("France", "Argentina", event_id="102"),
    ]
    recent = {"avg_goals": 1.2, "defense_score": 0.8}
    from scripts.wc_scanner import main
    with patch("sys.argv", ["wc_scanner.py", "--mode", "sgp"]), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.is_configured", return_value=True), \
         patch("alpha.data.ingestion.football_data_client.FootballDataClient.fetch_wc_games", return_value=games), \
         patch("alpha.data.ingestion.wc_market_odds.load_wc_market_odds", return_value={}), \
         patch("alpha.data.ingestion.wc_recent_form.WCRecentFormClient.fetch", return_value=recent) as fetch, \
         patch("alpha.data.ingestion.wc_tactics.WCTacticsClient.resolve_team_ids", return_value={"Brazil": "1", "Germany": "2", "France": "3", "Argentina": "4"}), \
         patch("alpha.data.ingestion.wc_tactics.WCTacticsClient.fetch_profile", side_effect=lambda team, *_: _make_tactical_profile(team)), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.__init__", return_value=None), \
         patch("alpha.engines.sports.wc_model.WCMatchModel.predict", side_effect=lambda item: item):
        main()
    assert fetch.call_count == 4
    assert {call.args[0] for call in fetch.call_args_list} == {
        "Brazil", "Germany", "France", "Argentina"
    }


def _make_tactical_profile(team: str) -> WCTacticalProfile:
    return WCTacticalProfile(
        team=team, matches=5, latest_match="2026-06-15", formation="4-3-3",
        possession=0.52, pass_completion=0.82, long_ball_rate=0.10,
        cross_rate=0.04, shots_for=13.0, shots_allowed=11.0,
        shot_on_target_rate=0.34, corners_for=5.0, corners_allowed=4.0,
        pressing_proxy=3.8, clearances=14.0,
    )
