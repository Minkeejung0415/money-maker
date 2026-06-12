"""Integration-style tests for the MLB moneyline paper scanner pipeline."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from alpha.engines.sports.mlb_prediction_logger import MLBPredictionLogger
from alpha.engines.sports.mlb_run_model import MLBRunModel
from scripts.mlb_moneyline_scanner import join_odds_to_schedule, scan

DATE = "2026-06-11"


def _schedule_game(game_pk=777001, commence="2026-06-11T23:05:00Z", confirmed=True):
    return {
        "event_id": f"mlb-statsapi-{game_pk}",
        "statsapi_game_id": game_pk,
        "game_date": DATE,
        "commence_time_utc": commence,
        "home_team": "New York Yankees",
        "away_team": "Toronto Blue Jays",
        "venue": "Yankee Stadium",
        "probable_pitcher_home": "Gerrit Cole" if confirmed else None,
        "probable_pitcher_away": "Kevin Gausman" if confirmed else None,
        "probable_pitcher_home_id": 543037 if confirmed else None,
        "probable_pitcher_away_id": 592332 if confirmed else None,
        "probable_pitchers_confirmed": confirmed,
        "game_status": "Scheduled",
        "doubleheader_flag": False,
        "game_number": 1,
    }


def _odds_game(event_id="abc123", commence="2026-06-11T23:05:00Z", num_books=3):
    return {
        "event_id": event_id,
        "home_team": "New York Yankees",
        "away_team": "Toronto Blue Jays",
        "commence_time_utc": commence,
        "fetched_at_utc": "2026-06-11T12:00:00+00:00",
        "bookmaker_odds": [],
        "best_home_odds": -150 if num_books else None,
        "best_home_book": "fanduel" if num_books else None,
        "best_away_odds": 130 if num_books else None,
        "best_away_book": "draftkings" if num_books else None,
        "consensus_home_no_vig_prob": 0.579 if num_books else None,
        "consensus_away_no_vig_prob": 0.421 if num_books else None,
        "num_books": num_books,
    }


class FakeStarterSource:
    def season_pitching_record(self, pitcher_id, season):
        return {
            "throws": "R", "starts": 14, "innings": 85.0,
            "era": 3.2, "xera": 3.4, "fip": 3.3, "whip": 1.1,
            "k_per9": 9.5, "bb_per9": 2.5, "hr_per9": 1.0,
        }

    def statcast_pitch_log(self, pitcher_id, season):
        return None


class FakeOffenseSource:
    def season_batting_record(self, team, season):
        return {
            "games": 64, "runs_per_game": 4.8, "woba": 0.325,
            "obp": 0.325, "slg": 0.420, "k_rate": 0.21, "bb_rate": 0.09,
        }

    def team_game_results(self, team, season):
        return [{"date": f"2026-05-{d:02d}", "runs": 5} for d in range(1, 15)]


def _clients(schedule_games, odds_games):
    schedule_client = MagicMock()
    schedule_client.fetch_schedule.return_value = schedule_games
    schedule_client.last_pitcher_changes = []
    odds_client = MagicMock()
    odds_client.fetch_moneyline.return_value = odds_games
    odds_client.last_quota = {"credits_last": 1.0, "credits_used": 5.0,
                              "credits_remaining": 495.0}
    return schedule_client, odds_client


def _run_scan(tmp_path, schedule_games, odds_games, **kwargs):
    schedule_client, odds_client = _clients(schedule_games, odds_games)
    plog = MLBPredictionLogger(tmp_path)
    records = scan(
        DATE,
        schedule_client=schedule_client,
        odds_client=odds_client,
        prediction_logger=plog,
        model=MLBRunModel(),
        starter_source=FakeStarterSource(),
        offense_source=FakeOffenseSource(),
        **kwargs,
    )
    return records, plog, schedule_client, odds_client


# ---------------------------------------------------------------------------
# Join robustness
# ---------------------------------------------------------------------------

def test_join_matches_by_normalized_teams():
    joined = join_odds_to_schedule([_schedule_game()], [_odds_game()])
    assert joined["mlb-statsapi-777001"]["event_id"] == "abc123"


def test_join_doubleheader_uses_commence_time_without_reuse():
    sched = [
        _schedule_game(777001, commence="2026-06-11T17:05:00Z"),
        _schedule_game(777002, commence="2026-06-11T23:05:00Z"),
    ]
    odds = [
        _odds_game("late", commence="2026-06-11T23:05:00Z"),
        _odds_game("early", commence="2026-06-11T17:05:00Z"),
    ]
    joined = join_odds_to_schedule(sched, odds)
    assert joined["mlb-statsapi-777001"]["event_id"] == "early"
    assert joined["mlb-statsapi-777002"]["event_id"] == "late"


def test_join_leaves_unmatched_games_without_odds():
    sched = [_schedule_game()]
    odds = [_odds_game() | {"home_team": "Boston Red Sox"}]
    assert join_odds_to_schedule(sched, odds) == {}


# ---------------------------------------------------------------------------
# End-to-end paper scan
# ---------------------------------------------------------------------------

def test_scan_logs_full_record_with_fail_closed_gate(tmp_path, capsys):
    records, plog, _, _ = _run_scan(tmp_path, [_schedule_game()], [_odds_game()])
    assert len(records) == 1
    rec = records[0]
    # Required log fields.
    for field in (
        "prediction_id", "event_id", "created_at_utc", "commence_time_utc",
        "home_team", "away_team", "probable_pitchers", "pitcher_confirmed",
        "real_odds_present", "independent_home_prob", "independent_away_prob",
        "market_consensus_home_no_vig_prob", "market_consensus_away_no_vig_prob",
        "missing_features", "calibrator_status", "paper_bet_decision",
        "refusal_reasons", "model_version", "feature_schema_version",
    ):
        assert field in rec or field == "created_at_utc", field
    saved = json.loads(plog.predictions_file.read_text().strip())
    assert saved["result"] is None and saved["closing_odds"] is None and saved["clv"] is None
    # Uncalibrated MVP must refuse even with confirmed pitchers + real odds.
    assert rec["paper_bet_decision"] == "NO_BET"
    assert "calibrator_not_fitted" in rec["refusal_reasons"]
    assert rec["real_odds_present"] is True
    out = capsys.readouterr().out
    assert "MLB MONEYLINE SCANNER" in out
    assert "PAPER ONLY" in out
    assert "NO BET" in out
    assert "calibrator_not_fitted" in out


def test_scan_without_odds_fails_closed(tmp_path, capsys):
    records, _, _, _ = _run_scan(tmp_path, [_schedule_game()], [])
    rec = records[0]
    assert rec["real_odds_present"] is False
    assert rec["market_consensus_home_no_vig_prob"] is None
    assert "real_odds_missing" in rec["refusal_reasons"]
    assert "NO REAL ODDS" in capsys.readouterr().out


def test_scan_team_filter(tmp_path):
    other = _schedule_game(888001) | {
        "home_team": "Boston Red Sox", "away_team": "Tampa Bay Rays",
        "event_id": "mlb-statsapi-888001",
    }
    records, _, _, _ = _run_scan(
        tmp_path, [_schedule_game(), other], [_odds_game()], team_filter="yankees"
    )
    assert len(records) == 1
    assert records[0]["home_team"] == "New York Yankees"


def test_scan_passes_manual_refresh_flags_only(tmp_path):
    _, _, _, odds_client = _run_scan(
        tmp_path, [_schedule_game()], [_odds_game()], force_refresh_odds=True
    )
    odds_client.fetch_moneyline.assert_called_once_with(
        force_refresh=True, selected_event_ids=None
    )


def test_scan_unconfirmed_pitchers_refused_and_never_invented(tmp_path):
    records, _, _, _ = _run_scan(
        tmp_path, [_schedule_game(confirmed=False)], [_odds_game()]
    )
    rec = records[0]
    assert rec["pitcher_confirmed"] is False
    assert rec["probable_pitchers"] == {"home": None, "away": None}
    assert "probable_pitchers_not_confirmed" in rec["refusal_reasons"]
