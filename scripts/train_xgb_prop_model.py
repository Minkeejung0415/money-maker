"""
Train XGBoost prop models on historical game logs.

Reads:  data/historical_logs.csv  (from fetch_historical_logs.py)
Writes: data/xgb_pts_model.pkl
        data/xgb_reb_model.pkl
        data/xgb_ast_model.pkl

Each model is a regression model that predicts the raw stat value
(points / rebounds / assists) for a given game, using only information
available BEFORE that game (rolling averages from prior games).

PropModel uses these projections as the mu parameter for the NegBin/ZIP CDF
to compute P(over line) — replacing the hand-tuned weighted average.

Usage:
    ./venv/Scripts/python.exe scripts/train_xgb_prop_model.py
"""
from __future__ import annotations

from pathlib import Path
from statistics import mean

import pandas as pd
import numpy as np

from alpha.engines.sports.xgb_prop_model import XGBoostPropModel

DECAY = 0.85
LOG_FILE = Path("data/historical_logs.csv")
MIN_MINUTES = 20
MIN_GAMES = 5

_STAT_COLS = {
    "pts": ("pts", "data/xgb_pts_model.pkl"),
    "reb": ("reb", "data/xgb_reb_model.pkl"),
    "ast": ("ast", "data/xgb_ast_model.pkl"),
}


def _weighted_avg(vals: list[float]) -> float:
    if not vals:
        return 0.0
    total_w = total_v = 0.0
    for i, v in enumerate(vals):
        w = DECAY ** i
        total_w += w
        total_v += v * w
    return total_v / total_w


def _rest_days(current_date: pd.Timestamp, prev_dates: list[pd.Timestamp]) -> int:
    if not prev_dates:
        return 2  # neutral default
    delta = (current_date - prev_dates[0]).days - 1
    return int(max(0, min(4, delta)))


def build_features(
    group: pd.DataFrame,
    game_idx: int,
    stat_col: str,
    opp_def_rtg: float = 112.0,
    opp_pace: float = 100.0,
) -> dict | None:
    """
    Build feature dict for game at game_idx using only prior games as history.
    group is sorted newest-first within a player-season.
    """
    history = group.iloc[game_idx + 1:]
    qualifying = history[history["min_float"] >= MIN_MINUTES]
    if len(qualifying) < MIN_GAMES:
        return None

    vals = qualifying[stat_col].tolist()
    roll5  = _weighted_avg(vals[:5])
    roll10 = _weighted_avg(vals[:10])
    roll20 = _weighted_avg(vals[:20])
    min_recent = mean(qualifying["min_float"].tolist()[:5])

    matchup = str(group.iloc[game_idx]["matchup"])
    is_home = 1 if "vs." in matchup else 0

    current_date = pd.to_datetime(group.iloc[game_idx]["game_date"])
    prev_dates = [pd.to_datetime(d) for d in history["game_date"].tolist()]
    rest = _rest_days(current_date, prev_dates)

    return {
        "roll5": roll5,
        "roll10": roll10,
        "roll20": roll20,
        "min_recent": min_recent,
        "opp_def_rtg": opp_def_rtg,
        "is_home": is_home,
        "rest_days": rest,
        "pace": opp_pace,
    }


def train_model(stat_name: str, stat_col: str, out_path: str) -> None:
    print(f"\nTraining {stat_name.upper()} model...")
    df = pd.read_csv(LOG_FILE)
    df = df[df["min_float"] >= MIN_MINUTES].copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    df = df.sort_values(
        ["player_id", "season", "game_date"],
        ascending=[True, True, False],
    ).reset_index(drop=True)

    features, targets = [], []
    groups = df.groupby(["player_id", "season"])
    total = len(groups)
    for i, ((player_id, season), group) in enumerate(groups):
        if i % 100 == 0:
            print(f"\r  Building features: {i}/{total} player-seasons", end="", flush=True)
        group = group.reset_index(drop=True)
        for idx in range(len(group)):
            feat = build_features(group, idx, stat_col)
            if feat is None:
                continue
            features.append(feat)
            targets.append(float(group.iloc[idx][stat_col]))

    print(f"\r  {len(features)} training samples built from {total} player-seasons")

    model = XGBoostPropModel(target=stat_name)
    model.fit(features, targets)
    model.save(Path(out_path))

    imp = model.feature_importance()
    print(f"  Top features: " + ", ".join(
        f"{k}={v:.3f}" for k, v in sorted(imp.items(), key=lambda x: -x[1])[:4]
    ))
    print(f"  Saved → {out_path}")


if __name__ == "__main__":
    if not LOG_FILE.exists():
        print(f"ERROR: {LOG_FILE} not found.")
        print("Run fetch_historical_logs.py first.")
        raise SystemExit(1)

    rows = sum(1 for _ in open(LOG_FILE)) - 1  # subtract header
    print(f"Loaded {rows:,} game log rows from {LOG_FILE}")

    for stat_name, (stat_col, out_path) in _STAT_COLS.items():
        train_model(stat_name, stat_col, out_path)

    print("\nAll 3 models trained. Wire into PropModel by re-running the scanner.")
