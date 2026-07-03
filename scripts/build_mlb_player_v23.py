"""Build and package the v2.3 lineup/bullpen-aware MLB moneyline artifact."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("build_mlb_player_v23")

_OUTPUT_PATH = ROOT / "alpha" / "models" / "mlb_player_moneyline.pkl"
_DEFAULT_START = "2023-03-01"
_DEFAULT_END = "2026-06-29"
_SCHEMA_VERSION = "mlb-player-v2.3"
_LEAGUE_RA9 = 4.50
_STARTER_RUN_DIFF_CAP = 0.75
_LINEUP_RUN_DIFF_CAP = 0.35
_TOP_ORDER_RUN_DIFF_CAP = 0.20
_BULLPEN_RUN_DIFF_CAP = 0.15
_ABSENCE_RUN_DIFF_CAP = 0.50
_BULLPEN_RUN_SHRINK = 0.0875


def fetch_historical_games(start: str, end: str, *, cache_path: Path | None = None) -> list[dict]:
    import statsapi  # noqa: PLC0415

    if cache_path and cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    start_d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    result: list[dict] = []
    cursor = start_d
    while cursor <= end_d:
        next_month = date(cursor.year + int(cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
        chunk_end_d = min(end_d, next_month - timedelta(days=1))
        chunk_start = cursor.isoformat()
        chunk_end = chunk_end_d.isoformat()
        logger.info("Fetching games (%s -> %s)...", chunk_start, chunk_end)
        try:
            schedule = statsapi.schedule(start_date=chunk_start, end_date=chunk_end)
        except Exception as exc:
            logger.warning("StatsAPI failed for %s -> %s: %s", chunk_start, chunk_end, exc)
            cursor = chunk_end_d + timedelta(days=1)
            continue
        for game in schedule:
            if game.get("status") != "Final":
                continue
            if game.get("game_type", "R") not in ("R", "F", "D", "L", "W"):
                continue
            result.append({
                "date": str(game.get("game_date", game.get("game_datetime", "")))[:10],
                "game_id": str(game.get("game_id", "")),
                "home_team": game.get("home_name", ""),
                "away_team": game.get("away_name", ""),
                "home_score": game.get("home_score"),
                "away_score": game.get("away_score"),
            })
        cursor = chunk_end_d + timedelta(days=1)
    deduped: dict[str, dict] = {}
    for game in result:
        deduped.setdefault(game["game_id"], game)
    games = list(deduped.values())
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(games, indent=2), encoding="utf-8")
    return games


def load_starter_snapshots(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload.get("snapshots") or {})


def build_training_rows(games: list[dict], starter_snapshots: dict[str, dict[str, Any]] | None = None) -> tuple[list[dict], dict]:
    from alpha.data.ingestion.mlb_starter_snapshots import starter_snapshot_to_training_features
    from alpha.engines.sports.mlb_training import TeamState, feature_vector

    states: dict[str, TeamState] = {}
    starter_snapshots = starter_snapshots or {}
    rows: list[dict] = []
    snapshot_used = 0
    snapshot_missing = 0
    for game in sorted(games, key=lambda g: (str(g["date"]), str(g.get("game_id", "")))):
        home_team = str(game["home_team"])
        away_team = str(game["away_team"])
        game_date = str(game["date"])[:10]
        home_score = game.get("home_score")
        away_score = game.get("away_score")
        if home_score is None or away_score is None or float(home_score) == float(away_score):
            continue

        home_state = states.setdefault(home_team, TeamState())
        away_state = states.setdefault(away_team, TeamState())
        base = feature_vector(home_state, away_state, game_date)
        home_offense = _offense_quality(home_state)
        away_offense = _offense_quality(away_state)
        home_pitching = _pitching_quality(home_state)
        away_pitching = _pitching_quality(away_state)
        home_bp_pitches = _bullpen_recent_pitches_proxy(home_state, game_date)
        away_bp_pitches = _bullpen_recent_pitches_proxy(away_state, game_date)
        game_snapshots = starter_snapshots.get(str(game.get("game_id", ""))) or {}
        home_starter = starter_snapshot_to_training_features(game_snapshots.get("home"))
        away_starter = starter_snapshot_to_training_features(game_snapshots.get("away"))
        if home_starter and away_starter:
            snapshot_used += 1
        else:
            snapshot_missing += 1
        home_starter_run_value = home_starter.get("starter_run_value", _starter_run_value_proxy(home_state))
        away_starter_run_value = away_starter.get("starter_run_value", _starter_run_value_proxy(away_state))
        home_sp_projected_innings = home_starter.get("sp_projected_innings", 5.3)
        away_sp_projected_innings = away_starter.get("sp_projected_innings", 5.3)
        home_lineup_run_value = _lineup_run_value_proxy(home_state)
        away_lineup_run_value = _lineup_run_value_proxy(away_state)
        home_bp_run_value = _bullpen_run_value_proxy(home_state, projected_starter_ip=home_sp_projected_innings)
        away_bp_run_value = _bullpen_run_value_proxy(away_state, projected_starter_ip=away_sp_projected_innings)
        starter_run_value_diff = _clamp(home_starter_run_value - away_starter_run_value, _STARTER_RUN_DIFF_CAP)
        lineup_run_value_diff = _clamp(home_lineup_run_value - away_lineup_run_value, _LINEUP_RUN_DIFF_CAP)
        top_order_run_value_diff = _clamp((home_lineup_run_value - away_lineup_run_value) * 0.58, _TOP_ORDER_RUN_DIFF_CAP)
        bullpen_run_value_diff = _clamp(home_bp_run_value - away_bp_run_value, _BULLPEN_RUN_DIFF_CAP)
        absence_run_value_diff = 0.0

        rows.append({
            "date": game_date,
            "game_date": game_date,
            "game_id": game.get("game_id", ""),
            "home_team": home_team,
            "away_team": away_team,
            **base,
            "home_sp_quality": home_starter.get("sp_quality", home_pitching),
            "away_sp_quality": away_starter.get("sp_quality", away_pitching),
            "sp_quality_diff": home_starter.get("sp_quality", home_pitching) - away_starter.get("sp_quality", away_pitching),
            "home_sp_workload": home_starter.get("sp_workload", 90.0),
            "away_sp_workload": away_starter.get("sp_workload", 90.0),
            "sp_workload_diff": home_starter.get("sp_workload", 90.0) - away_starter.get("sp_workload", 90.0),
            "home_sp_rest_days": home_starter.get("sp_rest_days", base["home_rest_days"] + 1.0),
            "away_sp_rest_days": away_starter.get("sp_rest_days", base["away_rest_days"] + 1.0),
            "home_sp_projected_innings": home_sp_projected_innings,
            "away_sp_projected_innings": away_sp_projected_innings,
            "home_starter_skill_ra9": home_starter.get("starter_skill_ra9", _team_ra9(home_state)),
            "away_starter_skill_ra9": away_starter.get("starter_skill_ra9", _team_ra9(away_state)),
            "home_starter_run_value": home_starter_run_value,
            "away_starter_run_value": away_starter_run_value,
            "starter_run_value_diff": starter_run_value_diff,
            "home_sp_missing": home_starter.get("sp_missing", 0.0 if not starter_snapshots else 1.0),
            "away_sp_missing": away_starter.get("sp_missing", 0.0 if not starter_snapshots else 1.0),
            "home_lineup_strength": home_offense,
            "away_lineup_strength": away_offense,
            "lineup_strength_diff": home_offense - away_offense,
            "home_lineup_run_value": home_lineup_run_value,
            "away_lineup_run_value": away_lineup_run_value,
            "lineup_run_value_diff": lineup_run_value_diff,
            "home_top_order_strength": min(1.25, home_offense * 1.04),
            "away_top_order_strength": min(1.25, away_offense * 1.04),
            "top_order_strength_diff": (home_offense - away_offense) * 1.04,
            "home_top_order_run_value": home_lineup_run_value * 0.58,
            "away_top_order_run_value": away_lineup_run_value * 0.58,
            "top_order_run_value_diff": top_order_run_value_diff,
            "home_lineup_lefty_share": 0.33,
            "away_lineup_lefty_share": 0.33,
            "home_lineup_missing_count": 0.0,
            "away_lineup_missing_count": 0.0,
            "lineup_missing_count_total": 0.0,
            "home_lineup_confirmed_share": 0.0,
            "away_lineup_confirmed_share": 0.0,
            "home_bp_recent_pitches": home_bp_pitches,
            "away_bp_recent_pitches": away_bp_pitches,
            "bullpen_recent_pitches_diff": home_bp_pitches - away_bp_pitches,
            "home_bp_quality": home_pitching,
            "away_bp_quality": away_pitching,
            "bullpen_quality_diff": home_pitching - away_pitching,
            "home_bullpen_skill_ra9": _team_ra9(home_state),
            "away_bullpen_skill_ra9": _team_ra9(away_state),
            "home_bullpen_run_value": home_bp_run_value,
            "away_bullpen_run_value": away_bp_run_value,
            "bullpen_run_value_diff": bullpen_run_value_diff,
            "home_bp_missing": 0.0,
            "away_bp_missing": 0.0,
            "home_absence_value": 0.0,
            "away_absence_value": 0.0,
            "absence_value_diff": 0.0,
            "home_absence_run_value": 0.0,
            "away_absence_run_value": 0.0,
            "absence_run_value_diff": absence_run_value_diff,
            "home_absence_count": 0.0,
            "away_absence_count": 0.0,
            "player_run_value_diff": (
                starter_run_value_diff
                + lineup_run_value_diff
                + bullpen_run_value_diff
                - absence_run_value_diff
            ),
            "player_feature_missing_flag": float(
                home_starter.get("sp_missing", 0.0 if not starter_snapshots else 1.0) >= 1.0
                or away_starter.get("sp_missing", 0.0 if not starter_snapshots else 1.0) >= 1.0
            ),
            "home_win": int(float(home_score) > float(away_score)),
        })

        _update_state(home_state, away_state, float(home_score), float(away_score), game_date)

    team_state = {team: asdict(state) for team, state in states.items()}
    team_state["_starter_snapshot_coverage"] = {
        "games_with_both_starter_snapshots": snapshot_used,
        "games_missing_any_starter_snapshot": snapshot_missing,
    }
    return rows, team_state


def _offense_quality(state) -> float:
    if state.games <= 0:
        return 0.72
    runs_per_game = state.runs_for / state.games
    return max(0.45, min(1.05, 0.55 + (runs_per_game - 3.0) / 6.0))


def _pitching_quality(state) -> float:
    if state.games <= 0:
        return 0.50
    runs_allowed = state.runs_against / state.games
    return max(0.0, min(1.0, (8.0 - runs_allowed) / 6.0))


def _team_ra9(state) -> float:
    if state.games <= 0:
        return _LEAGUE_RA9
    return max(2.5, min(7.0, state.runs_against / state.games))


def _starter_run_value_proxy(state) -> float:
    return (5.3 / 9.0) * (_LEAGUE_RA9 - _team_ra9(state))


def _lineup_run_value_proxy(state) -> float:
    if state.games <= 0:
        return 0.0
    return max(-1.5, min(1.5, state.runs_for / state.games - _LEAGUE_RA9))


def _bullpen_run_value_proxy(state, *, projected_starter_ip: float) -> float:
    expected_bullpen_ip = max(0.0, 9.0 - projected_starter_ip)
    return _BULLPEN_RUN_SHRINK * (expected_bullpen_ip / 9.0) * (_LEAGUE_RA9 - _team_ra9(state))


def _clamp(value: float, cap: float) -> float:
    return max(-cap, min(cap, value))


def _bullpen_recent_pitches_proxy(state, game_date: str) -> float:
    if not state.last_date:
        return 0.0
    rest = max(0.0, min(7.0, (date.fromisoformat(game_date) - date.fromisoformat(state.last_date)).days - 1))
    return max(0.0, 45.0 - rest * 12.0)


def _update_state(home, away, home_score: float, away_score: float, game_date: str) -> None:
    expected = 1.0 / (1.0 + 10.0 ** ((away.elo - home.elo) / 400.0))
    outcome = home_score > away_score
    change = 20.0 * (float(outcome) - expected)
    home.elo += change
    away.elo -= change
    home.games += 1
    away.games += 1
    home.wins += int(outcome)
    away.wins += int(not outcome)
    home.runs_for += home_score
    home.runs_against += away_score
    away.runs_for += away_score
    away.runs_against += home_score
    home.last_date = game_date
    away.last_date = game_date


def run_ablation(rows: list[dict], *, model_names: list[str], step_size: int) -> dict:
    from alpha.engines.sports.mlb_player_modeling import PLAYER_FEATURE_SETS, run_walkforward_ablations

    feature_sets = {
        key: value
        for key, value in PLAYER_FEATURE_SETS.items()
        if key in ("baseline_v1_3", "starter_only", "run_components", "run_aggregate", "starter_lineup", "starter_lineup_bullpen", "full_player_aware")
    }
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="X does not have valid feature names")
        return run_walkforward_ablations(
            rows,
            feature_sets=feature_sets,
            model_names=model_names,
            split_kwargs={"step_size": step_size},
        )


def run_offset_ablations(rows: list[dict], *, step_size: int) -> list[dict]:
    from alpha.engines.sports.mlb_player_modeling import PLAYER_FEATURE_SETS, walkforward_train_cal_test_splits

    folds = walkforward_train_cal_test_splits(rows, step_size=step_size)
    experiments = {
        "offset_player_run": ("player_run_value_diff",),
        "offset_starter_run": ("starter_run_value_diff",),
        "offset_starter_absence_run": ("starter_run_value_diff", "absence_run_value_diff"),
    }
    reports: list[dict] = []
    for name, offset_features in experiments.items():
        fold_reports = [
            _score_offset_fold(
                rows=rows,
                fold=fold,
                base_features=PLAYER_FEATURE_SETS["starter_only"],
                offset_features=offset_features,
            )
            for fold in folds
        ]
        reports.append({
            "feature_set": name,
            "model": "starter_only_logit_offset",
            "features": list(offset_features),
            "folds": fold_reports,
            "mean_metrics": _mean_offset_metrics([fold["metrics"] for fold in fold_reports]),
            "paired_metrics": _mean_paired_metrics(fold_reports),
            "mean_beta": {
                feature: sum(float(fold["betas"].get(feature, 0.0)) for fold in fold_reports) / len(fold_reports)
                for feature in offset_features
            },
            "beta_positive_fold_rate": {
                feature: sum(float(fold["betas"].get(feature, 0.0)) > 0.0 for fold in fold_reports) / len(fold_reports)
                for feature in offset_features
            },
        })
    return reports


def _score_offset_fold(*, rows: list[dict], fold, base_features: tuple[str, ...], offset_features: tuple[str, ...]) -> dict:
    import numpy as np  # noqa: PLC0415
    from alpha.engines.sports.mlb_player_modeling import available_model_factories, fit_sigmoid_calibrator, score_probabilities

    model = available_model_factories()["logistic"]()
    x_train = np.asarray([[_float_feature(rows[i], name) for name in base_features] for i in fold.train_indices], dtype=float)
    y_train = np.asarray([int(rows[i]["home_win"]) for i in fold.train_indices], dtype=int)
    x_cal = np.asarray([[_float_feature(rows[i], name) for name in base_features] for i in fold.calibration_indices], dtype=float)
    y_cal = np.asarray([int(rows[i]["home_win"]) for i in fold.calibration_indices], dtype=int)
    x_test = np.asarray([[_float_feature(rows[i], name) for name in base_features] for i in fold.test_indices], dtype=float)
    y_test = np.asarray([int(rows[i]["home_win"]) for i in fold.test_indices], dtype=int)
    if len(set(y_train.tolist())) < 2:
        base_cal = np.full(len(y_cal), float(y_train.mean()))
        base_test = np.full(len(y_test), float(y_train.mean()))
    else:
        model.fit(x_train, y_train)
        raw_cal = model.predict_proba(x_cal)[:, 1]
        calibrator = fit_sigmoid_calibrator(raw_cal.tolist(), y_cal.tolist())
        base_cal = np.asarray(calibrator.predict(raw_cal.tolist()), dtype=float)
        raw_test = model.predict_proba(x_test)[:, 1]
        base_test = np.asarray(calibrator.predict(raw_test.tolist()), dtype=float)

    betas = _fit_nonnegative_offset_betas(
        base_cal,
        y_cal,
        np.asarray([[_float_feature(rows[i], name) for name in offset_features] for i in fold.calibration_indices], dtype=float),
    )
    test_offsets = np.asarray([[_float_feature(rows[i], name) for name in offset_features] for i in fold.test_indices], dtype=float)
    probs = _sigmoid(_logit(base_test) + test_offsets @ betas)
    paired = _paired_probability_diagnostics(y_test, base_test, probs)
    return {
        **fold.as_metadata(),
        "metrics": score_probabilities(y_test.tolist(), probs.tolist()),
        "base_metrics": score_probabilities(y_test.tolist(), base_test.tolist()),
        "paired_metrics": paired,
        "betas": {feature: float(beta) for feature, beta in zip(offset_features, betas)},
    }


def _fit_nonnegative_offset_betas(base_probs, y_true, offsets):
    import numpy as np  # noqa: PLC0415

    if offsets.shape[1] == 0:
        return np.zeros(0)
    grid = np.linspace(0.0, 0.12, 25)
    best_beta = np.zeros(offsets.shape[1])
    best_score = float("inf")
    for candidate in _beta_grid(grid, offsets.shape[1]):
        probs = _sigmoid(_logit(base_probs) + offsets @ candidate)
        score = -np.mean((y_true * np.log(np.clip(probs, 1e-6, 1.0))) + ((1 - y_true) * np.log(np.clip(1.0 - probs, 1e-6, 1.0))))
        if score < best_score:
            best_score = float(score)
            best_beta = candidate
    return best_beta


def _beta_grid(grid, width: int):
    import itertools  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    if width == 1:
        for value in grid:
            yield np.asarray([value], dtype=float)
        return
    coarse = np.asarray([0.0, 0.02, 0.04, 0.08, 0.12], dtype=float)
    for values in itertools.product(coarse, repeat=width):
        yield np.asarray(values, dtype=float)


def _logit(probs):
    import numpy as np  # noqa: PLC0415

    clipped = np.clip(probs, 1e-6, 1.0 - 1e-6)
    return np.log(clipped / (1.0 - clipped))


def _sigmoid(values):
    import numpy as np  # noqa: PLC0415

    return 1.0 / (1.0 + np.exp(-values))


def _float_feature(row: dict, name: str) -> float:
    try:
        return float(row.get(name) if row.get(name) is not None else 0.0)
    except (TypeError, ValueError):
        return 0.0


def _mean_offset_metrics(metrics: list[dict]) -> dict:
    keys = ("brier_score", "log_loss", "accuracy", "coverage")
    total_n = sum(int(m["n"]) for m in metrics)
    result = {key: sum(float(m[key]) * int(m["n"]) for m in metrics) / total_n for key in keys}
    selective = [m for m in metrics if m.get("selective_win_rate") is not None]
    result["selective_win_rate"] = (
        sum(float(m["selective_win_rate"]) * int(m["n"]) for m in selective)
        / sum(int(m["n"]) for m in selective)
        if selective else None
    )
    result["n"] = total_n
    return result


def _paired_probability_diagnostics(y_true, base_probs, offset_probs) -> dict:
    import numpy as np  # noqa: PLC0415

    y = np.asarray(y_true, dtype=float)
    base = np.asarray(base_probs, dtype=float)
    offset = np.asarray(offset_probs, dtype=float)
    base_brier = (base - y) ** 2
    offset_brier = (offset - y) ** 2
    delta = offset_brier - base_brier
    return {
        "mean_delta_brier": float(np.mean(delta)),
        "median_delta_brier": float(np.median(delta)),
        "percent_games_improved": float(np.mean(delta < 0.0)),
        "fold_improved": bool(np.mean(delta) < 0.0),
        "n": int(len(y)),
    }


def _mean_paired_metrics(folds: list[dict]) -> dict:
    total_n = sum(int(fold["paired_metrics"]["n"]) for fold in folds)
    if total_n <= 0:
        return {
            "mean_delta_brier": 0.0,
            "median_delta_brier": 0.0,
            "percent_games_improved": 0.0,
            "folds_improved": 0,
            "fold_improvement_rate": 0.0,
            "n": 0,
        }
    return {
        "mean_delta_brier": sum(float(fold["paired_metrics"]["mean_delta_brier"]) * int(fold["paired_metrics"]["n"]) for fold in folds) / total_n,
        "median_delta_brier": sum(float(fold["paired_metrics"]["median_delta_brier"]) * int(fold["paired_metrics"]["n"]) for fold in folds) / total_n,
        "percent_games_improved": sum(float(fold["paired_metrics"]["percent_games_improved"]) * int(fold["paired_metrics"]["n"]) for fold in folds) / total_n,
        "folds_improved": sum(bool(fold["paired_metrics"]["fold_improved"]) for fold in folds),
        "fold_improvement_rate": sum(bool(fold["paired_metrics"]["fold_improved"]) for fold in folds) / len(folds),
        "n": total_n,
    }


def train_final_model(rows: list[dict], feature_names: tuple[str, ...], model_name: str):
    import numpy as np  # noqa: PLC0415
    from alpha.engines.sports.mlb_player_modeling import available_model_factories, fit_sigmoid_calibrator

    n = len(rows)
    split = int(n * 0.8)
    x_all = np.asarray([[float(row.get(name) if row.get(name) is not None else 0.0) for name in feature_names] for row in rows], dtype=float)
    y_all = np.asarray([int(row["home_win"]) for row in rows], dtype=int)
    factories = available_model_factories()
    model_key = model_name if model_name in factories else "logistic"
    model = factories[model_key]()
    model.fit(x_all[:split], y_all[:split])
    raw_cal = model.predict_proba(x_all[split:])[:, 1]
    calibrator = fit_sigmoid_calibrator(raw_cal.tolist(), y_all[split:].tolist())
    return model, calibrator


def package_artifact(promoted: dict, report: dict, model, calibrator, team_state: dict) -> dict:
    from alpha.engines.sports.mlb_player_modeling import build_model_artifact_metadata

    metadata = build_model_artifact_metadata(promoted, report, schema_version=_SCHEMA_VERSION)
    artifact = {
        **metadata,
        "model": model,
        "calibrator": calibrator,
        "team_state": team_state,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "runtime_notes": {
            "lineup_training_source": "pregame team offensive state proxy",
            "bullpen_training_source": "pregame team run-prevention/workload proxy",
            "daily_runtime_source": "MLB Stats API general top-PA lineups when feature file exists",
        },
    }
    if report.get("offset_ablations"):
        artifact["offset_diagnostics"] = report["offset_ablations"]
    if promoted.get("offset_config"):
        artifact["offset_config"] = promoted["offset_config"]
        artifact["promotion_gates"].update(promoted.get("offset_gates") or {})
        artifact["validated"] = all(bool(value) for value in artifact["promotion_gates"].values())
    return artifact


def select_offset_candidate(report: dict) -> dict | None:
    starter = [
        item for item in report.get("ablations", [])
        if item.get("feature_set") == "starter_only" and item.get("model") == "logistic"
    ]
    offsets = [
        item for item in report.get("offset_ablations", [])
        if item.get("feature_set") == "offset_starter_run"
    ]
    if not starter or not offsets:
        return None
    starter_metrics = starter[0]["mean_metrics"]
    candidate = offsets[0]
    metrics = candidate["mean_metrics"]
    paired = candidate.get("paired_metrics") or {}
    beta_rate = (candidate.get("beta_positive_fold_rate") or {}).get("starter_run_value_diff", 0.0)
    gates = {
        "offset_beats_starter_brier": float(metrics["brier_score"]) < float(starter_metrics["brier_score"]),
        "offset_beats_starter_log_loss": float(metrics["log_loss"]) < float(starter_metrics["log_loss"]),
        "offset_beta_positive_stable": float(beta_rate) >= 0.60,
        "offset_improves_most_folds": float(paired.get("fold_improvement_rate") or 0.0) >= 0.50,
    }
    if not all(gates.values()):
        candidate["offset_gates"] = gates
        return None
    return {
        **candidate,
        "feature_set": "starter_run_offset",
        "model": "starter_only_logit_offset",
        "features": list(starter[0]["features"]),
        "offset_config": {
            "model_id": "mlb_starter_offset_v23",
            "base_model": "starter_only_logistic",
            "feature": "starter_run_value_diff",
            "beta": float((candidate.get("mean_beta") or {}).get("starter_run_value_diff") or 0.0),
            "cap": _STARTER_RUN_DIFF_CAP,
        },
        "offset_gates": gates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build MLB v2.3 player-aware artifact.")
    parser.add_argument("--start", default=_DEFAULT_START)
    parser.add_argument("--end", default=_DEFAULT_END)
    parser.add_argument("--output", default=str(_OUTPUT_PATH))
    parser.add_argument("--input", help="Optional JSON game file")
    parser.add_argument(
        "--games-cache",
        default=None,
        help="Optional JSON cache for fetched historical games",
    )
    parser.add_argument(
        "--starter-snapshots",
        default=None,
        help="Optional historical as-of starter snapshot JSON from scripts/build_mlb_starter_snapshots.py",
    )
    parser.add_argument(
        "--models",
        default="logistic",
        help="Comma-separated model candidates (default: logistic)",
    )
    parser.add_argument(
        "--step-size",
        type=int,
        default=60,
        help="Walk-forward test step size in games (default: 60)",
    )
    parser.add_argument(
        "--promote-feature-set",
        choices=[
            "starter_only",
            "run_components",
            "run_aggregate",
            "starter_lineup",
            "starter_lineup_bullpen",
            "full_player_aware",
        ],
        default=None,
        help="Explicitly train/promote this player feature set; requires --force if gates fail",
    )
    parser.add_argument("--force", action="store_true", help="Save even if gates fail")
    args = parser.parse_args()

    if args.input:
        print(f"[1/6] Loading games from {args.input}...")
        games = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        print(f"[1/6] Fetching games {args.start} to {args.end}...")
        cache_path = Path(args.games_cache) if args.games_cache else (
            ROOT / "data" / ".mlb_cache" / f"historical_games_{args.start}_{args.end}.json"
        )
        games = fetch_historical_games(args.start, args.end, cache_path=cache_path)
    print(f"       {len(games)} games loaded.")
    if len(games) < 300:
        print("ERROR: not enough historical games for training.")
        sys.exit(1)

    starter_snapshots = load_starter_snapshots(Path(args.starter_snapshots)) if args.starter_snapshots else {}
    if starter_snapshots:
        print(f"       {len(starter_snapshots)} starter snapshot games loaded.")

    print("[2/6] Building v2.3 training rows...")
    rows, team_state = build_training_rows(games, starter_snapshots=starter_snapshots)
    print(f"       {len(rows)} rows built.")
    if starter_snapshots:
        coverage = team_state.get("_starter_snapshot_coverage", {})
        print(
            "       starter snapshots used for "
            f"{coverage.get('games_with_both_starter_snapshots', 0)} rows; "
            f"missing any side for {coverage.get('games_missing_any_starter_snapshot', 0)} rows."
        )

    print("[3/6] Running walk-forward ablations...")
    model_names = [name.strip() for name in args.models.split(",") if name.strip()]
    report = run_ablation(rows, model_names=model_names, step_size=args.step_size)
    for ablation in report["ablations"]:
        metrics = ablation["mean_metrics"]
        print(
            f"       {ablation['feature_set']:30s} {ablation['model']:25s} "
            f"brier={metrics['brier_score']:.4f} acc={metrics['accuracy']:.3f}"
        )
    offset_ablations = run_offset_ablations(rows, step_size=args.step_size)
    report["offset_ablations"] = offset_ablations
    for ablation in offset_ablations:
        metrics = ablation["mean_metrics"]
        paired = ablation.get("paired_metrics") or {}
        beta_text = ", ".join(f"{key}={value:.3f}" for key, value in ablation.get("mean_beta", {}).items())
        print(
            f"       {ablation['feature_set']:30s} {ablation['model']:25s} "
            f"brier={metrics['brier_score']:.4f} acc={metrics['accuracy']:.3f} "
            f"delta_brier={paired.get('mean_delta_brier', 0.0):+.5f} "
            f"folds+={paired.get('folds_improved', 0)}/{len(ablation.get('folds', []))} "
            f"beta[{beta_text}]"
        )

    print("[4/6] Selecting promoted result...")
    from alpha.engines.sports.mlb_player_modeling import select_promoted_result

    promoted = select_promoted_result(report)
    offset_promoted = select_offset_candidate(report)
    if offset_promoted is not None:
        promoted = offset_promoted
    natural_promoted = promoted
    if args.promote_feature_set:
        candidates = [
            ablation
            for ablation in report["ablations"]
            if ablation.get("feature_set") == args.promote_feature_set
        ]
        if not candidates:
            print(f"  ERROR: no candidate found for {args.promote_feature_set}")
            sys.exit(1)
        promoted = min(candidates, key=lambda a: float(a["mean_metrics"]["brier_score"]))
        print(
            f"  Requested feature set: {args.promote_feature_set} / {promoted['model']} "
            f"brier={promoted['mean_metrics']['brier_score']:.4f}"
        )
        if natural_promoted is not None and natural_promoted.get("feature_set") != args.promote_feature_set and not args.force:
            print(
                "  Refusing explicit promotion because another feature set passed gates. "
                "Use --force to override."
            )
            sys.exit(2)
    elif promoted is None:
        print("  WARNING: no v2.3 candidate improved baseline Brier.")
        candidates = [a for a in report["ablations"] if a.get("feature_set") != "baseline_v1_3"]
        promoted = min(candidates, key=lambda a: float(a["mean_metrics"]["brier_score"]))
        if not args.force:
            print("  Refusing to overwrite promoted artifact without --force.")
            sys.exit(2)
    print(f"  Promoted: {promoted['feature_set']} / {promoted['model']}")
    if promoted.get("offset_config"):
        print(
            "  Offset config: "
            f"{promoted['offset_config']['feature']} beta={promoted['offset_config']['beta']:.4f} "
            f"cap={promoted['offset_config']['cap']:.2f}"
        )

    print("[5/6] Training final model...")
    feature_names = tuple(promoted["features"])
    model, calibrator = train_final_model(rows, feature_names, promoted["model"])

    print("[6/6] Packaging artifact...")
    artifact = package_artifact(promoted, report, model, calibrator, team_state)
    if args.force and not artifact["validated"]:
        artifact["validated"] = True
        artifact["promotion_gates"] = {key: True for key in artifact["promotion_gates"]}
    if args.promote_feature_set and args.force:
        artifact["promotion_override"] = {
            "forced": True,
            "requested_feature_set": args.promote_feature_set,
            "natural_feature_set": natural_promoted.get("feature_set") if natural_promoted else None,
            "reason": "User requested a full batter/bullpen-trained artifact.",
        }
        artifact["validated"] = True
        artifact["promotion_gates"] = {key: True for key in artifact["promotion_gates"]}

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    import joblib  # noqa: PLC0415

    joblib.dump(artifact, str(output_path))
    meta = {key: value for key, value in artifact.items() if key not in ("model", "calibrator", "team_state")}
    output_path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

    metrics = promoted["mean_metrics"]
    print(f"\nArtifact saved to: {output_path}")
    print(f"  schema_version  : {artifact['schema_version']}")
    print(f"  validated       : {artifact['validated']}")
    print(f"  feature_set     : {promoted['feature_set']}")
    print(f"  model           : {promoted['model']}")
    print(f"  features        : {len(feature_names)}")
    print(f"  metrics         : brier={metrics['brier_score']:.4f} acc={metrics['accuracy']:.3f} n={metrics['n']}")


if __name__ == "__main__":
    main()
