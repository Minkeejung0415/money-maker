"""Build date-specific MLB player feature files from the local database."""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from alpha.data.ingestion.mlb_player_database import load_database_snapshot  # noqa: E402
from alpha.data.ingestion.mlb_stats import fetch_today_games  # noqa: E402
from alpha.engines.sports.mlb_player_feature_interpreter import (  # noqa: E402
    write_event_player_features_file,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build MLB event-level player features for a slate.")
    parser.add_argument("--date", required=True, help="Slate date in YYYY-MM-DD format")
    parser.add_argument("--database", default="data/mlb/player_database/mlb_player_database.json")
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    database_path = _repo_path(args.database)
    output_path = _repo_path(args.output) if args.output else (
        ROOT / "data" / "mlb" / "player_features" / f"mlb_player_features_{args.date}.json"
    )
    games = fetch_today_games(args.date)
    snapshot = load_database_snapshot(database_path)
    write_event_player_features_file(
        output_path,
        games=games,
        database_snapshot=snapshot,
        target_date=args.date,
    )
    print(f"Built MLB player feature file: {output_path}")
    print(f"Games: {len(games)}")


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


if __name__ == "__main__":
    main()
