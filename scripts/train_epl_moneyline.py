"""Train and validate the EPL moneyline probability model."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from alpha.engines.sports.evaluation import probability_metrics
from alpha.engines.sports.epl_training import EPL_FEATURE_NAMES, build_epl_pregame_rows, calibrated


def fetch_epl_games(start: str, end: str) -> list[dict]:
    """Fetch EPL (PL) finished results from football-data.org in calendar-year chunks."""
    import os
    import requests
    from datetime import date

    api_key = os.environ.get("FOOTBALL_API_KEY") or os.environ.get("Football_API_KEY") or ""
    if not api_key:
        raise RuntimeError("FOOTBALL_API_KEY env var required")

    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    result: list[dict] = []

    for year in range(start_date.year, end_date.year + 1):
        chunk_start = max(start_date, date(year, 1, 1)).isoformat()
        chunk_end = min(end_date, date(year, 12, 31)).isoformat()

        url = "https://api.football-data.org/v4/competitions/PL/matches"
        params = {"dateFrom": chunk_start, "dateTo": chunk_end, "status": "FINISHED"}
        headers = {"X-Auth-Token": api_key}

        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for match in data.get("matches", []):
            score = match.get("score", {})
            full_time = score.get("fullTime", {})
            home_score = full_time.get("home")
            away_score = full_time.get("away")
            if home_score is None or away_score is None:
                continue
            result.append({
                "date": str(match.get("utcDate", ""))[:10],
                "game_id": str(match.get("id", "")),
                "home_team": match.get("homeTeam", {}).get("name", ""),
                "away_team": match.get("awayTeam", {}).get("name", ""),
                "home_score": home_score,
                "away_score": away_score,
                "home_xg": None,
                "away_xg": None,
            })

    # Deduplicate by game_id
    return list({g["game_id"]: g for g in result}.values())


def _matrix(rows):
    import numpy as np
    return (
        np.asarray([[float(r[n]) for n in EPL_FEATURE_NAMES] for r in rows]),
        np.asarray([r["home_win"] for r in rows]),
    )


def _platt(raw_probs, y):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    p = np.clip(raw_probs, 1e-6, 1 - 1e-6)
    logits = np.log(p / (1 - p)).reshape(-1, 1)
    return LogisticRegression().fit(logits, y)


def train(games: list[dict], output: Path) -> dict:
    import joblib
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression

    rows, state = build_epl_pregame_rows(games)
    if len(rows) < 300:
        raise ValueError(f"Need at least 300 completed non-draw games, got {len(rows)}")

    n = len(rows)
    a = int(n * 0.6)
    b = int(n * 0.8)
    train_rows, cal_rows, test_rows = rows[:a], rows[a:b], rows[b:]

    Xtr, ytr = _matrix(train_rows)
    Xc, yc = _matrix(cal_rows)
    Xt, yt = _matrix(test_rows)

    candidates = {
        "logistic": LogisticRegression(max_iter=2000, C=0.5),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            max_depth=3, max_iter=200, learning_rate=0.05,
            l2_regularization=1.0, random_state=42,
        ),
    }

    scored = {}
    for name, model in candidates.items():
        model.fit(Xtr, ytr)
        cal = _platt(model.predict_proba(Xc)[:, 1], yc)
        probs = calibrated(cal, model.predict_proba(Xt)[:, 1])
        metrics = probability_metrics(yt.tolist(), probs.tolist())
        metrics["accuracy"] = float(((probs >= 0.5) == yt).mean())
        scored[name] = (metrics["brier_score"], model, cal, metrics)

    name, (score, model, cal, metrics) = min(scored.items(), key=lambda x: x[1][0])

    home_rate = float(yt.mean())
    baselines = {
        "coin_brier": probability_metrics(yt.tolist(), [0.5] * len(yt))["brier_score"],
        "home_rate_brier": probability_metrics(yt.tolist(), [home_rate] * len(yt))["brier_score"],
    }
    validated = score < min(baselines.values())

    bundle = {
        "kind": "epl_win_probability_bundle",
        "validated": validated,
        "model": model,
        "calibrator": cal,
        "feature_names": list(EPL_FEATURE_NAMES),
        "team_state": state,
        "metrics": metrics,
        "baselines": baselines,
        "candidate": name,
        "training_start": rows[0]["date"],
        "training_end": train_rows[-1]["date"],
        "test_start": test_rows[0]["date"],
        "test_end": test_rows[-1]["date"],
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "version": "epl-v1",
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, output)

    meta = {k: v for k, v in bundle.items() if k not in ("model", "calibrator", "team_state")}
    output.with_suffix(".meta.json").write_text(
        json.dumps(meta, indent=2, default=str), encoding="utf-8"
    )
    return meta


def main():
    p = argparse.ArgumentParser(description="Train EPL moneyline probability model")
    p.add_argument("--input", help="Optional JSON file with pre-fetched games")
    p.add_argument("--start", default="2022-08-01", help="Start date for fetch")
    p.add_argument("--end", default="2025-05-31", help="End date for fetch")
    p.add_argument("--output", default="alpha/models/epl_win_probability.pkl", help="Output pkl path")
    args = p.parse_args()

    if args.input:
        games = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        games = fetch_epl_games(args.start, args.end)

    meta = train(games, Path(args.output))
    print(json.dumps(meta, indent=2, default=str))

    if not meta["validated"]:
        raise SystemExit("Model failed baseline release gate")


if __name__ == "__main__":
    main()
