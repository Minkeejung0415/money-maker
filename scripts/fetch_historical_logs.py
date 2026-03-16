"""
Fetch historical NBA game logs for XGBoost training.

Fetches seasons: 2022-23, 2023-24, 2024-25
For each active player: all game logs with PTS/REB/AST/FG3M/MIN/MATCHUP.
Saves to: data/historical_logs.csv

Runtime: ~2-3 hours (rate-limited nba_api calls).
Run once, then use the CSV to train the XGBoost model.

Usage:
    ./venv/Scripts/python.exe scripts/fetch_historical_logs.py
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

SEASONS = ["2022-23", "2023-24", "2024-25"]
OUT_FILE = Path("data/historical_logs.csv")
SLEEP = 0.6  # nba_api rate limit

FIELDS = [
    "season", "player_id", "player_name", "game_date", "matchup",
    "min_float", "pts", "reb", "ast", "fg3m", "opp_team",
]


def _parse_minutes(min_val) -> float:
    try:
        if isinstance(min_val, str) and ":" in min_val:
            parts = min_val.split(":")
            return float(parts[0]) + float(parts[1]) / 60
        return float(min_val)
    except (ValueError, TypeError):
        return 0.0


def fetch_all_logs() -> None:
    from nba_api.stats.static import players as nba_players
    from nba_api.stats.endpoints.playergamelogs import PlayerGameLogs

    all_players = nba_players.get_active_players()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    total = len(all_players) * len(SEASONS)
    done = 0

    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()

        for season in SEASONS:
            print(f"\nSeason {season} — {len(all_players)} players")
            for player in all_players:
                done += 1
                print(f"\r  [{done}/{total}] {player['full_name'][:35]:<35}", end="", flush=True)
                try:
                    time.sleep(SLEEP)
                    gl = PlayerGameLogs(
                        player_id_nullable=str(player["id"]),
                        season_nullable=season,
                        last_n_games_nullable="0",
                    )
                    df = gl.get_data_frames()[0]
                    if df.empty:
                        continue
                    for _, row in df.iterrows():
                        matchup = str(row.get("MATCHUP", ""))
                        opp = matchup.split(" ")[-1] if matchup else ""
                        writer.writerow({
                            "season": season,
                            "player_id": player["id"],
                            "player_name": player["full_name"],
                            "game_date": str(row.get("GAME_DATE", ""))[:10],
                            "matchup": matchup,
                            "min_float": round(_parse_minutes(row.get("MIN", 0)), 1),
                            "pts": float(row.get("PTS", 0) or 0),
                            "reb": float(row.get("REB", 0) or 0),
                            "ast": float(row.get("AST", 0) or 0),
                            "fg3m": float(row.get("FG3M", 0) or 0),
                            "opp_team": opp,
                        })
                except Exception as e:
                    print(f"\n  skip {player['full_name']}: {e}")

    print(f"\n\nDone. Saved to {OUT_FILE}")


if __name__ == "__main__":
    fetch_all_logs()
