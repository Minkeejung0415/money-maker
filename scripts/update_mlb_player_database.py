"""Update the local MLB player-stat database from CSV-style inputs."""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from alpha.data.ingestion.mlb_player_database import (  # noqa: E402
    load_database_snapshot,
    normalize_absence_rows,
    normalize_batter_rows,
    normalize_bullpen_rows,
    normalize_lineup_rows,
    normalize_pitcher_rows,
    read_rows_csv,
    update_database_snapshot,
    write_json,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update local MLB player database from CSV inputs.")
    parser.add_argument("--date", required=True, help="Import date in YYYY-MM-DD format")
    parser.add_argument("--database", default="data/mlb/player_database/mlb_player_database.json")
    parser.add_argument("--batters-csv")
    parser.add_argument("--pitchers-csv")
    parser.add_argument("--bullpen-csv")
    parser.add_argument("--lineups-csv")
    parser.add_argument("--absences-csv")
    parser.add_argument("--source", default="local_csv")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    database_path = Path(args.database)
    if not database_path.is_absolute():
        database_path = ROOT / database_path

    snapshot = load_database_snapshot(database_path)
    updated = update_database_snapshot(
        snapshot,
        batters=normalize_batter_rows(_read_optional(args.batters_csv), source=args.source, as_of=args.date),
        pitchers=normalize_pitcher_rows(_read_optional(args.pitchers_csv), source=args.source, as_of=args.date),
        bullpen=normalize_bullpen_rows(_read_optional(args.bullpen_csv), source=args.source, as_of=args.date),
        lineups=normalize_lineup_rows(_read_optional(args.lineups_csv), source=args.source, as_of=args.date),
        absences=normalize_absence_rows(_read_optional(args.absences_csv), source=args.source, as_of=args.date),
        source=args.source,
        import_date=args.date,
    )
    write_json(database_path, updated)
    counts = {name: len(rows) for name, rows in updated["components"].items()}
    print(f"Updated MLB player database: {database_path}")
    print("Rows: " + ", ".join(f"{name}={count}" for name, count in counts.items()))


def _read_optional(path: str | None) -> list[dict]:
    if not path:
        return []
    input_path = Path(path)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    return read_rows_csv(input_path)


if __name__ == "__main__":
    main()
