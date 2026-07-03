from __future__ import annotations

import json

import pytest

from alpha.data.ingestion.mlb_player_database import (
    normalize_absence_rows,
    normalize_batter_rows,
    normalize_bullpen_rows,
    normalize_lineup_rows,
    normalize_pitcher_rows,
)
from alpha.engines.sports.mlb_player_feature_interpreter import (
    build_event_player_features,
    write_event_player_features_file,
)


def _snapshot(updated_at: str = "2026-06-28T10:00:00+00:00") -> dict:
    return {
        "updated_at": updated_at,
        "components": {
            "batters": normalize_batter_rows([
                {"player": "Home Bat", "team": "Home", "date": "2026-06-27", "war": 4.0, "xwoba": 0.390, "wrc_plus": 160, "lineup_spot": 1},
                {"player": "Away Bat", "team": "Away", "date": "2026-06-27", "war": 2.0, "xwoba": 0.310, "wrc_plus": 95, "lineup_spot": 1},
            ]),
            "pitchers": normalize_pitcher_rows([
                {"player": "Home Starter", "team": "Home", "date": "2026-06-27", "role": "SP", "war": 4.0, "xera": 2.80, "fip": 3.00, "k_bb_pct": 0.24, "rest_days": 5, "pitch_count_workload": 92},
                {"player": "Away Starter", "team": "Away", "date": "2026-06-27", "role": "SP", "war": 1.0, "xera": 4.80, "fip": 4.90, "k_bb_pct": 0.10, "rest_days": 5, "pitch_count_workload": 88},
            ]),
            "bullpen": normalize_bullpen_rows([
                {"team": "Home", "date": "2026-06-27", "xera": 3.00, "fip": 3.20, "k_bb_pct": 0.22, "pitch_count_workload": 40},
                {"team": "Away", "date": "2026-06-27", "xera": 4.90, "fip": 5.10, "k_bb_pct": 0.10, "pitch_count_workload": 61},
            ]),
            "lineups": normalize_lineup_rows([
                {"game_id": "g1", "player": "Home Bat", "team": "Home", "date": "2026-06-28", "order": 1, "confirmed": "true", "bats": "L"},
                {"game_id": "g1", "player": "Away Bat", "team": "Away", "date": "2026-06-28", "order": 1, "confirmed": "true", "bats": "R"},
            ]),
            "absences": normalize_absence_rows([
                {"game_id": "g1", "player": "Away Missing", "team": "Away", "date": "2026-06-28", "absence_value": 0.2},
            ]),
        },
    }


def test_build_event_player_features_interprets_components():
    games = [{
        "event_id": "g1",
        "home_team": "Home",
        "away_team": "Away",
        "home_probable_pitcher": "Home Starter",
        "away_probable_pitcher": "Away Starter",
    }]

    result = build_event_player_features(games, _snapshot(), target_date="2026-06-28")

    g1 = result["g1"]
    assert g1["home_sp_quality"] > g1["away_sp_quality"]
    assert g1["lineup_strength_diff"] > 0
    assert g1["bullpen_quality_diff"] > 0
    assert g1["absence_value_diff"] < 0
    assert g1["player_source_confidence"] == pytest.approx(1.0)
    assert g1["player_data_stale_flag"] == pytest.approx(0.0)


def test_general_unconfirmed_lineups_get_medium_confidence():
    snap = _snapshot()
    for row in snap["components"]["lineups"]:
        row["confirmed"] = False
        row["source"] = "mlb_statsapi_general_lineup"
    games = [{
        "event_id": "g1",
        "home_team": "Home",
        "away_team": "Away",
        "home_probable_pitcher": "Home Starter",
        "away_probable_pitcher": "Away Starter",
    }]

    result = build_event_player_features(games, snap, target_date="2026-06-28")

    assert result["g1"]["lineup_source_confidence"] == pytest.approx(0.8)
    assert result["g1"]["home_lineup_source"] == "mlb_statsapi_general_lineup"


def test_build_event_player_features_marks_stale_low_confidence():
    games = [{"event_id": "g1", "home_team": "Home", "away_team": "Away"}]

    result = build_event_player_features(
        games,
        _snapshot(updated_at="2026-06-20T10:00:00+00:00"),
        target_date="2026-06-28",
    )

    assert result["g1"]["player_data_stale_flag"] == pytest.approx(1.0)
    assert result["g1"]["player_source_confidence"] < 0.8


def test_write_event_player_features_file(tmp_path):
    output = tmp_path / "features.json"
    write_event_player_features_file(
        output,
        games=[{"event_id": "g1", "home_team": "Home", "away_team": "Away"}],
        database_snapshot=_snapshot(),
        target_date="2026-06-28",
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "mlb-player-features-v2.3"
    assert "g1" in payload["events"]
