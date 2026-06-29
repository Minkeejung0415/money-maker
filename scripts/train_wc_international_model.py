"""Train a WC 1X2 model from international qualifiers and friendlies."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pickle
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from alpha.engines.sports.wc_trained_model import (
    FEATURE_NAMES,
    build_runtime_features,
    normalize_team_name,
)

DEFAULT_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
DEFAULT_RAW_PATH = ROOT / "data" / "wc" / "international_results.csv"
DEFAULT_ARTIFACT = ROOT / "alpha" / "models" / "wc_international_1x2.pkl"
DEFAULT_META = ROOT / "alpha" / "models" / "wc_runtime_model.meta.json"
DEFAULT_CUTOFF = "2026-06-01"

K_BY_TOURNAMENT = {
    "world_cup": 45.0,
    "qualifier": 35.0,
    "major": 30.0,
    "friendly": 15.0,
    "other": 20.0,
}


def main() -> None:
    args = _parse_args()
    raw_path = Path(args.raw_path)
    if args.refresh or not raw_path.exists():
        _download(args.url, raw_path)

    rows = _load_rows(raw_path, cutoff=args.cutoff)
    training_rows, ratings = build_training_rows(rows)
    if len(training_rows) < args.min_rows:
        raise SystemExit(f"not enough rows to train: {len(training_rows)} < {args.min_rows}")

    train_rows, test_rows = _chronological_split(training_rows, args.test_fraction)
    x_train, y_train = _matrix(train_rows)
    x_test, y_test = _matrix(test_rows)

    model = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("model", LogisticRegression(max_iter=1500, C=0.7)),
    ])
    model.fit(x_train, y_train)
    probs = model.predict_proba(x_test)
    classes = [str(item) for item in model.classes_]
    metrics = _metrics(y_test, probs, classes)

    dataset_fingerprint = _fingerprint(raw_path, training_rows)
    artifact = {
        "model_id": "wc_international_1x2_v1",
        "schema_version": "wc-international-1x2-v1",
        "feature_names": list(FEATURE_NAMES),
        "classes": classes,
        "model": model,
        "ratings": ratings,
        "training_window": [training_rows[0]["date"], training_rows[-1]["date"]],
        "cutoff": args.cutoff,
        "metrics": metrics,
        "dataset_fingerprint": dataset_fingerprint,
    }

    artifact_path = Path(args.artifact_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("wb") as handle:
        pickle.dump(artifact, handle)

    meta = {
        "model_id": "wc_international_1x2_v1",
        "league": "WC",
        "market": "moneyline",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "training_window": artifact["training_window"],
        "feature_schema_hash": _schema_hash(),
        "dataset_fingerprint": dataset_fingerprint,
        "calibration": "multinomial_logistic_intrinsic",
        "brier": metrics["multiclass_brier"],
        "log_loss": metrics["log_loss"],
        "accuracy": metrics["accuracy"],
        "n_train": len(train_rows),
        "n_test": len(test_rows),
        "promotion_passed": metrics["multiclass_brier"] < args.max_brier,
        "allowed_runtime": metrics["multiclass_brier"] < args.max_brier,
        "artifact_path": artifact_path.name,
        "source_url": args.url,
        "included_tournaments": ["FIFA World Cup", "FIFA World Cup qualification", "Friendlies", "major internationals"],
    }
    meta_path = Path(args.meta_path)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")

    print(f"rows={len(training_rows)} train={len(train_rows)} test={len(test_rows)}")
    print(f"artifact={artifact_path}")
    print(f"metadata={meta_path}")
    print(json.dumps(metrics, indent=2, sort_keys=True))
    print(f"promotion_passed={str(meta['promotion_passed']).lower()} allowed_runtime={str(meta['allowed_runtime']).lower()}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--raw-path", default=str(DEFAULT_RAW_PATH))
    parser.add_argument("--artifact-path", default=str(DEFAULT_ARTIFACT))
    parser.add_argument("--meta-path", default=str(DEFAULT_META))
    parser.add_argument("--cutoff", default=DEFAULT_CUTOFF)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--min-rows", type=int, default=5000)
    parser.add_argument("--max-brier", type=float, default=0.70)
    return parser.parse_args()


def _download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "money-maker-wc-trainer/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        path.write_bytes(response.read())


def _load_rows(path: Path, *, cutoff: str) -> list[dict[str, str]]:
    cutoff_dt = datetime.fromisoformat(cutoff).date()
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("date"):
                continue
            game_date = datetime.fromisoformat(row["date"]).date()
            if game_date >= cutoff_dt:
                continue
            try:
                int(row["home_score"])
                int(row["away_score"])
            except (TypeError, ValueError):
                continue
            tournament = row.get("tournament", "")
            if not _include_tournament(tournament):
                continue
            rows.append(row)
    return sorted(rows, key=lambda item: item["date"])


def build_training_rows(rows: Iterable[dict[str, str]]) -> tuple[list[dict], dict[str, float]]:
    ratings: dict[str, float] = {}
    output: list[dict] = []
    for row in rows:
        home = normalize_team_name(row["home_team"])
        away = normalize_team_name(row["away_team"])
        ratings.setdefault(home, 1500.0)
        ratings.setdefault(away, 1500.0)
        tournament = row.get("tournament", "")
        features = build_runtime_features(
            home,
            away,
            ratings=ratings,
            tournament=tournament,
            neutral=str(row.get("neutral", "FALSE")).upper() == "TRUE",
            country=row.get("country", ""),
        )
        home_score = int(row["home_score"])
        away_score = int(row["away_score"])
        if home_score > away_score:
            outcome = "H"
        elif home_score < away_score:
            outcome = "A"
        else:
            outcome = "D"
        output.append({
            "date": row["date"],
            "home_team": home,
            "away_team": away,
            "outcome": outcome,
            **features,
        })
        _update_elo(ratings, home, away, outcome, tournament)
    return output, ratings


def _include_tournament(tournament: str) -> bool:
    label = tournament.lower()
    return (
        "friendly" in label
        or "fifa world cup" in label
        or "qualification" in label
        or "qualifying" in label
        or "qualifier" in label
        or any(token in label for token in ("uefa euro", "copa", "africa cup", "asian cup", "gold cup", "nations league"))
    )


def _update_elo(ratings: dict[str, float], home: str, away: str, outcome: str, tournament: str) -> None:
    elo_h = ratings.get(home, 1500.0)
    elo_a = ratings.get(away, 1500.0)
    expected_h = 1.0 / (1.0 + 10.0 ** (-(elo_h - elo_a) / 400.0))
    actual_h = 1.0 if outcome == "H" else 0.0 if outcome == "A" else 0.5
    k = _k_factor(tournament)
    change = k * (actual_h - expected_h)
    ratings[home] = elo_h + change
    ratings[away] = elo_a - change


def _k_factor(tournament: str) -> float:
    label = tournament.lower()
    if "fifa world cup" in label and "qualification" not in label:
        return K_BY_TOURNAMENT["world_cup"]
    if "qualification" in label or "qualifying" in label or "qualifier" in label:
        return K_BY_TOURNAMENT["qualifier"]
    if "friendly" in label:
        return K_BY_TOURNAMENT["friendly"]
    if any(token in label for token in ("uefa euro", "copa", "africa cup", "asian cup", "gold cup", "nations league")):
        return K_BY_TOURNAMENT["major"]
    return K_BY_TOURNAMENT["other"]


def _chronological_split(rows: list[dict], test_fraction: float) -> tuple[list[dict], list[dict]]:
    split = max(1, min(len(rows) - 1, int(len(rows) * (1.0 - test_fraction))))
    return rows[:split], rows[split:]


def _matrix(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray([[float(row[name]) for name in FEATURE_NAMES] for row in rows], dtype=float)
    y = np.asarray([row["outcome"] for row in rows])
    return x, y


def _metrics(y_true: np.ndarray, probs: np.ndarray, classes: list[str]) -> dict[str, float]:
    labels = list(classes)
    y_pred = [labels[int(np.argmax(row))] for row in probs]
    briers = []
    for idx, label in enumerate(labels):
        briers.append(brier_score_loss((y_true == label).astype(int), probs[:, idx]))
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "log_loss": float(log_loss(y_true, probs, labels=labels)),
        "multiclass_brier": float(sum(briers)),
        "home_brier": float(briers[labels.index("H")]) if "H" in labels else 0.0,
        "draw_brier": float(briers[labels.index("D")]) if "D" in labels else 0.0,
        "away_brier": float(briers[labels.index("A")]) if "A" in labels else 0.0,
    }


def _fingerprint(raw_path: Path, rows: list[dict]) -> str:
    digest = hashlib.sha256()
    digest.update(raw_path.read_bytes())
    digest.update(json.dumps({"n": len(rows), "first": rows[0]["date"], "last": rows[-1]["date"]}, sort_keys=True).encode())
    return digest.hexdigest()


def _schema_hash() -> str:
    return hashlib.sha256(json.dumps(list(FEATURE_NAMES), sort_keys=True).encode()).hexdigest()


if __name__ == "__main__":
    main()
