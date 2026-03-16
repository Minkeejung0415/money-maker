"""
Grade logged predictions by looking up actual box scores from nba_api.

Reads data/prediction_log.jsonl, finds ungraded records (outcome=None),
fetches the real box score for each player's game_date, writes True/False back.

Usage:
  ./venv/Scripts/python.exe scripts/grade_predictions.py
  ./venv/Scripts/python.exe scripts/grade_predictions.py --date 2026-03-15
  ./venv/Scripts/python.exe scripts/grade_predictions.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOG_FILE = ROOT / "data" / "prediction_log.jsonl"
NBA_API_SLEEP = 0.6

_MARKET_TO_COL = {
    "player_points": "PTS",
    "player_rebounds": "REB",
    "player_assists": "AST",
    "player_steals": "STL",
    "player_blocks": "BLK",
    "player_threes": "FG3M",
}


def load_records() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    records = []
    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def save_records(records: list[dict]) -> None:
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def fetch_player_stats(player_name: str, game_date: str, season: str = "2025-26") -> dict | None:
    """
    Fetch stats for player on a specific game_date.
    Returns dict with PTS/REB/AST/STL/BLK/FG3M/MIN or None if not found.
    """
    from nba_api.stats.static import players as nba_players
    from nba_api.stats.endpoints.playergamelogs import PlayerGameLogs

    all_players = nba_players.get_players()
    player_map = {p["full_name"].lower(): p["id"] for p in all_players}
    lastname_map = {p["full_name"].split()[-1].lower(): p["full_name"] for p in all_players}

    pid = player_map.get(player_name.lower())
    if pid is None:
        last = player_name.split()[-1].lower()
        full = lastname_map.get(last)
        if full:
            pid = player_map.get(full.lower())
    if pid is None:
        return None

    try:
        time.sleep(NBA_API_SLEEP)
        gl = PlayerGameLogs(
            player_id_nullable=str(pid),
            season_nullable=season,
            last_n_games_nullable="10",
        )
        df = gl.get_data_frames()[0]
        if df.empty:
            return None

        # Find the row matching game_date (format: YYYY-MM-DD)
        for _, row in df.iterrows():
            row_date = str(row.get("GAME_DATE", ""))[:10]
            if row_date == game_date:
                min_val = row.get("MIN", "0")
                try:
                    if isinstance(min_val, str) and ":" in min_val:
                        parts = min_val.split(":")
                        min_f = float(parts[0]) + float(parts[1]) / 60
                    else:
                        min_f = float(min_val) if min_val else 0.0
                except Exception:
                    min_f = 0.0

                return {
                    "PTS": float(row.get("PTS") or 0),
                    "REB": float(row.get("REB") or 0),
                    "AST": float(row.get("AST") or 0),
                    "STL": float(row.get("STL") or 0),
                    "BLK": float(row.get("BLK") or 0),
                    "FG3M": float(row.get("FG3M") or 0),
                    "MIN": min_f,
                }

        return None  # Date not found in last 10 games

    except Exception:
        return None


def grade_record(record: dict, actuals: dict) -> bool | None:
    """
    Returns True (hit), False (miss), or None (can't determine).
    """
    stat_col = _MARKET_TO_COL.get(record["market"])
    if stat_col is None:
        return None

    player_stats = actuals.get(record["player"])
    if player_stats is None:
        return None

    # Skip DNP (< 5 min)
    if player_stats.get("MIN", 0) < 5.0:
        return None

    actual_val = player_stats.get(stat_col, 0.0)
    line = record["line"]
    direction = record["direction"]

    if direction == "over":
        return actual_val > line
    else:
        return actual_val < line


def main() -> None:
    parser = argparse.ArgumentParser(description="Grade NBA prop predictions")
    parser.add_argument("--date", type=str, default=None,
                        help="Only grade predictions for this date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be graded without writing")
    args = parser.parse_args()

    records = load_records()
    if not records:
        print("No prediction log found or empty. Run sgp_scanner.py first.")
        return

    ungraded = [r for r in records if r["outcome"] is None]
    if args.date:
        ungraded = [r for r in ungraded if r.get("game_date") == args.date]

    if not ungraded:
        print("No ungraded records found.")
        # Show summary of already-graded records
        graded = [r for r in records if r["outcome"] is not None]
        if graded:
            hits = sum(1 for r in graded if r["outcome"])
            print(f"Already graded: {hits}/{len(graded)} = {hits/len(graded)*100:.1f}% accuracy")
            by_conf: dict[str, list[bool]] = {}
            for r in graded:
                by_conf.setdefault(r["confidence"], []).append(r["outcome"])
            for conf, outcomes in sorted(by_conf.items()):
                h = sum(outcomes)
                print(f"  {conf}: {h}/{len(outcomes)} = {h/len(outcomes)*100:.1f}%")
        return

    # Group by (player, game_date) to minimize API calls
    fetch_keys: dict[tuple[str, str], dict | None] = {}
    for r in ungraded:
        key = (r["player"], r["game_date"])
        if key not in fetch_keys:
            fetch_keys[key] = None

    print(f"Fetching box scores for {len(fetch_keys)} player-date combos...")
    for i, (player, game_date) in enumerate(fetch_keys.keys(), 1):
        print(f"  [{i}/{len(fetch_keys)}] {player} on {game_date}")
        stats = fetch_player_stats(player, game_date)
        fetch_keys[(player, game_date)] = stats

    # Build player -> stats lookup for current batch
    actuals: dict[str, dict | None] = {}
    for (player, game_date), stats in fetch_keys.items():
        actuals[player] = stats  # last date wins if multiple (shouldn't happen)

    # Grade
    graded_count = 0
    no_data_count = 0
    print(f"\nGrading {len(ungraded)} predictions...")

    for record in records:
        if record["outcome"] is not None:
            continue
        if args.date and record.get("game_date") != args.date:
            continue

        result = grade_record(record, actuals)
        if result is None:
            no_data_count += 1
            continue

        tick = "HIT" if result else "MISS"
        direction = record["direction"].upper()
        print(
            f"  {tick}  {record['player']:<28} {direction} {record['line']:<5} "
            f"{record['market'].replace('player_',''):<10} "
            f"[{record['confidence']}]  game={record['game_date']}"
        )

        if not args.dry_run:
            record["outcome"] = result
        graded_count += 1

    if not args.dry_run:
        save_records(records)
        print(f"\nWrote {graded_count} graded outcomes to {LOG_FILE}")
    else:
        print(f"\n[DRY RUN] Would grade {graded_count} records ({no_data_count} no-data)")

    # Summary
    all_graded = [r for r in records if r["outcome"] is not None]
    if all_graded:
        hits = sum(1 for r in all_graded if r["outcome"])
        print(f"\nOverall accuracy: {hits}/{len(all_graded)} = {hits/len(all_graded)*100:.1f}%")
        by_conf: dict[str, list[bool]] = {}
        for r in all_graded:
            by_conf.setdefault(r["confidence"], []).append(r["outcome"])
        for conf, outcomes in sorted(by_conf.items()):
            h = sum(outcomes)
            print(f"  {conf}: {h}/{len(outcomes)} = {h/len(outcomes)*100:.1f}%")
        print(f"  No data: {no_data_count}")


if __name__ == "__main__":
    main()
