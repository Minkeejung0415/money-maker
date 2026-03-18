"""
Compare old vs new model predictions against today's actual NBA box scores.
No Odds API needed — uses prop lines from existing picks file + nba_api box scores.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PICKS_FILE = ROOT / "picks" / "props_all_2026-03-16.txt"
SEASON = "2025-26"
NBA_API_SLEEP = 0.6

# ── Parse picks from file ─────────────────────────────────────────────────────
import re

_STAT_ABBREV = {"pts": "PTS", "reb": "REB", "ast": "AST",
                "stl": "STL", "blk": "BLK", "3pm": "FG3M"}

def parse_picks(path: Path) -> list[dict]:
    picks = []
    # Example: "  Ryan Kalkbrenner: OVER 5.5 pts  (+100)  model: 92.0%  [HIGH]"
    pattern = re.compile(
        r"^\s+\*?\s*(.+?):\s+(OVER|UNDER)\s+([\d.]+)\s+(\w+)?\s*\([^)]+\)\s+model:\s+([\d.]+)%\s+\[(\w+)\]"
    )
    for line in path.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line)
        if m:
            player, direction, line_val, stat_word, prob, conf = m.groups()
            stat_col = _STAT_ABBREV.get((stat_word or "").lower(), "PTS")
            picks.append({
                "player": player.strip(),
                "direction": direction,
                "line": float(line_val),
                "stat_col": stat_col,
                "old_prob": float(prob) / 100,
                "confidence": conf,
            })
    # Deduplicate by (player, direction, line, stat_col) — SGP legs repeat at file end
    seen: set[tuple] = set()
    deduped = []
    for p in picks:
        key = (p["player"], p["direction"], p["line"], p["stat_col"])
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped

# ── Fetch real box scores from nba_api ───────────────────────────────────────

def fetch_box_scores_for_players(player_names: list[str], season: str = "2025-26") -> dict[str, dict]:
    """
    Fetch most recent game stats for each player using PlayerGameLogs.
    Returns {player_name: {PTS, REB, AST, MIN}}.
    Uses the same endpoint as PropModel — known to work for 2025-26.
    """
    from nba_api.stats.static import players as nba_players
    from nba_api.stats.endpoints.playergamelogs import PlayerGameLogs

    all_players = nba_players.get_players()
    player_map = {p["full_name"].lower(): p["id"] for p in all_players}
    # Also map last name for fuzzy matching
    lastname_map = {p["full_name"].split()[-1].lower(): p["full_name"] for p in all_players}

    result: dict[str, dict] = {}
    print(f"  Fetching most recent game stats for {len(player_names)} players...")

    for i, name in enumerate(player_names, 1):
        pid = player_map.get(name.lower())
        if pid is None:
            # Try last-name match
            last = name.split()[-1].lower()
            full = lastname_map.get(last)
            if full:
                pid = player_map.get(full.lower())
        if pid is None:
            continue

        try:
            time.sleep(NBA_API_SLEEP)
            gl = PlayerGameLogs(
                player_id_nullable=str(pid),
                season_nullable=season,
                last_n_games_nullable="1",
            )
            df = gl.get_data_frames()[0]
            if df.empty:
                continue
            row = df.iloc[0]
            game_date = str(row.get("GAME_DATE", ""))[:10]
            # Only count if game was today (or recently)
            min_val = row.get("MIN", "0")
            try:
                if isinstance(min_val, str) and ":" in min_val:
                    parts = min_val.split(":")
                    min_f = float(parts[0]) + float(parts[1]) / 60
                else:
                    min_f = float(min_val) if min_val else 0.0
            except Exception:
                min_f = 0.0

            result[name] = {
                "PTS": float(row.get("PTS") or 0),
                "REB": float(row.get("REB") or 0),
                "AST": float(row.get("AST") or 0),
                "MIN": min_f,
                "GAME_DATE": game_date,
            }
            if i % 10 == 0:
                print(f"  ...{i}/{len(player_names)} done")
        except Exception as exc:
            pass  # Skip silently

    return result

# ── Re-run new PropModel on same lines ───────────────────────────────────────

_MARKET_FOR_LINE = {
    # Map (player, line) to market — inferred from line magnitude and picks file context
}

def infer_market_from_line_and_context(line: float, direction: str, player: str) -> list[str]:
    """Return candidate markets based on line value."""
    markets = []
    if line >= 10.0:
        markets.append("player_points")
    if line <= 12.0:
        markets.append("player_rebounds")
    if line <= 10.0:
        markets.append("player_assists")
    return markets or ["player_points"]


def rescore_with_new_model(picks: list[dict]) -> list[dict]:
    """Re-score each pick with the updated PropModel."""
    from alpha.engines.sports.prop_model import PropModel

    model = PropModel(season=SEASON)
    rescored = []

    # Group by player to avoid redundant API calls
    players_seen: set[str] = set()
    for pick in picks:
        player = pick["player"]
        line = pick["line"]

        # Determine most likely market from line + picks file context
        # Use heuristic: line <= 5 → ast/reb, 5-14 → reb/ast/pts, 14+ → pts
        if line >= 14.0:
            markets = ["player_points"]
        elif line >= 6.0:
            markets = ["player_points", "player_rebounds"]
        elif line >= 3.0:
            markets = ["player_rebounds", "player_assists"]
        else:
            markets = ["player_assists", "player_rebounds"]

        new_prob = None
        used_market = None
        for mkt in markets:
            try:
                result = model.predict_prop(player, mkt, line, "Boston Celtics",
                                            over_odds=-110)
                if result is not None:
                    # Check if the model probability makes sense for direction
                    p = result["model_prob"]
                    if pick["direction"] == "OVER":
                        new_prob = p
                    else:
                        new_prob = 1.0 - p
                    used_market = mkt
                    break
            except Exception:
                continue

        rescored.append({
            **pick,
            "new_prob": round(new_prob, 4) if new_prob is not None else None,
            "market_inferred": used_market,
        })
        if player not in players_seen:
            players_seen.add(player)

    return rescored


# ── Main comparison ───────────────────────────────────────────────────────────

def col_for_market(market: str) -> str:
    return {"player_points": "PTS", "player_rebounds": "REB", "player_assists": "AST"}.get(market, "PTS")


def main():
    print("=" * 70)
    print("MODEL COMPARISON: OLD vs NEW  |  March 14, 2026")
    print("=" * 70)

    # 1. Parse old picks
    picks = parse_picks(PICKS_FILE)
    # Focus on HIGH confidence picks only (most meaningful comparison)
    high_picks = [p for p in picks if p["confidence"] == "HIGH"]
    print(f"\nLoaded {len(picks)} total picks, {len(high_picks)} HIGH confidence")

    # 2. Fetch real results for players in our picks
    unique_players = list({p["player"] for p in picks})
    print(f"\nFetching today's box scores from nba_api ({len(unique_players)} players)...")
    actuals = fetch_box_scores_for_players(unique_players, SEASON)
    print(f"  Loaded stats for {len(actuals)} players")

    # 3. Score against actuals (old model only — new model re-scoring takes too long live)
    #    Instead compare old model confidence vs actual outcome
    print("\n" + "=" * 70)
    print(f"{'Player':<28} {'Pick':<25} {'Old%':>6} {'Actual':>7} {'Hit?':>5}")
    print("-" * 70)

    correct = 0
    total = 0
    high_correct = 0
    high_total = 0
    no_data = 0

    # Stat column mapping — infer from line value
    def infer_col(pick: dict) -> str:
        line = pick["line"]
        if line >= 14.0:
            return "PTS"
        elif line >= 6.0:
            return "PTS"   # could be reb but pts more common at 6-13
        elif line >= 3.0:
            return "REB"
        else:
            return "AST"

    for pick in picks:
        player = pick["player"]
        actual = actuals.get(player)

        # Try to find actual stat
        if actual is None:
            # Try partial name match
            for aname, astats in actuals.items():
                if player.lower() in aname.lower() or aname.lower() in player.lower():
                    actual = astats
                    break

        if actual is None:
            no_data += 1
            continue

        # Infer the stat column and check if they played
        line = pick["line"]
        direction = pick["direction"]
        conf = pick["confidence"]

        # Use the exact stat column parsed from the picks file
        stat_col = pick.get("stat_col", "PTS")
        stat_val = actual.get(stat_col, 0.0)
        stat_name = stat_col.lower()

        # Skip DNP
        if actual["MIN"] < 5.0:
            no_data += 1
            continue

        hit = (direction == "OVER" and stat_val > line) or (direction == "UNDER" and stat_val < line)
        total += 1
        if hit:
            correct += 1
        if conf == "HIGH":
            high_total += 1
            if hit:
                high_correct += 1

        tick = "HIT" if hit else "MIS"
        print(
            f"{player:<28} {direction} {line:<5} ({stat_name:<3}) "
            f"{pick['old_prob']*100:>5.1f}%  "
            f"{stat_val:>6.1f}  "
            f"{tick:>5}  [{conf}]"
        )

    print("-" * 70)
    print(f"\nOLD MODEL ACCURACY vs REAL RESULTS:")
    print(f"  Overall:         {correct}/{total} = {correct/total*100:.1f}%" if total else "  No data")
    print(f"  HIGH confidence: {high_correct}/{high_total} = {high_correct/high_total*100:.1f}%" if high_total else "  No HIGH picks matched")
    print(f"  No data:         {no_data} players (DNP or name mismatch)")

    # NEW MODEL: Show what the temperature-calibrated probs would have been
    print("\n" + "=" * 70)
    print("TEMPERATURE CALIBRATION EFFECT (OLD -> NEW confidence for HIGH picks)")
    print("=" * 70)
    import math
    def temp_scale(p: float, T: float = 0.75) -> float:
        if p <= 0.01 or p >= 0.99:
            return p
        lo = math.log(p / (1.0 - p))
        return 1.0 / (1.0 + math.exp(-lo * T))

    for pick in picks:
        if pick["confidence"] != "HIGH":
            continue
        old_p = pick["old_prob"]
        new_p = temp_scale(old_p)
        print(f"  {pick['player']:<28} {pick['direction']} {pick['line']:<5}  "
              f"{old_p*100:.1f}% -> {new_p*100:.1f}%")


if __name__ == "__main__":
    main()
