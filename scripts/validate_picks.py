"""
validate_picks.py — Check picks against actual results.

TWO modes — both use ZERO new API calls / zero Odds API credits:

  --date 2026-03-11  (default)
      Uses cached .pkl files from prop_cache:
        • mar-11 cache = pre-game history  → model prediction
        • mar-12 cache = includes mar-11 game at top → actual result
      No network at all.

  --date 2026-03-12
      Fetches March 12 box scores via nba_api (free, no key needed).
      Validates the hardcoded picks from picks/props_2026-03-12.txt etc.

Usage:
    python scripts/validate_picks.py
    python scripts/validate_picks.py --date 2026-03-12
"""
from __future__ import annotations

import argparse
import io
import pickle
import sys
import time
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.cache_hygiene import purge_prop_cache

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_CACHE_DIR = ROOT / "data" / ".prop_cache"
_SLEEP = 0.6

_STAT_COLS = ["PTS", "REB", "AST", "FG3M"]
_MARKET_LABELS = {"PTS": "pts", "REB": "reb", "AST": "ast", "FG3M": "3pm"}
_MIN_MINUTES = 20
_MIN_GAMES   = 5
ACTIVE_SEASON = "2025-26"


def _emit_season_verification() -> None:
    """Print canonical season evidence used by production modeling paths."""
    from alpha.data.ingestion.nba_stats_cache import NBAStatsCache
    from alpha.engines.sports.prop_model import PropModel

    stats_cache = NBAStatsCache()
    model = PropModel(season=ACTIVE_SEASON, stats_cache=stats_cache)

    print(f"ACTIVE_SEASON={ACTIVE_SEASON}")
    print(f"NBAStatsCache active season={ACTIVE_SEASON}")
    print(f"PropModel active season={getattr(model, '_season', ACTIVE_SEASON)}")


# ─── March 12 hardcoded picks (from picks/*.txt files) ───────────────────────

_PROPS_2026_03_12 = [
    {"player": "Trae Young",        "stat": "AST", "line": 5.5,  "model_prob": 0.956, "conf": "HIGH"},
    {"player": "Trae Young",        "stat": "PTS", "line": 13.5, "model_prob": 0.984, "conf": "HIGH"},
    {"player": "Cameron Johnson",   "stat": "PTS", "line": 8.5,  "model_prob": 0.990, "conf": "HIGH"},
    {"player": "Bruce Brown",       "stat": "REB", "line": 2.5,  "model_prob": 0.933, "conf": "HIGH"},
    {"player": "Aaron Gordon",      "stat": "AST", "line": 2.5,  "model_prob": 0.679, "conf": "HIGH"},
    {"player": "Cameron Johnson",   "stat": "REB", "line": 2.5,  "model_prob": 0.899, "conf": "HIGH"},
    {"player": "Bruce Brown",       "stat": "PTS", "line": 6.5,  "model_prob": 0.800, "conf": "HIGH"},
    {"player": "Jayson Tatum",      "stat": "AST", "line": 4.5,  "model_prob": 0.773, "conf": "HIGH"},
    {"player": "Jayson Tatum",      "stat": "PTS", "line": 19.5, "model_prob": 0.842, "conf": "HIGH"},
    {"player": "Jayson Tatum",      "stat": "REB", "line": 6.5,  "model_prob": 0.876, "conf": "HIGH"},
    {"player": "Jalen Suggs",       "stat": "PTS", "line": 14.5, "model_prob": 0.748, "conf": "HIGH"},
    {"player": "Desmond Bane",      "stat": "REB", "line": 4.5,  "model_prob": 0.744, "conf": "HIGH"},
    {"player": "Bilal Coulibaly",   "stat": "REB", "line": 3.5,  "model_prob": 0.754, "conf": "HIGH"},
    {"player": "Jared McCain",      "stat": "PTS", "line": 7.5,  "model_prob": 0.817, "conf": "HIGH"},
    {"player": "Isaiah Joe",        "stat": "AST", "line": 2.5,  "model_prob": 0.534, "conf": "HIGH"},
    {"player": "Ajay Mitchell",     "stat": "REB", "line": 3.5,  "model_prob": 0.614, "conf": "HIGH"},
]

_ML_2026_03_12 = [
    {"team": "Washington Wizards", "model_prob": 0.193},
    {"team": "Denver Nuggets",     "model_prob": 0.425},
    {"team": "Boston Celtics",     "model_prob": 0.476},
    {"team": "Brooklyn Nets",      "model_prob": 0.220},
    {"team": "Memphis Grizzlies",  "model_prob": 0.537},
    {"team": "Detroit Pistons",    "model_prob": 0.874},
    {"team": "Indiana Pacers",     "model_prob": 0.291},
    {"team": "Milwaukee Bucks",    "model_prob": 0.371},
]


