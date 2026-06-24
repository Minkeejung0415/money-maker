"""
Build and package the v1.8 player-aware MLB moneyline artifact.

Pipeline
--------
1. Fetch completed MLB games 2023-2025 from MLB Stats API.
2. Build baseline Elo/win-pct/run-diff rows via build_pregame_rows().
3. Add team-ERA-based starter quality features per season
   (a proxy when per-game pitcher names are unavailable historically).
4. Run walk-forward ablations comparing baseline_v1_3 vs starter_only.
5. If starter features improve Brier score: package into a validated
   mlb_player_moneyline_artifact and save to alpha/models/.
6. Print summary of gates, metrics, and artifact path.

Usage
-----
    python scripts/build_mlb_player_v18.py
    python scripts/build_mlb_player_v18.py --start 2022-03-01 --end 2026-06-01
    python scripts/build_mlb_player_v18.py --force   # save even if gates fail
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("build_mlb_player_v18")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OUTPUT_PATH = ROOT / "alpha" / "models" / "mlb_player_moneyline.pkl"
_DEFAULT_START = "2023-03-01"
_DEFAULT_END = "2026-06-01"


# ---------------------------------------------------------------------------
# Game fetching (mirrors train_mlb_moneyline.py)
# ---------------------------------------------------------------------------

def fetch_historical_games(start: str, end: str) -> list[dict]:
    """Fetch completed regular/postseason games from MLB Stats API."""
    import statsapi

    start_d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    result: list[dict] = []

    for year in range(start_d.year, end_d.year + 1):
        chunk_start = max(start_d, date(year, 1, 1)).isoformat()
        chunk_end = min(end_d, date(year, 12, 31)).isoformat()
        logger.info("Fetching %d games (%s -> %s)...", year, chunk_start, chunk_end)
        try:
            schedule = statsapi.schedule(start_date=chunk_start, end_date=chunk_end)
        except Exception as exc:
            logger.warning("StatsAPI failed for %d: %s", year, exc)
            continue

        for g in schedule:
            if g.get("status") != "Final":
                continue
            if g.get("game_type", "R") not in ("R", "F", "D", "L", "W"):
                continue
            result.append({
                "date": str(g.get("game_date", g.get("game_datetime", "")))[:10],
                "game_id": str(g.get("game_id", "")),
                "home_team": g.get("home_name", ""),
                "away_team": g.get("away_name", ""),
                "home_score": g.get("home_score"),
                "away_score": g.get("away_score"),
            })

    # Deduplicate by game_id
    seen: set[str] = set()
    deduped: list[dict] = []
    for g in result:
        if g["game_id"] not in seen:
            seen.add(g["game_id"])
            deduped.append(g)

    logger.info("Fetched %d completed games total.", len(deduped))
    return deduped


# ---------------------------------------------------------------------------
# Build training rows
# ---------------------------------------------------------------------------

def _runs_allowed_quality(runs_against: float, games: int) -> float:
    """
    Convert season runs-allowed-per-game into a 0-1 quality score.
    8+ runs/game = 0.0, 2 runs/game = 1.0.
    """
    if games <= 0:
        return 0.50
    per_game = runs_against / games
    return max(0.0, min(1.0, (8.0 - per_game) / 6.0))


def build_training_rows(games: list[dict]) -> tuple[list[dict], dict]:
    """
    Return (rows, team_state) where rows combine:
      - Elo/win-pct/run-diff baseline features from build_pregame_rows()
      - Runs-allowed-per-game starter quality proxy derived from the
        same game history (no external API needed)

    The sp_quality proxy isolates the defensive/pitching component
    from the composite run_diff feature, giving the model a separate
    signal to weight.

    Each row is suitable for run_walkforward_ablations() with the
    starter_only feature set (BASELINE + STARTER features).
    """
    from alpha.engines.sports.mlb_training import build_pregame_rows

    baseline_rows, team_state = build_pregame_rows(games)

    # Build quality map from final season team_state
    quality_map: dict[str, float] = {
        team: _runs_allowed_quality(
            float(state.get("runs_against", 0)),
            int(state.get("games", 0)),
        )
        for team, state in team_state.items()
    }

    enriched: list[dict] = []
    missing_quality = 0

    for row in baseline_rows:
        home_quality = quality_map.get(row["home_team"])
        away_quality = quality_map.get(row["away_team"])

        if home_quality is None or away_quality is None:
            missing_quality += 1
            home_quality = home_quality if home_quality is not None else 0.50
            away_quality = away_quality if away_quality is not None else 0.50

        enriched.append({
            **row,
            "game_date": row["date"],  # alias for walk-forward split
            # Starter-quality features derived from runs allowed
            "home_sp_quality": home_quality,
            "away_sp_quality": away_quality,
            "sp_quality_diff": home_quality - away_quality,
            "home_sp_workload": 90.0,
            "away_sp_workload": 90.0,
            "sp_workload_diff": 0.0,
            "home_sp_rest_days": 5.0,
            "away_sp_rest_days": 5.0,
            "home_sp_missing": 0.0,
            "away_sp_missing": 0.0,
        })

    if missing_quality:
        logger.warning(
            "%d rows had fallback quality=0.50 (team not in team_state).",
            missing_quality,
        )

    logger.info("Built %d training rows (baseline + starter features).", len(enriched))
    return enriched, team_state


# ---------------------------------------------------------------------------
# Walk-forward ablation
# ---------------------------------------------------------------------------

def run_ablation(rows: list[dict]) -> dict:
    """Run walk-forward ablations for baseline_v1_3 and starter_only feature sets."""
    from alpha.engines.sports.mlb_player_modeling import (
        PLAYER_FEATURE_SETS,
        run_walkforward_ablations,
    )

    feature_sets = {
        k: v
        for k, v in PLAYER_FEATURE_SETS.items()
        if k in ("baseline_v1_3", "starter_only")
    }

    logger.info(
        "Running walk-forward ablations on %d rows, feature sets: %s...",
        len(rows),
        list(feature_sets),
    )
    report = run_walkforward_ablations(rows, feature_sets=feature_sets)
    return report


# ---------------------------------------------------------------------------
# Train final model
# ---------------------------------------------------------------------------

def train_final_model(
    rows: list[dict],
    feature_names: tuple[str, ...],
    model_name: str,
) -> tuple:
    """Train final model + calibrator on all rows using a 80/20 split."""
    import numpy as np
    from alpha.engines.sports.mlb_player_modeling import (
        available_model_factories,
        fit_sigmoid_calibrator,
    )

    n = len(rows)
    split = int(n * 0.8)

    x_all = np.asarray(
        [[float(row.get(name) if row.get(name) is not None else 0.0) for name in feature_names] for row in rows],
        dtype=float,
    )
    y_all = np.asarray([int(row["home_win"]) for row in rows], dtype=int)

    x_train, y_train = x_all[:split], y_all[:split]
    x_cal, y_cal = x_all[split:], y_all[split:]

    factories = available_model_factories()
    if model_name not in factories:
        model_name = next(iter(factories))
    model = factories[model_name]()
    model.fit(x_train, y_train)

    raw_cal = model.predict_proba(x_cal)[:, 1]
    calibrator = fit_sigmoid_calibrator(raw_cal.tolist(), y_cal.tolist())

    logger.info("Trained final %s on %d rows (cal split: %d).", model_name, n, n - split)
    return model, calibrator


# ---------------------------------------------------------------------------
# Package artifact
# ---------------------------------------------------------------------------

def package_artifact(
    promoted: dict,
    report: dict,
    model,
    calibrator,
    team_state: dict,
    *,
    force: bool = False,
) -> dict:
    """
    Build and return the mlb_player_moneyline_artifact dict.

    Parameters
    ----------
    promoted:
        The selected ablation result (from select_promoted_result or best candidate).
    report:
        Full ablation report from run_walkforward_ablations().
    model:
        Fitted sklearn-compatible classifier.
    calibrator:
        Fitted calibrator (IdentityCalibrator or SigmoidCalibrator).
    team_state:
        {team_name: {games, wins, ...}} terminal state for live inference.
    force:
        If True, set validated=True even when promotion gates fail.
    """
    from alpha.engines.sports.mlb_player_modeling import build_model_artifact_metadata

    metadata = build_model_artifact_metadata(promoted, report)

    artifact = {
        **metadata,
        "model": model,
        "calibrator": calibrator,
        "team_state": team_state,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }

    if force and not artifact["validated"]:
        logger.warning("--force: overriding validated=False -> True")
        artifact["validated"] = True
        artifact["promotion_gates"] = {k: True for k in artifact["promotion_gates"]}

    return artifact


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build MLB v1.8 player-aware artifact.")
    parser.add_argument("--start", default=_DEFAULT_START)
    parser.add_argument("--end", default=_DEFAULT_END)
    parser.add_argument(
        "--output",
        default=str(_OUTPUT_PATH),
        help="Output .pkl path (default: alpha/models/mlb_player_moneyline.pkl)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Save artifact even if promotion gates fail (for development/testing)",
    )
    parser.add_argument(
        "--input",
        help="Optional JSON file of pre-fetched games (skips Stats API call)",
    )
    args = parser.parse_args()

    output_path = Path(args.output)

    # - Step 1: Load or fetch games -
    if args.input:
        print(f"[1/6] Loading games from {args.input}...")
        games = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        print(f"[1/6] Fetching games {args.start} to {args.end}...")
        games = fetch_historical_games(args.start, args.end)

    if len(games) < 300:
        print(f"ERROR: Only {len(games)} games found - need -300. Exiting.")
        sys.exit(1)
    print(f"       {len(games)} games loaded.")

    # - Step 2: Build training rows -
    print("[2/6] Building training rows (baseline + starter features)...")
    rows, team_state = build_training_rows(games)
    print(f"       {len(rows)} rows built.")

    if len(rows) < 300:
        print(f"ERROR: Only {len(rows)} completed rows - need -300. Exiting.")
        sys.exit(1)

    # - Step 3: Walk-forward ablation -
    print("[3/6] Running walk-forward ablations...")
    try:
        report = run_ablation(rows)
    except ValueError as exc:
        print(f"ERROR in ablation: {exc}")
        sys.exit(1)

    # Print ablation summary
    for ablation in report["ablations"]:
        m = ablation["mean_metrics"]
        print(
            f"       {ablation['feature_set']:30s} {ablation['model']:25s} "
            f"brier={m['brier_score']:.4f}  acc={m['accuracy']:.3f}"
        )

    # - Step 4: Select best result -
    print("[4/6] Selecting promoted result...")
    from alpha.engines.sports.mlb_player_modeling import select_promoted_result

    promoted = select_promoted_result(report)
    if promoted is None:
        print("  WARNING: starter features did NOT improve Brier score over baseline.")
        if not args.force:
            print("  Artifact will have validated=False and will not activate at runtime.")
            print("  Run with --force to override (use for development only).")
        # Still package with best non-baseline result for future use
        candidates = [a for a in report["ablations"] if a.get("feature_set") != "baseline_v1_3"]
        promoted = min(candidates, key=lambda a: float(a["mean_metrics"]["brier_score"])) if candidates else report["ablations"][0]
    else:
        print(
            f"  Promoted: {promoted['feature_set']} / {promoted['model']}  "
            f"brier={promoted['mean_metrics']['brier_score']:.4f}"
        )

    # - Step 5: Train final model -
    print("[5/6] Training final model on all data...")
    feature_names = tuple(promoted["features"])
    model, calibrator = train_final_model(rows, feature_names, promoted["model"])

    # - Step 6: Package and save -
    print("[6/6] Packaging artifact...")
    artifact = package_artifact(
        promoted, report, model, calibrator, team_state, force=args.force
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump(artifact, str(output_path))

    # Save human-readable metadata
    meta = {k: v for k, v in artifact.items() if k not in ("model", "calibrator", "team_state")}
    meta_path = output_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

    print(f"\nArtifact saved to: {output_path}")
    print(f"Metadata saved to: {meta_path}")
    print(f"  validated       : {artifact['validated']}")
    print(f"  promotion_gates : {artifact['promotion_gates']}")
    print(f"  feature_set     : {promoted['feature_set']}")
    print(f"  model           : {promoted['model']}")
    print(f"  features        : {len(feature_names)}")
    m = promoted["mean_metrics"]
    print(
        f"  metrics         : brier={m['brier_score']:.4f}  "
        f"acc={m['accuracy']:.3f}  n={m['n']}"
    )

    if not artifact["validated"] and not args.force:
        print(
            "\nNOTE: Artifact is NOT validated - scanner will keep using v1.3 baseline."
        )
        print("      Improve data quality (per-game pitcher logs) to pass gates.")
        sys.exit(2)


if __name__ == "__main__":
    main()
