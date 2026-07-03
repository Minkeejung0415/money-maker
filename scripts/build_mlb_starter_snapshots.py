"""Build historical as-of starter snapshots for MLB training."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpha.data.ingestion.mlb_starter_snapshots import (  # noqa: E402
    build_snapshots_from_lines,
    extract_starter_lines,
    fetch_game_feed,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build MLB historical starter snapshots from StatsAPI game feeds.")
    parser.add_argument(
        "--games-cache",
        default=str(ROOT / "data" / ".mlb_cache" / "historical_games_2023-03-01_2026-06-29.json"),
        help="Historical game JSON produced by scripts/build_mlb_player_v23.py",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "data" / "mlb" / "starter_snapshots" / "mlb_starter_snapshots_2023-2026.json"),
    )
    parser.add_argument(
        "--feed-cache-dir",
        default=None,
        help="Optional directory for raw StatsAPI game feed cache. Usually leave unset; feeds are large.",
    )
    parser.add_argument(
        "--line-cache",
        default=str(ROOT / "data" / ".mlb_cache" / "starter_lines_2023-2026.json"),
        help="Compact extracted starter-line cache for resumable full builds.",
    )
    parser.add_argument("--start", default=None, help="Optional inclusive YYYY-MM-DD game date lower bound.")
    parser.add_argument("--end", default=None, help="Optional inclusive YYYY-MM-DD game date upper bound.")
    parser.add_argument("--limit", type=int, default=None, help="Optional number of games to process for smoke tests.")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent StatsAPI fetch workers.")
    args = parser.parse_args()

    games = json.loads(Path(args.games_cache).read_text(encoding="utf-8"))
    if args.start:
        games = [game for game in games if str(game.get("date", ""))[:10] >= args.start]
    if args.end:
        games = [game for game in games if str(game.get("date", ""))[:10] <= args.end]
    games = sorted(games, key=lambda g: (str(g.get("date", "")), str(g.get("game_id", ""))))
    if args.limit is not None:
        games = games[: args.limit]

    print(f"Building starter snapshots from {len(games)} games...")
    line_cache = Path(args.line_cache) if args.line_cache else None
    cached_payload = _load_line_cache(line_cache)
    lines_by_game = {
        str(line.get("game_id")): [item for item in cached_payload["lines"] if str(item.get("game_id")) == str(line.get("game_id"))]
        for line in cached_payload["lines"]
    }
    failures = list(cached_payload["failures"])
    failure_ids = {str(item.get("game_id")) for item in failures}
    feed_cache_dir = Path(args.feed_cache_dir) if args.feed_cache_dir else None

    pending_games = [
        game for game in games
        if str(game.get("game_id") or "") and str(game.get("game_id") or "") not in lines_by_game and str(game.get("game_id") or "") not in failure_ids
    ]
    completed = len(games) - len(pending_games)
    if pending_games:
        print(f"  fetching {len(pending_games)} uncached games with {args.workers} workers...")
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_to_game = {
            executor.submit(_fetch_lines_for_game, game, feed_cache_dir): game
            for game in pending_games
        }
        for future in as_completed(future_to_game):
            game = future_to_game[future]
            game_id = str(game.get("game_id") or "")
            completed += 1
            try:
                lines_by_game[game_id] = future.result()
            except Exception as exc:  # pragma: no cover - network failure path
                failures.append({"game_id": game_id, "error": str(exc)})
                failure_ids.add(game_id)
            if line_cache and completed % 100 == 0:
                _save_line_cache(line_cache, lines_by_game, failures)
                print(f"  processed {completed}/{len(games)} games...")

    if line_cache:
        _save_line_cache(line_cache, lines_by_game, failures)

    lines = [line for game_lines in lines_by_game.values() for line in game_lines]
    snapshots = build_snapshots_from_lines(lines)
    payload = {
        "schema_version": "mlb-starter-snapshots-v1",
        "source": "MLB StatsAPI live feed boxscore pitching lines",
        "coverage": {
            "games_requested": len(games),
            "games_with_snapshots": len(snapshots),
            "starter_lines": len(lines),
            "failures": len(failures),
        },
        "unavailable_fields": {
            "xera": "not present in StatsAPI game boxscore; left null",
            "velocity_change": "requires pitch-level Statcast history; left null",
            "war_per_ip": "estimated from prior FIP run value, not official WAR",
        },
        "failures": failures[:100],
        "snapshots": snapshots,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    coverage = payload["coverage"]
    print(f"Saved {coverage['games_with_snapshots']} games / {coverage['starter_lines']} starter lines to {output}")
    if coverage["failures"]:
        print(f"Warnings: {coverage['failures']} feed failures. See payload failures for first 100.")


def _load_line_cache(path: Path | None) -> dict:
    if not path or not path.exists():
        return {"lines": [], "failures": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "lines": list(payload.get("lines") or []),
        "failures": list(payload.get("failures") or []),
    }


def _fetch_lines_for_game(game: dict, feed_cache_dir: Path | None) -> list[dict]:
    feed = fetch_game_feed(str(game.get("game_id") or ""), cache_dir=feed_cache_dir)
    return extract_starter_lines(feed, game)


def _save_line_cache(path: Path, lines_by_game: dict[str, list[dict]], failures: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [line for game_id in sorted(lines_by_game) for line in lines_by_game[game_id]]
    path.write_text(json.dumps({"lines": lines, "failures": failures}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
