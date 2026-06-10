"""
Train XGBoost prop models on historical game logs.

Reads:  data/historical_logs.csv  (from fetch_historical_logs.py)
Writes: data/xgb_pts_model.pkl   + data/xgb_pts_model.meta.json
        data/xgb_reb_model.pkl   + ...
        data/xgb_ast_model.pkl
        data/xgb_fg3m_model.pkl  (player_threes support — market stays
                                  disabled by default at ingestion)

Correctness guarantees:
  - Features come from the SHARED builder (alpha.engines.sports.
    prop_features) — the exact code used at live inference.
  - Target rows are NOT filtered by the target game's minutes (that was
    selection bias); only HISTORY games need the 20-minute floor.
  - is_home comes from the historical matchup string ("vs." = home).
  - rest_days/back_to_back use actual game dates.
  - Opponent def-rtg/pace have no leak-free historical source here, so they
    are NaN in training (XGBoost-native missing) — never fake constants.
  - Chronological 70/15/15 train/val/test split; early stopping on val.
  - A model is saved ONLY if it beats the naive baselines (season average,
    rolling per-min projection) on the held-out test period.

Usage:
    python scripts/train_xgb_prop_model.py [--ablation]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpha.engines.sports.prop_features import (
    ALL_FEATURES,
    FEATURE_SCHEMA_VERSION,
    build_pregame_features,
    features_to_vector,
    normalize_history_row,
)
from alpha.engines.sports.xgb_prop_model import MODEL_VERSION, XGBoostPropModel

LOG_FILE = Path("data/historical_logs.csv")

_STAT_COLS = {
    "pts":  ("pts",  "data/xgb_pts_model.pkl"),
    "reb":  ("reb",  "data/xgb_reb_model.pkl"),
    "ast":  ("ast",  "data/xgb_ast_model.pkl"),
    "fg3m": ("fg3m", "data/xgb_fg3m_model.pkl"),
}

TRAIN_FRAC, VAL_FRAC = 0.70, 0.15  # remainder = test


def build_dataset(df: pd.DataFrame, stat_col: str) -> pd.DataFrame:
    """
    Build one row per (player-season, game) using only prior games.

    The target game is included regardless of its own minutes — filtering
    on target-game minutes leaks postgame information and biases the
    training distribution toward games the player ended up playing a lot.
    """
    samples: list[dict] = []
    groups = df.groupby(["player_id", "season"])
    total = len(groups)
    for i, ((player_id, season), group) in enumerate(groups):
        if i % 200 == 0:
            print(f"\r  Building features: {i}/{total} player-seasons", end="", flush=True)
        group = group.sort_values("game_date").reset_index(drop=True)
        rows = group.to_dict("records")
        history_norm: list[dict] = []  # oldest-first accumulator
        prior_raw_stats: list[float] = []
        for rec in rows:
            game_date = pd.Timestamp(rec["game_date"]).date()
            matchup = str(rec.get("matchup", ""))
            is_home = "vs." in matchup

            result = build_pregame_features(
                history=list(reversed(history_norm)),  # newest-first
                market=_market_for(stat_col),
                game_date=game_date,
                is_home=is_home,
            )
            if result is not None:
                samples.append({
                    **result.features,
                    "_target": float(rec[stat_col]),
                    "_game_date": game_date,
                    "_season_avg_baseline": float(np.mean(prior_raw_stats)),
                })

            norm = normalize_history_row(rec, stat_col)
            if norm is not None:
                history_norm.append(norm)
                prior_raw_stats.append(float(rec[stat_col]))

    print(f"\r  {len(samples)} training samples built from {total} player-seasons")
    return pd.DataFrame(samples)


def _market_for(stat_col: str) -> str:
    return {
        "pts": "player_points", "reb": "player_rebounds",
        "ast": "player_assists", "fg3m": "player_threes",
    }[stat_col]


def _mae(pred: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean(np.abs(pred - y)))


def _rmse(pred: np.ndarray, y: np.ndarray) -> float:
    return float(np.sqrt(np.mean((pred - y) ** 2)))


def _permutation_importance(model: XGBoostPropModel, feats: list[dict],
                            y: np.ndarray, base_mae: float) -> dict[str, float]:
    """MAE increase when each feature column is shuffled on the val set."""
    rng = np.random.default_rng(42)
    X = np.array([features_to_vector(f, model.feature_names) for f in feats])
    out: dict[str, float] = {}
    for j, name in enumerate(model.feature_names):
        Xp = X.copy()
        rng.shuffle(Xp[:, j])
        pred = model._model.predict(Xp)
        out[name] = round(_mae(pred, y) - base_mae, 4)
    return out


def train_model(stat_name: str, stat_col: str, out_path: str, ablation: bool = False) -> None:
    print(f"\nTraining {stat_name.upper()} model...")
    df = pd.read_csv(LOG_FILE, encoding="utf-8")
    df["game_date"] = pd.to_datetime(df["game_date"])

    data = build_dataset(df, stat_col)
    if len(data) < 100:
        print(f"  Not enough samples ({len(data)}) — skipping {stat_name}")
        return

    # Chronological split: never train on future games.
    data = data.sort_values("_game_date").reset_index(drop=True)
    n = len(data)
    i_train, i_val = int(n * TRAIN_FRAC), int(n * (TRAIN_FRAC + VAL_FRAC))
    splits = {
        "train": data.iloc[:i_train],
        "val":   data.iloc[i_train:i_val],
        "test":  data.iloc[i_val:],
    }
    print(f"  Split: train={len(splits['train'])} val={len(splits['val'])} "
          f"test={len(splits['test'])} "
          f"(train ends {splits['train']['_game_date'].max()}, "
          f"test starts {splits['test']['_game_date'].min()})")

    def _feats(frame: pd.DataFrame) -> list[dict]:
        return frame[ALL_FEATURES].to_dict("records")

    model = XGBoostPropModel(target=stat_name)
    model.fit(
        _feats(splits["train"]), splits["train"]["_target"].tolist(),
        val_features=_feats(splits["val"]), val_targets=splits["val"]["_target"].tolist(),
    )

    # Held-out test metrics + naive baselines.
    y_test = splits["test"]["_target"].to_numpy()
    X_test = np.array([features_to_vector(f, model.feature_names) for f in _feats(splits["test"])])
    pred_test = model._model.predict(X_test)
    test_mae, test_rmse = _mae(pred_test, y_test), _rmse(pred_test, y_test)

    baseline_season = splits["test"]["_season_avg_baseline"].to_numpy()
    baseline_roll = (
        splits["test"]["roll10_stat_per_min"] * splits["test"]["projected_minutes"]
    ).to_numpy()
    baselines = {
        "season_avg_mae": _mae(baseline_season, y_test),
        "rolling_proj_mae": _mae(baseline_roll, y_test),
    }
    print(f"  Test MAE: model={test_mae:.3f} | season_avg={baselines['season_avg_mae']:.3f} "
          f"| rolling_proj={baselines['rolling_proj_mae']:.3f}")

    accepted = test_mae < min(baselines.values())
    if not accepted:
        print(f"  REJECTED: model does not beat naive baselines on held-out period. "
              f"Not saving {out_path}.")
        return

    val_feats = _feats(splits["val"])
    y_val = splits["val"]["_target"].to_numpy()
    perm = _permutation_importance(
        model, val_feats, y_val, model.validation_metrics["val_mae"],
    )

    meta = {
        **model.metadata(),
        "model_version": MODEL_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "trained_on": str(date.today()),
        "validation_period": {
            "val_start": str(splits["val"]["_game_date"].min()),
            "val_end": str(splits["val"]["_game_date"].max()),
            "test_start": str(splits["test"]["_game_date"].min()),
            "test_end": str(splits["test"]["_game_date"].max()),
        },
        "test_metrics": {"mae": test_mae, "rmse": test_rmse, "samples": int(len(y_test))},
        "baselines": baselines,
        "accepted_vs_baselines": accepted,
        "sample_count": int(n),
        "feature_importance": {k: round(float(v), 4) for k, v in model.feature_importance().items()},
        "permutation_importance_val": perm,
    }

    if ablation:
        meta["ablation_val_mae"] = _ablation_report(splits)

    model.save(Path(out_path))
    Path(out_path).with_suffix(".meta.json").write_text(
        json.dumps(meta, indent=2, default=str), encoding="utf-8",
    )
    top = sorted(model.feature_importance().items(), key=lambda x: -x[1])[:4]
    print("  Top features: " + ", ".join(f"{k}={v:.3f}" for k, v in top))
    print(f"  Saved -> {out_path} (+ .meta.json)")


def _ablation_report(splits: dict[str, pd.DataFrame]) -> dict[str, float]:
    """Drop-one-feature retrains: val MAE per ablated feature."""
    report: dict[str, float] = {}
    for dropped in ALL_FEATURES:
        kept = [f for f in ALL_FEATURES if f != dropped]
        m = XGBoostPropModel(target="ablation")
        m.feature_names = kept
        m.fit(
            splits["train"][kept].to_dict("records"), splits["train"]["_target"].tolist(),
            val_features=splits["val"][kept].to_dict("records"),
            val_targets=splits["val"]["_target"].tolist(),
        )
        report[dropped] = round(m.validation_metrics["val_mae"], 4)
        print(f"    ablate {dropped}: val MAE {report[dropped]}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ablation", action="store_true",
                        help="run drop-one-feature ablation (slow)")
    args = parser.parse_args()

    if not LOG_FILE.exists():
        print(f"ERROR: {LOG_FILE} not found.")
        print("Run fetch_historical_logs.py first.")
        raise SystemExit(1)

    rows = sum(1 for _ in open(LOG_FILE, encoding="utf-8")) - 1  # subtract header
    print(f"Loaded {rows:,} game log rows from {LOG_FILE}")

    for stat_name, (stat_col, out_path) in _STAT_COLS.items():
        train_model(stat_name, stat_col, out_path, ablation=args.ablation)

    print("\nDone. Models that beat baselines were saved with .meta.json sidecars.")
