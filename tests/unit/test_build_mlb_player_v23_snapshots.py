from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_builder():
    path = Path(__file__).resolve().parents[2] / "scripts" / "build_mlb_player_v23.py"
    spec = importlib.util.spec_from_file_location("build_mlb_player_v23", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_training_rows_use_historical_starter_snapshots_over_team_proxy():
    builder = _load_builder()
    games = [
        {
            "date": "2025-04-01",
            "game_id": "g1",
            "home_team": "Home",
            "away_team": "Away",
            "home_score": 5,
            "away_score": 4,
        }
    ]
    snapshots = {
        "g1": {
            "home": {
                "starter_skill_ra9": 3.30,
                "projected_innings": 6.2,
                "previous_pitch_count": 97.0,
                "rest_days": 5.0,
                "starter_run_value": 0.72,
                "missing_flag": 0.0,
            },
            "away": {
                "starter_skill_ra9": 5.10,
                "projected_innings": 4.8,
                "previous_pitch_count": 83.0,
                "rest_days": 3.0,
                "starter_run_value": -0.31,
                "missing_flag": 0.0,
            },
        }
    }

    rows, state = builder.build_training_rows(games, starter_snapshots=snapshots)

    assert len(rows) == 1
    row = rows[0]
    assert row["home_sp_workload"] == 97.0
    assert row["away_sp_rest_days"] == 3.0
    assert row["home_sp_projected_innings"] == 6.2
    assert row["away_starter_run_value"] == -0.31
    assert row["starter_run_value_diff"] == 0.75
    assert row["player_feature_missing_flag"] == 0.0
    assert state["_starter_snapshot_coverage"]["games_with_both_starter_snapshots"] == 1
