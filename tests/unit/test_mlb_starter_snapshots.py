from __future__ import annotations

import pytest

from alpha.data.ingestion.mlb_starter_snapshots import (
    build_snapshots_from_lines,
    extract_starter_lines,
    starter_snapshot_to_training_features,
)


def test_extract_starter_lines_reads_actual_first_pitcher_boxscore_line():
    feed = {
        "gamePk": 1,
        "liveData": {
            "boxscore": {
                "teams": {
                    "home": {
                        "team": {"name": "Home"},
                        "pitchers": [10, 11],
                        "players": {
                            "ID10": {
                                "person": {"fullName": "Home Starter"},
                                "stats": {
                                    "pitching": {
                                        "inningsPitched": "6.1",
                                        "outs": 19,
                                        "strikeOuts": 7,
                                        "baseOnBalls": 2,
                                        "hitByPitch": 1,
                                        "homeRuns": 1,
                                        "battersFaced": 25,
                                        "numberOfPitches": 94,
                                    }
                                },
                            }
                        },
                    },
                    "away": {"pitchers": [], "players": {}},
                }
            }
        },
    }
    game = {"game_id": "1", "date": "2025-04-01", "home_team": "Home", "away_team": "Away"}

    lines = extract_starter_lines(feed, game)

    assert len(lines) == 1
    assert lines[0]["pitcher_name"] == "Home Starter"
    assert lines[0]["innings_pitched"] == pytest.approx(6 + 1 / 3)
    assert lines[0]["pitch_count"] == 94.0


def test_build_snapshots_are_as_of_prior_starts():
    lines = [
        {
            "game_id": "g1",
            "game_date": "2025-04-01",
            "side": "home",
            "team": "A",
            "opponent": "B",
            "pitcher_id": "p1",
            "pitcher_name": "Starter",
            "outs": 18,
            "strikeouts": 6,
            "walks": 1,
            "hbp": 0,
            "home_runs": 1,
            "batters_faced": 23,
            "pitch_count": 88,
        },
        {
            "game_id": "g2",
            "game_date": "2025-04-07",
            "side": "away",
            "team": "A",
            "opponent": "C",
            "pitcher_id": "p1",
            "pitcher_name": "Starter",
            "outs": 15,
            "strikeouts": 5,
            "walks": 2,
            "hbp": 0,
            "home_runs": 0,
            "batters_faced": 21,
            "pitch_count": 91,
        },
    ]

    snapshots = build_snapshots_from_lines(lines)
    first = snapshots["g1"]["home"]
    second = snapshots["g2"]["away"]

    assert first["prior_starts"] == 0
    assert first["missing_flag"] == 1.0
    assert second["prior_starts"] == 1
    assert second["prior_ip"] == pytest.approx(6.0)
    assert second["rest_days"] == 5.0
    assert second["previous_pitch_count"] == 88.0
    assert second["k_bb_pct"] == pytest.approx((6 - 1) / 23)
    assert second["source_confidence"] == pytest.approx(0.2)


def test_starter_snapshot_maps_to_training_features():
    snapshot = {
        "starter_skill_ra9": 3.60,
        "projected_innings": 6.0,
        "previous_pitch_count": 92.0,
        "rest_days": 5.0,
        "starter_run_value": 0.60,
        "missing_flag": 0.0,
    }

    features = starter_snapshot_to_training_features(snapshot)

    assert features["sp_quality"] == pytest.approx((8.0 - 3.60) / 6.0)
    assert features["sp_projected_innings"] == 6.0
    assert features["sp_workload"] == 92.0
    assert features["starter_run_value"] == 0.60
    assert features["sp_missing"] == 0.0
