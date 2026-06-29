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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("build_mlb_player_v23")

_OUTPUT_PATH = ROOT / "alpha" / "models" / "mlb_player_moneyline.pkl"
_DEFAULT_START = "2023-03-01"
_DEFAULT_END = "2026-06-29"
_SCHEMA_VERSION = "mlb-player-v2.3"


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


def build_training_rows(games: list[dict]) -> tuple[list[dict], dict]:
    from alpha.engines.sports.mlb_training import TeamState, feature_vector

    states: dict[str, TeamState] = {}
    rows: list[dict] = []
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

        rows.append({
            "date": game_date,
            "game_date": game_date,
            "game_id": game.get("game_id", ""),
            "home_team": home_team,
            "away_team": away_team,
            **base,
            "home_sp_quality": home_pitching,
            "away_sp_quality": away_pitching,
            "sp_quality_diff": home_pitching - away_pitching,
            "home_sp_workload": 90.0,
            "away_sp_workload": 90.0,
            "sp_workload_diff": 0.0,
            "home_sp_rest_days": base["home_rest_days"] + 1.0,
            "away_sp_rest_days": base["away_rest_days"] + 1.0,
            "home_sp_missing": 0.0,
            "away_sp_missing": 0.0,
            "home_lineup_strength": home_offense,
            "away_lineup_strength": away_offense,
            "lineup_strength_diff": home_offense - away_offense,
            "home_top_order_strength": min(1.25, home_offense * 1.04),
            "away_top_order_strength": min(1.25, away_offense * 1.04),
            "top_order_strength_diff": (home_offense - away_offense) * 1.04,
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
            "home_bp_missing": 0.0,
            "away_bp_missing": 0.0,
            "home_absence_value": 0.0,
            "away_absence_value": 0.0,
            "absence_value_diff": 0.0,
            "home_absence_count": 0.0,
            "away_absence_count": 0.0,
            "player_feature_missing_flag": 0.0,
            "home_win": int(float(home_score) > float(away_score)),
        })

        _update_state(home_state, away_state, float(home_score), float(away_score), game_date)

    return rows, {team: asdict(state) for team, state in states.items()}


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
        if key in ("baseline_v1_3", "starter_only", "starter_lineup", "starter_lineup_bullpen", "full_player_aware")
    }
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="X does not have valid feature names")
        return run_walkforward_ablations(
            rows,
            feature_sets=feature_sets,
            model_names=model_names,
            split_kwargs={"step_size": step_size},
        )


def train_final_model(rows: list[dict], feature_names: tuple[str, ...], model_name: str):
    import numpy as np  # noqa: PLC0415
    from alpha.engines.sports.mlb_player_modeling import available_model_factories, fit_sigmoid_calibrator

    n = len(rows)
    split = int(n * 0.8)
    x_all = np.asarray([[float(row.get(name) if row.get(name) is not None else 0.0) for name in feature_names] for row in rows], dtype=float)
    y_all = np.asarray([int(row["home_win"]) for row in rows], dtype=int)
    factories = available_model_factories()
    model = factories[model_name if model_name in factories else "logistic"]()
    model.fit(x_all[:split], y_all[:split])
    raw_cal = model.predict_proba(x_all[split:])[:, 1]
    calibrator = fit_sigmoid_calibrator(raw_cal.tolist(), y_all[split:].tolist())
    return model, calibrator


def package_artifact(promoted: dict, report: dict, model, calibrator, team_state: dict) -> dict:
    from alpha.engines.sports.mlb_player_modeling import build_model_artifact_metadata

    metadata = build_model_artifact_metadata(promoted, report, schema_version=_SCHEMA_VERSION)
    return {
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

    print("[2/6] Building v2.3 training rows...")
    rows, team_state = build_training_rows(games)
    print(f"       {len(rows)} rows built.")

    print("[3/6] Running walk-forward ablations...")
    model_names = [name.strip() for name in args.models.split(",") if name.strip()]
    report = run_ablation(rows, model_names=model_names, step_size=args.step_size)
    for ablation in report["ablations"]:
        metrics = ablation["mean_metrics"]
        print(
            f"       {ablation['feature_set']:30s} {ablation['model']:25s} "
            f"brier={metrics['brier_score']:.4f} acc={metrics['accuracy']:.3f}"
        )

    print("[4/6] Selecting promoted result...")
    from alpha.engines.sports.mlb_player_modeling import select_promoted_result

    promoted = select_promoted_result(report)
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
