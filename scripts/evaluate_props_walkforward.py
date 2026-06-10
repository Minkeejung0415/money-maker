"""
Walk-forward evaluation for NBA player-prop models.  PAPER ONLY.

Two modes:

1. Projection walk-forward (default; needs data/historical_logs.csv):
   expanding-window time splits — each fold trains an XGBoost model on
   strictly earlier games and scores MAE/RMSE on the next window,
   against the naive baselines (season average, rolling projection).
   Calibration/validation rows are carved from the END of each training
   window (still earlier than the test window) so calibration data never
   mixes with model-training data.

2. Paper-bet report (--paper-log data/paper_bets/paper_bets.jsonl):
   probability metrics (Brier, log loss, reliability table) and betting
   metrics (ROI, CLV, drawdown, streaks) of SETTLED paper bets, grouped
   by market / player / bookmaker / confidence / odds / month / model.

Usage:
    python scripts/evaluate_props_walkforward.py [--stat pts] [--folds 5]
    python scripts/evaluate_props_walkforward.py --paper-log data/paper_bets/paper_bets.jsonl
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpha.engines.sports.evaluation import (
    betting_metrics,
    grouped_betting_report,
    probability_metrics,
    projection_metrics,
    walkforward_splits,
)

LOG_FILE = Path("data/historical_logs.csv")
REPORT_DIR = Path("reports")

PROP_MARKETS = {"player_points", "player_rebounds", "player_assists", "player_threes"}


def _load_trainer():
    spec = importlib.util.spec_from_file_location(
        "train_xgb_prop_model", Path(__file__).with_name("train_xgb_prop_model.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["train_xgb_prop_model"] = mod
    spec.loader.exec_module(mod)
    return mod


def run_projection_walkforward(stat: str, n_folds: int) -> dict:
    import pandas as pd

    from alpha.engines.sports.prop_features import ALL_FEATURES
    from alpha.engines.sports.xgb_prop_model import XGBoostPropModel

    trainer = _load_trainer()
    df = pd.read_csv(LOG_FILE, encoding="utf-8")
    df["game_date"] = pd.to_datetime(df["game_date"])
    data = trainer.build_dataset(df, stat).sort_values("_game_date").reset_index(drop=True)
    print(f"{len(data)} samples for {stat}")

    folds_out = []
    splits = walkforward_splits(data["_game_date"].tolist(), n_folds=n_folds)
    for i, (train_idx, test_idx) in enumerate(splits):
        train = data.iloc[train_idx]
        test = data.iloc[test_idx]
        # Validation (early stopping / calibration) = last 15% of the train
        # window — chronologically after training rows, before test rows.
        cut = int(len(train) * 0.85)
        tr, val = train.iloc[:cut], train.iloc[cut:]

        model = XGBoostPropModel(target=stat)
        model.fit(
            tr[ALL_FEATURES].to_dict("records"), tr["_target"].tolist(),
            val_features=val[ALL_FEATURES].to_dict("records"),
            val_targets=val["_target"].tolist(),
        )
        import numpy as np

        from alpha.engines.sports.prop_features import features_to_vector
        X = np.array([features_to_vector(f, model.feature_names)
                      for f in test[ALL_FEATURES].to_dict("records")])
        pred = model._model.predict(X)
        y = test["_target"].to_numpy()

        fold = {
            "fold": i,
            "test_start": str(test["_game_date"].min()),
            "test_end": str(test["_game_date"].max()),
            "model": projection_metrics(y.tolist(), pred.tolist()),
            "baseline_season_avg": projection_metrics(
                y.tolist(), test["_season_avg_baseline"].tolist()),
            "baseline_rolling": projection_metrics(
                y.tolist(),
                (test["roll10_stat_per_min"] * test["projected_minutes"]).tolist()),
        }
        folds_out.append(fold)
        print(f"  fold {i}: model MAE={fold['model']['mae']:.3f} "
              f"season={fold['baseline_season_avg']['mae']:.3f} "
              f"rolling={fold['baseline_rolling']['mae']:.3f}")

    return {"stat": stat, "folds": folds_out}


def run_paper_report(paper_log: Path) -> dict:
    from alpha.engines.sports.paper_betting_logger import PaperBettingLogger

    logger = PaperBettingLogger(paper_log)
    bets = [b for b in logger.settled() if b.get("market") in PROP_MARKETS]
    if not bets:
        print("No settled prop paper bets found.")
        return {"num_bets": 0}

    decided = [b for b in bets if b["result"] in ("win", "loss")]
    report: dict = {"overall": betting_metrics(bets)}
    if decided:
        outcomes = [1 if b["result"] == "win" else 0 for b in decided]
        probs = [float(b["final_calibrated_prob"]) for b in decided]
        report["probability"] = probability_metrics(outcomes, probs)
    report["grouped"] = grouped_betting_report(bets)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stat", default="pts", choices=["pts", "reb", "ast", "fg3m"])
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--paper-log", type=Path, default=None)
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    if args.paper_log is not None:
        report = run_paper_report(args.paper_log)
        out = REPORT_DIR / "props_paper_report.json"
    else:
        if not LOG_FILE.exists():
            print(f"ERROR: {LOG_FILE} not found. Run fetch_historical_logs.py first.")
            raise SystemExit(1)
        report = run_projection_walkforward(args.stat, args.folds)
        out = REPORT_DIR / f"props_walkforward_{args.stat}.json"

    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Report written to {out}")
