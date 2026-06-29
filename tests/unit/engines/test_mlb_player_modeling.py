from __future__ import annotations

from datetime import date, timedelta

from alpha.engines.sports.mlb_player_modeling import (
    BASELINE_FEATURES,
    PLAYER_FEATURE_SETS,
    available_model_factories,
    build_model_artifact_metadata,
    run_walkforward_ablations,
    score_probabilities,
    select_promoted_result,
    walkforward_train_cal_test_splits,
)
from alpha.engines.sports.mlb_training import FEATURE_NAMES


def _rows(n: int = 36) -> list[dict]:
    start = date(2025, 4, 1)
    rows = []
    for i in range(n):
        home_win = int(i % 4 in (0, 1))
        signal = 1.0 if home_win else -1.0
        rows.append(
            {
                "game_id": f"g{i:03d}",
                "game_date": (start + timedelta(days=i)).isoformat(),
                "home_win": home_win,
                "elo_diff": signal * 8.0 + (i % 3),
                "home_win_pct": 0.51 + signal * 0.01,
                "away_win_pct": 0.49 - signal * 0.01,
                "home_run_diff": signal * 0.1,
                "away_run_diff": -signal * 0.1,
                "home_rest_days": float(2 + i % 3),
                "away_rest_days": float(2 + (i + 1) % 3),
                "home_indicator": 1.0,
                "home_sp_quality": 3.0 + signal,
                "away_sp_quality": 3.0 - signal,
                "sp_quality_diff": signal * 2.0,
                "home_sp_workload": 88.0 - signal * 2.0,
                "away_sp_workload": 88.0 + signal * 2.0,
                "sp_workload_diff": -signal * 4.0,
                "home_sp_rest_days": 5.0 + signal,
                "away_sp_rest_days": 5.0 - signal,
                "home_sp_missing": 0.0,
                "away_sp_missing": 0.0,
                "home_lineup_strength": 0.330 + signal * 0.020,
                "away_lineup_strength": 0.330 - signal * 0.020,
                "lineup_strength_diff": signal * 0.040,
                "home_top_order_strength": 0.360 + signal * 0.020,
                "away_top_order_strength": 0.360 - signal * 0.020,
                "top_order_strength_diff": signal * 0.040,
                "home_lineup_lefty_share": 0.44,
                "away_lineup_lefty_share": 0.33,
                "home_lineup_missing_count": 0.0,
                "away_lineup_missing_count": 0.0,
                "lineup_missing_count_total": 0.0,
                "home_lineup_confirmed_share": 1.0,
                "away_lineup_confirmed_share": 1.0,
                "home_bp_recent_pitches": 44.0 - signal * 8.0,
                "away_bp_recent_pitches": 44.0 + signal * 8.0,
                "bullpen_recent_pitches_diff": -signal * 16.0,
                "home_bp_quality": 2.0 + signal,
                "away_bp_quality": 2.0 - signal,
                "bullpen_quality_diff": signal * 2.0,
                "home_bp_missing": 0.0,
                "away_bp_missing": 0.0,
                "home_absence_value": 0.0 if home_win else 0.2,
                "away_absence_value": 0.2 if home_win else 0.0,
                "absence_value_diff": -signal * 0.2,
                "home_absence_count": 0.0 if home_win else 1.0,
                "away_absence_count": 1.0 if home_win else 0.0,
                "player_feature_missing_flag": 0.0,
            }
        )
    return rows


def test_feature_sets_include_expected_ablations_and_baseline_schema():
    assert BASELINE_FEATURES == FEATURE_NAMES
    assert list(PLAYER_FEATURE_SETS) == [
        "baseline_v1_3",
        "starter_only",
        "starter_lineup",
        "starter_lineup_bullpen",
        "full_player_aware",
    ]
    assert PLAYER_FEATURE_SETS["baseline_v1_3"] == FEATURE_NAMES
    assert "home_sp_quality" in PLAYER_FEATURE_SETS["starter_only"]
    assert "lineup_strength_diff" in PLAYER_FEATURE_SETS["starter_lineup"]
    assert "bullpen_quality_diff" in PLAYER_FEATURE_SETS["starter_lineup_bullpen"]
    assert "absence_value_diff" in PLAYER_FEATURE_SETS["full_player_aware"]


def test_walkforward_splits_are_chronological_train_calibration_test():
    rows = _rows()
    folds = walkforward_train_cal_test_splits(
        rows,
        min_train=12,
        calibration_size=6,
        test_size=6,
        step_size=6,
    )

    assert len(folds) == 3
    for fold in folds:
        train_dates = [rows[i]["game_date"] for i in fold.train_indices]
        calibration_dates = [rows[i]["game_date"] for i in fold.calibration_indices]
        test_dates = [rows[i]["game_date"] for i in fold.test_indices]
        assert max(train_dates) < min(calibration_dates)
        assert max(calibration_dates) < min(test_dates)


def test_run_walkforward_ablations_reports_models_feature_sets_and_metrics():
    report = run_walkforward_ablations(
        _rows(),
        feature_sets={
            "baseline_v1_3": PLAYER_FEATURE_SETS["baseline_v1_3"],
            "full_player_aware": PLAYER_FEATURE_SETS["full_player_aware"],
        },
        model_names=["logistic"],
        split_kwargs={"min_train": 12, "calibration_size": 6, "test_size": 6, "step_size": 6},
    )

    assert report["schema_version"] == "mlb-player-v1.8"
    assert report["models"] == ["logistic"]
    assert len(report["ablations"]) == 2
    for ablation in report["ablations"]:
        assert ablation["folds"]
        assert {"brier_score", "log_loss", "accuracy", "coverage", "selective_win_rate", "n"} <= set(ablation["mean_metrics"])
        assert "reliability_table" in ablation["folds"][0]["metrics"]


def test_score_probabilities_includes_selective_metrics():
    metrics = score_probabilities([1, 0, 1, 0], [0.72, 0.31, 0.51, 0.49])

    assert metrics["coverage"] == 0.5
    assert metrics["selective_win_rate"] == 1.0


def test_lightgbm_is_optional_and_core_models_are_available():
    factories = available_model_factories()

    assert {"logistic", "hist_gradient_boosting"} <= set(factories)
    if "lightgbm" in factories:
        assert callable(factories["lightgbm"])


def test_artifact_metadata_contains_schema_features_split_dates_metrics_and_gates():
    report = run_walkforward_ablations(
        _rows(),
        feature_sets={
            "baseline_v1_3": PLAYER_FEATURE_SETS["baseline_v1_3"],
            "full_player_aware": PLAYER_FEATURE_SETS["full_player_aware"],
        },
        model_names=["logistic"],
        split_kwargs={"min_train": 12, "calibration_size": 6, "test_size": 6, "step_size": 6},
    )
    candidate = select_promoted_result(report) or report["ablations"][-1]

    metadata = build_model_artifact_metadata(
        candidate,
        report,
        source_fingerprints={"player_rows": "sha256:test"},
    )

    assert metadata["schema_version"] == "mlb-player-v1.8"
    assert metadata["feature_names"] == candidate["features"]
    assert metadata["split_dates"][0]["train_start"] == "2025-04-01"
    assert metadata["metrics"]["n"] == 18
    assert metadata["source_fingerprints"] == {"player_rows": "sha256:test"}
    assert {"baseline_available", "candidate_improves_baseline_brier", "has_walkforward_folds", "has_feature_schema"} <= set(
        metadata["promotion_gates"]
    )
