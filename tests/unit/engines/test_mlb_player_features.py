from __future__ import annotations

import pytest

from alpha.engines.sports.mlb_player_features import build_player_aware_game_rows
from alpha.engines.sports.mlb_training import FEATURE_NAMES


def _games():
    return [
        {
            "game_id": "g1",
            "game_date": "2026-04-01",
            "game_number": 1,
            "home_team": "A",
            "away_team": "B",
            "home_starter_id": "p1",
            "away_starter_id": "p2",
            "home_win": 1,
        },
        {
            "game_id": "g2",
            "game_date": "2026-04-01",
            "game_number": 2,
            "home_team": "A",
            "away_team": "B",
            "home_starter_id": "p1",
            "away_starter_id": "p2",
            "home_win": 0,
        },
        {
            "game_id": "g3",
            "game_date": "2026-04-02",
            "game_number": 1,
            "home_team": "A",
            "away_team": "B",
            "home_starter_id": "p1",
            "away_starter_id": "p2",
            "home_win": 1,
        },
    ]


def _slots(game_id: str):
    return [
        {"game_id": game_id, "team": "A", "side": "home", "player_id": "b1", "player_name": "B One", "batting_order": 1, "bats": "L", "confirmed": True},
        {"game_id": game_id, "team": "A", "side": "home", "player_id": "b2", "player_name": "B Two", "batting_order": 2, "bats": "R", "confirmed": False},
        {"game_id": game_id, "team": "B", "side": "away", "player_id": "b3", "player_name": "B Three", "batting_order": 1, "bats": "R", "confirmed": True},
    ]


def test_starter_features_shift_before_target_game():
    rows = build_player_aware_game_rows(
        [_games()[2]],
        _slots("g3"),
        pitcher_logs=[
            {"player_id": "p1", "game_date": "2026-04-01", "game_number": 1, "starter_quality": 2.0, "pitch_count": 90},
            {"player_id": "p1", "game_date": "2026-04-02", "game_number": 1, "starter_quality": 99.0, "pitch_count": 99},
            {"player_id": "p2", "game_date": "2026-04-01", "game_number": 1, "starter_quality": 1.0, "pitch_count": 80},
        ],
    )

    row = rows[0]
    assert row["home_sp_quality"] == 2.0
    assert row["away_sp_quality"] == 1.0
    assert row["sp_quality_diff"] == 1.0
    assert row["home_sp_workload"] == 90.0
    assert row["home_sp_missing"] == 0.0


def test_lineup_features_include_strength_missing_and_confirmation():
    rows = build_player_aware_game_rows(
        [_games()[2]],
        _slots("g3") + [{"game_id": "g3", "team": "A", "side": "home", "batting_order": 3, "confirmed": False}],
        batter_logs=[
            {"player_id": "b1", "game_date": "2026-04-01", "batting_value": 0.400, "bats": "L"},
            {"player_id": "b2", "game_date": "2026-04-01", "batting_value": 0.300, "bats": "R"},
            {"player_id": "b3", "game_date": "2026-04-01", "batting_value": 0.250, "bats": "R"},
        ],
    )

    row = rows[0]
    assert row["home_lineup_strength"] == pytest.approx((0.400 + 0.300 + 0.0) / 3)
    assert row["away_lineup_strength"] == 0.250
    assert row["lineup_strength_diff"] == pytest.approx(((0.400 + 0.300 + 0.0) / 3) - 0.250)
    assert row["home_lineup_lefty_share"] == pytest.approx(1 / 3)
    assert row["home_lineup_missing_count"] == 1.0
    assert row["home_lineup_confirmed_share"] == pytest.approx(1 / 3)
    assert row["player_feature_missing_flag"] == 1.0


def test_bullpen_features_exclude_same_day_by_default_and_allow_explicit_between_games():
    games = _games()[:2]
    relief_logs = [
        {"team": "A", "game_date": "2026-03-31", "game_number": 1, "pitches": 10, "relief_quality": 0.8},
        {"team": "A", "game_date": "2026-04-01", "game_number": 1, "pitches": 50, "relief_quality": 0.1},
    ]

    default_rows = build_player_aware_game_rows(games, _slots("g1") + _slots("g2"), relief_logs=relief_logs)
    between_rows = build_player_aware_game_rows(
        games,
        _slots("g1") + _slots("g2"),
        relief_logs=relief_logs,
        allow_between_games=True,
    )

    assert default_rows[1]["home_bp_recent_pitches"] == 10.0
    assert between_rows[1]["home_bp_recent_pitches"] == 60.0
    assert default_rows[1]["home_bp_quality"] == 0.8
    assert between_rows[1]["home_bp_quality"] == 0.45


def test_absence_features_use_structured_game_team_rows():
    rows = build_player_aware_game_rows(
        [_games()[2]],
        _slots("g3"),
        absence_rows=[
            {"game_id": "g3", "team": "A", "player_id": "b1", "absence_value": 0.35, "status": "out"},
            {"game_id": "g3", "team": "B", "player_id": "b3", "absence_value": 0.10, "status": "out"},
        ],
    )

    row = rows[0]
    assert row["home_absence_value"] == 0.35
    assert row["away_absence_value"] == 0.10
    assert row["absence_value_diff"] == pytest.approx(0.25)
    assert row["home_absence_count"] == 1.0


def test_row_builder_preserves_targets_and_v1_3_schema_is_unchanged():
    rows = build_player_aware_game_rows([_games()[0]], _slots("g1"))

    assert rows[0]["game_id"] == "g1"
    assert rows[0]["home_win"] == 1
    assert FEATURE_NAMES == (
        "elo_diff",
        "home_win_pct",
        "away_win_pct",
        "home_run_diff",
        "away_run_diff",
        "home_rest_days",
        "away_rest_days",
        "home_indicator",
    )