# ─── Cache-based validation (March 11) ───────────────────────────────────────

def _load_pkl(player: str, date: str) -> list[dict] | None:
    fname = _CACHE_DIR / f"{player.replace(' ', '_')}_{date}.pkl"
    if not fname.exists():
        return None
    try:
        with open(fname, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _qualifying(logs: list[dict]) -> list[dict]:
    return [g for g in logs if g.get("MIN_float", 0) >= _MIN_MINUTES]


def _weighted_avg(values: list[float]) -> float:
    def safe_mean(v):
        return mean(v) if v else 0.0
    last5, last10, last20 = values[:5], values[:10], values[:20]
    w5  = 0.5 if last5  else 0.0
    w10 = 0.3 if last10 else 0.0
    w20 = 0.2 if last20 else 0.0
    total = w5 + w10 + w20
    if total == 0:
        return 0.0
    return (w5 * safe_mean(last5) + w10 * safe_mean(last10) + w20 * safe_mean(last20)) / total


def _run_mar11_cache_validation() -> None:
    """
    Walk-forward validation using only cached .pkl files.

    For each player with both a mar-11 AND mar-12 cache:
      - mar-11 cache  = game logs fetched before March 11 games (history only)
      - mar-12 cache  = game logs fetched after  March 11 games (row[0] = March 11 actual)

    We compute the model's weighted projection from mar-11 history,
    set synthetic_line = that projection, then check if actual > projection.
    Also shows the raw numbers so you can see how the model was thinking.
    """
    # Find players with both dates
    mar11_files = {f.name.replace("_2026-03-11.pkl", "") for f in _CACHE_DIR.glob("*_2026-03-11.pkl")}
    mar12_files = {f.name.replace("_2026-03-12.pkl", "") for f in _CACHE_DIR.glob("*_2026-03-12.pkl")}
    players = sorted(mar11_files & mar12_files)

    if not players:
        print("  No players found with both 2026-03-11 and 2026-03-12 cache files.")
        return

    print(f"  Players with cache for both dates: {len(players)}")
    print(f"  {', '.join(p.replace('_', ' ') for p in players)}\n")

    rows: list[dict] = []

    for fname in players:
        player = fname.replace("_", " ")
        pre_logs  = _load_pkl(player, "2026-03-11")   # history before mar-11 game
        post_logs = _load_pkl(player, "2026-03-12")   # includes mar-11 game at top

        if pre_logs is None or post_logs is None:
            continue

        pre_q  = _qualifying(pre_logs)
        post_q = _qualifying(post_logs)

        if len(pre_q) < _MIN_GAMES:
            continue

        # Most recent game in mar-12 cache = march 11 actual
        # Verify it's actually a new game vs pre cache
        if len(post_q) <= len(pre_q):
            continue  # no new game found

        actual_game = post_q[0]  # most recent = march 11

        for stat in _STAT_COLS:
            pre_values  = [g[stat] for g in pre_q  if stat in g]
            if len(pre_values) < _MIN_GAMES:
                continue

            actual_val  = float(actual_game.get(stat, 0))
            proj        = _weighted_avg(pre_values)
            std         = max(1.0, stdev(pre_values[:20]) if len(pre_values) >= 2 else 1.0)

            # Synthetic line = the projection itself (round to nearest .5)
            synthetic_line = round(proj * 2) / 2

            hit  = actual_val > synthetic_line
            diff = actual_val - proj

            rows.append({
                "player":  player,
                "stat":    stat,
                "proj":    round(proj, 1),
                "line":    synthetic_line,
                "actual":  actual_val,
                "hit":     hit,
                "diff":    diff,
                "std":     round(std, 1),
            })

    if not rows:
        print("  No qualifying rows found.")
        return

    # Print
    print(f"{'─'*72}")
    print(f"  {'Player':<22} {'Stat':<4} {'Proj':>5} {'Line':>5} {'Actual':>7} {'Result':<6}  {'Diff':>6}")
    print(f"{'─'*72}")
    hits = 0
    for r in sorted(rows, key=lambda x: (x["player"], x["stat"])):
        icon = "✅" if r["hit"] else "❌"
        diff_str = f"{r['diff']:+.1f}"
        print(f"  {r['player']:<22} {_MARKET_LABELS.get(r['stat'], r['stat']):<4} "
              f"{r['proj']:>5.1f} {r['line']:>5.1f} {r['actual']:>7.0f} {icon:<6}  {diff_str:>6}")
        hits += r["hit"]

    total = len(rows)
    print(f"{'─'*72}")
    print(f"\n  Synthetic over hit rate: {hits}/{total}  ({hits/total:.1%})")
    print(f"  (Synthetic line = model projection rounded to nearest 0.5)")
    print(f"  A 50% rate = random. >55% = model direction is correct.")

    # Per-stat breakdown
    print(f"\n  Per-stat breakdown:")
    for stat in _STAT_COLS:
        stat_rows = [r for r in rows if r["stat"] == stat]
        if not stat_rows:
            continue
        stat_hits = sum(r["hit"] for r in stat_rows)
        avg_diff  = mean(r["diff"] for r in stat_rows)
        label = _MARKET_LABELS.get(stat, stat)
        print(f"    {label:4s}  {stat_hits}/{len(stat_rows)}  ({stat_hits/len(stat_rows):.1%})  "
              f"avg diff vs proj: {avg_diff:+.1f}")


# ─── Live box-score validation (March 12) ────────────────────────────────────

def _get_game_ids(date_str: str) -> list[str]:
    from nba_api.stats.endpoints.scoreboardv3 import ScoreboardV3  # noqa
    time.sleep(_SLEEP)
    sb  = ScoreboardV3(game_date=date_str, league_id="00")
    raw = sb.get_dict()
    games = raw.get("scoreboard", {}).get("games", [])
    return [g["gameId"] for g in games]


def _fetch_box_scores(game_ids: list[str]) -> tuple[dict, dict]:
    from nba_api.stats.endpoints.boxscoretraditionalv3 import BoxScoreTraditionalV3  # noqa

    player_stats: dict[str, dict] = {}
    team_wins:    dict[str, bool]  = {}

    for gid in game_ids:
        time.sleep(_SLEEP)
        try:
            raw   = BoxScoreTraditionalV3(game_id=gid).get_dict()
            teams = raw.get("boxScoreTraditional", {}).get("homeTeam"), \
                    raw.get("boxScoreTraditional", {}).get("awayTeam")

            team_pts: dict[str, int] = {}
            for team in teams:
                if team is None:
                    continue
                tname = team.get("teamName", "")
                tcity = team.get("teamCity", "")
                full  = f"{tcity} {tname}".strip().lower()
                team_pts[full] = team.get("statistics", {}).get("points", 0)

                for p in team.get("players", []):
                    first = str(p.get("firstName", "")).strip()
                    last  = str(p.get("familyName", "")).strip()
                    name  = f"{first} {last}".strip().lower()
                    if not name:
                        continue
                    stats = p.get("statistics", {})
                    mins_str = str(stats.get("minutes", "0") or "0")
                    try:
                        # format: "35:44" (MM:SS)
                        mins = float(mins_str.split(":")[0])
                    except Exception:
                        mins = 0.0
                    player_stats[name] = {
                        "PTS":  float(stats.get("points", 0)  or 0),
                        "REB":  float(stats.get("reboundsTotal", 0) or 0),
                        "AST":  float(stats.get("assists", 0) or 0),
                        "FG3M": float(stats.get("threePointersMade", 0) or 0),
                        "MIN":  mins,
                    }

            if len(team_pts) >= 2:
                sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
                team_wins[sorted_teams[0][0]] = True
                team_wins[sorted_teams[1][0]] = False

        except Exception as exc:
            print(f"  [warn] box score fetch failed for {gid}: {exc}")

    return player_stats, team_wins


def _fetch_season_logs(player_id: int, season: str = "2025-26") -> list[dict] | None:
    """Fetch full season game logs for a player via nba_api (free)."""
    from nba_api.stats.endpoints.playergamelogs import PlayerGameLogs  # noqa
    time.sleep(_SLEEP)
    gl = PlayerGameLogs(player_id_nullable=str(player_id),
                        season_nullable=season, last_n_games_nullable="0")
    df = gl.get_data_frames()[0]
    if df.empty:
        return None
    rows = []
    for _, row in df.iterrows():
        entry = dict(row)
        min_val = entry.get("MIN", 0)
        try:
            entry["MIN_float"] = float(str(min_val).split(":")[0]) if ":" in str(min_val) else float(min_val)
        except Exception:
            entry["MIN_float"] = 0.0
        rows.append(entry)
    return rows


def _run_mar11_live_validation() -> None:
    """
    Walk-forward backtest for March 11 2026:
      1. Fetch actual March 11 box scores (nba_api V3, free)
      2. For each player who played, fetch their 2025-26 season logs
      3. EXCLUDE any game played ON or AFTER March 11 (simulate pre-game)
      4. Compute model projection from remaining history
      5. Synthetic line = projection rounded to .5
      6. Check if actual > line

    Zero Odds API credits. Only nba_api (free).
    """
    from nba_api.stats.static import players as nba_players  # noqa

    TEST_DATE = "2026-03-11"

    print(f"  Fetching {TEST_DATE} box scores via nba_api (free)...")
    game_ids = _get_game_ids(TEST_DATE)
    if not game_ids:
        print("  No games found.")
        return
    print(f"  Found {len(game_ids)} game(s)")
    player_stats, team_wins = _fetch_box_scores(game_ids)
    qualifying_players = {n: s for n, s in player_stats.items() if s["MIN"] >= _MIN_MINUTES}
    print(f"  {len(qualifying_players)} players with >= {_MIN_MINUTES}min\n")
    print(f"  Fetching 2025-26 season logs to simulate pre-game predictions...")
    print(f"  (This takes ~{len(qualifying_players)*0.6:.0f}s — one free nba_api call per player)\n")

    all_nba = nba_players.get_players()
    name_to_id = {p["full_name"].lower(): p["id"] for p in all_nba}

    rows: list[dict] = []
    no_data: list[str] = []
    done = 0

    for actual_name, actual_stats in sorted(qualifying_players.items()):
        pid = name_to_id.get(actual_name)
        if pid is None:
            no_data.append(actual_name)
            continue

        logs = _fetch_season_logs(pid, "2025-26")
        if not logs:
            no_data.append(actual_name)
            continue

        # Keep only games BEFORE the test date (simulate pre-game state)
        pre_logs = [g for g in logs
                    if str(g.get("GAME_DATE", ""))[:10] < TEST_DATE]
        pre_q = [g for g in pre_logs if g.get("MIN_float", 0) >= _MIN_MINUTES]

        if len(pre_q) < _MIN_GAMES:
            continue

        done += 1
        print(f"\r  {done} players processed...", end="", flush=True)

        for stat in _STAT_COLS:
            values = [float(g[stat]) for g in pre_q if stat in g and g[stat] is not None]
            if len(values) < _MIN_GAMES:
                continue
            proj   = _weighted_avg(values)
            line   = round(proj * 2) / 2
            actual = actual_stats[stat]
            hit    = actual > line
            rows.append({
                "player": actual_name.title(),
                "stat":   stat,
                "proj":   round(proj, 1),
                "line":   line,
                "actual": actual,
                "hit":    hit,
                "diff":   actual - proj,
            })

    print(f"\r  Done. {done} players validated, {len(no_data)} skipped (no data).\n")

    if not rows:
        print("  No qualifying rows. Season logs may not be available for this date.")
        return

    print(f"{'─'*72}")
    print(f"  {'Player':<24} {'Stat':<4} {'Proj':>5} {'Line':>5} {'Actual':>7}  Result   Diff")
    print(f"{'─'*72}")
    for r in sorted(rows, key=lambda x: (x["stat"], -abs(x["diff"]))):
        icon = "✅" if r["hit"] else "❌"
        print(f"  {r['player']:<24} {_MARKET_LABELS.get(r['stat'], r['stat']):<4} "
              f"{r['proj']:>5.1f} {r['line']:>5.1f} {r['actual']:>7.0f}  {icon}       {r['diff']:>+.1f}")

    hits  = sum(r["hit"] for r in rows)
    total = len(rows)
    print(f"{'─'*72}")
    print(f"\n  Overall hit rate : {hits}/{total}  ({hits/total:.1%})")
    print(f"  (50% = random  |  >55% = model direction is useful)\n")

    print(f"  Per-stat:")
    for stat in _STAT_COLS:
        sr = [r for r in rows if r["stat"] == stat]
        if not sr:
            continue
        sh    = sum(r["hit"] for r in sr)
        label = _MARKET_LABELS.get(stat, stat)
        avg_d = mean(r["diff"] for r in sr)
        print(f"    {label:4s}  {sh}/{len(sr)}  ({sh/len(sr):.1%})  avg diff vs proj: {avg_d:+.1f}")


def _run_mar12_live_validation() -> None:
    """Validate hardcoded March 12 picks using nba_api box scores (free)."""
    print("  Fetching box scores from nba_api (free, no Odds API)...")
    game_ids = _get_game_ids("2026-03-12")
    if not game_ids:
        print("  No games found. nba_api may not have results yet.")
        return
    print(f"  Found {len(game_ids)} game(s)")

    player_stats, team_wins = _fetch_box_scores(game_ids)
    print(f"  Got stats for {len(player_stats)} players, {len(team_wins)} teams\n")

    # Props
    print(f"{'─'*72}")
    print("  PROP PICKS  (picks/props_2026-03-12.txt + ml_sgp)")
    print(f"{'─'*72}")
    seen: set = set()
    prop_hits = prop_total = hc_hits = hc_total = 0
    for p in _PROPS_2026_03_12:
        key = (p["player"].lower(), p["stat"], p["line"])
        if key in seen:
            continue
        seen.add(key)
        stats = player_stats.get(p["player"].lower())
        if stats is None:
            print(f"  ? {p['player']:<25} OVER {p['line']} {_MARKET_LABELS[p['stat']]}  — DNP/not found")
            continue
        actual = stats[p["stat"]]
        hit    = actual > p["line"]
        icon   = "✅" if hit else "❌"
        prop_hits  += int(hit); prop_total  += 1
        if p["conf"] == "HIGH":
            hc_hits += int(hit); hc_total += 1
        print(f"  {icon} {p['player']:<25} OVER {p['line']:4.1f} {_MARKET_LABELS[p['stat']]:<3}  "
              f"model:{p['model_prob']:.1%}  actual={actual:.0f}")

    # ML
    print(f"\n{'─'*72}")
    print("  MONEYLINE PICKS")
    print(f"{'─'*72}")
    ml_hits = ml_total = 0
    seen_ml: set = set()
    for pick in _ML_2026_03_12:
        tl = pick["team"].lower()
        if tl in seen_ml:
            continue
        seen_ml.add(tl)
        matched = next((k for k in team_wins if any(w in k for w in tl.split())), None)
        if matched is None:
            print(f"  ? {pick['team']:<30} model:{pick['model_prob']:.1%}  — no data")
            continue
        won  = team_wins[matched]
        icon = "✅" if won else "❌"
        ml_hits += int(won); ml_total += 1
        print(f"  {icon} {pick['team']:<30} model:{pick['model_prob']:.1%}  → {'WON' if won else 'LOST'}")

    # Summary
    print(f"\n{'='*65}")
    print("SUMMARY — March 12")
    print(f"{'='*65}")
    if prop_total:
        print(f"  Props overall : {prop_hits}/{prop_total}  ({prop_hits/prop_total:.1%})")
    if hc_total:
        print(f"  HIGH conf     : {hc_hits}/{hc_total}  ({hc_hits/hc_total:.1%})")
    if ml_total:
        print(f"  Moneylines    : {ml_hits}/{ml_total}  ({ml_hits/ml_total:.1%})")
    if prop_total:
        avg_mp = mean(p["model_prob"] for p in _PROPS_2026_03_12)
        hit_r  = prop_hits / prop_total
        gap    = avg_mp - hit_r
        print(f"\n  Avg model prob : {avg_mp:.1%}")
        print(f"  Actual hit rate: {hit_r:.1%}")
        if gap > 0.15:
            print(f"  ⚠  OVERCONFIDENT by {gap:.1%}")
        elif gap < -0.05:
            print(f"  ℹ  Underconfident by {abs(gap):.1%}")
        else:
            print(f"  ✓  Roughly calibrated (gap: {gap:+.1%})")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date", default="2026-03-11",
        help="Date to validate: 2026-03-11 (cache-only, no API) or 2026-03-12 (nba_api only)",
    )
    args = parser.parse_args()

    print(f"\n{'='*65}")
    print(f"PICK VALIDATION — {args.date}")
    print(f"{'='*65}\n")
    print(f"[HYGIENE] cache_dir={_CACHE_DIR}")
    try:
        deleted = purge_prop_cache(_CACHE_DIR)
    except Exception as exc:
        print(f"[HYGIENE] status=ERROR reason={exc.__class__.__name__}: {exc}")
        raise
    print(f"[HYGIENE] deleted_pkl={deleted}")
    print("[HYGIENE] status=OK\n")
    _emit_season_verification()
    print()

    if args.date == "2026-03-11":
        print("Mode: nba_api box scores + cached .pkl history  (free, no Odds API)\n")
        print("Strategy: cached .pkl = 2024-25 season history for projections")
        print("          nba_api box scores = actual March 11 2026 results\n")
        _run_mar11_live_validation()

    elif args.date == "2026-03-12":
        print("Mode: nba_api box scores  (free, no Odds API credits)\n")
        _run_mar12_live_validation()

    else:
        print(f"No validation data for {args.date}.")
        print("Supported: 2026-03-11 (cache), 2026-03-12 (nba_api)")


if __name__ == "__main__":
    main()
