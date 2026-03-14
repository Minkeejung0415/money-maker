"""
Dump ALL scored prop legs + moneylines for today.
No filters — everything the model scored, sorted by model_prob desc.
Usage: ./venv/Scripts/python.exe testing/dump_all_legs.py
"""
from __future__ import annotations
import io, sys, time
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Fix Windows console encoding
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Load .env so ODDS_API_KEY is available
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)
import os
# Also set directly in case pydantic-settings already consumed it
_env_path = ROOT / ".env"
for line in _env_path.read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from alpha.data.ingestion.odds_api import OddsAPIClient
from alpha.data.ingestion.player_props import PlayerPropsClient
from alpha.data.ingestion.nba_stats_cache import NBAStatsCache
from alpha.engines.sports.prop_model import PropModel

_MARKETS = ["player_points", "player_rebounds", "player_assists"]
_SLEEP   = 1.0
TODAY    = str(date.today())

def main():
    print(f"\n{'='*70}")
    print(f"ALL PROP LEGS — {TODAY}  (no filter — full model output)")
    print(f"{'='*70}\n")

    client = OddsAPIClient()
    games  = client.fetch_nba_games()
    print(f"Games: {len(games)}")

    props_client = PlayerPropsClient()
    raw_legs     = props_client.fetch_all_game_props(games)
    print(f"Raw prop lines: {len(raw_legs)}\n")

    stats_cache = NBAStatsCache()
    player_team_map = stats_cache.fetch_player_team_map()
    model = PropModel(stats_cache=stats_cache)

    seen   = set()
    done   = 0
    total  = len({r["player"] for r in raw_legs if r.get("market") in _MARKETS})
    scored = []

    for raw in raw_legs:
        if raw.get("market") not in _MARKETS:
            continue
        player = raw["player"]
        if player not in seen:
            seen.add(player)
            done += 1
            print(f"\r  Scoring {done}/{total}: {player[:35]:<35}", end="", flush=True)

        result = model.predict_prop(
            player_name=raw["player"],
            market=raw["market"],
            line=raw["line"],
            opponent_team=raw.get("away_team", ""),
            over_odds=raw.get("over_odds", -110),
        )
        if result is None:
            continue

        scored.append({
            "player":     raw["player"],
            "market":     raw["market"],
            "line":       raw["line"],
            "model_prob": result["model_prob"],
            "confidence": result.get("confidence", "?"),
            "proj":       result.get("proj_stat", 0),
            "over_odds":  raw.get("over_odds", -110),
            "home_team":  raw.get("home_team", ""),
            "away_team":  raw.get("away_team", ""),
        })

    print(f"\r  Done. {len(scored)} legs scored.{' '*30}\n")

    scored.sort(key=lambda x: x["model_prob"], reverse=True)

    MKTLABEL = {"player_points": "pts", "player_rebounds": "reb", "player_assists": "ast"}

    # ── Print all legs ────────────────────────────────────────────────────
    print(f"{'─'*70}")
    print(f"  {'Player':<26} {'Stat':<4} {'Line':>5} {'Proj':>5} {'Model%':>7} {'Conf':<6} {'Odds':>6}  Matchup")
    print(f"{'─'*70}")
    for l in scored:
        mkt  = MKTLABEL.get(l["market"], l["market"])
        odds = f"{l['over_odds']:+d}" if l["over_odds"] > 0 else str(l["over_odds"])
        game = f"{l['away_team'].split()[-1]} @ {l['home_team'].split()[-1]}"
        print(f"  {l['player']:<26} {mkt:<4} {l['line']:>5.1f} {l['proj']:>5.1f} "
              f"{l['model_prob']:>7.1%} {l['confidence']:<6} {odds:>6}  {game}")
    print(f"{'─'*70}")
    print(f"  Total: {len(scored)} legs\n")

    # ── Moneylines ───────────────────────────────────────────────────────
    from alpha.engines.sports.nba_model import NBAModel
    nba_model = NBAModel()
    ml_picks = []
    for g in games:
        home = g.get("home_team", "")
        away = g.get("away_team", "")
        home_odds = g.get("home_odds", -110)
        away_odds = g.get("away_odds", -110)
        if not home or not away:
            continue
        try:
            pred = nba_model.predict(g)
            home_prob = pred.get("home_win_prob", 0.5)
            away_prob = pred.get("away_win_prob", 1 - home_prob)
            ml_picks.append({"team": home, "opp": away, "prob": home_prob, "odds": home_odds, "side": "home"})
            ml_picks.append({"team": away, "opp": home, "prob": away_prob, "odds": away_odds, "side": "away"})
        except Exception as e:
            print(f"  [warn] ML predict failed for {home} vs {away}: {e}")

    if ml_picks:
        ml_picks.sort(key=lambda x: x["prob"], reverse=True)
        print(f"{'─'*70}")
        print(f"  {'Team':<30} {'Model%':>7} {'Side':<5} {'ML Odds':>8}  vs")
        print(f"{'─'*70}")
        for m in ml_picks:
            odds_str = f"{m['odds']:+d}" if m["odds"] else "N/A"
            print(f"  {m['team']:<30} {m['prob']:>7.1%} {m['side']:<5} {odds_str:>8}  vs {m['opp']}")
        print(f"{'─'*70}")

    # ── Save to picks ────────────────────────────────────────────────────
    out = ROOT / "picks" / f"picks_{TODAY}.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"================================================================\n")
        f.write(f"ALPHA TERMINAL — ALL PICKS  |  {TODAY}\n")
        f.write(f"================================================================\n")
        f.write(f"Games: {len(games)}  |  Prop lines scored: {len(scored)}\n")
        f.write(f"NOTE: AST legs marked [!] — model hit rate 41% (below random), bet at own risk\n")
        f.write(f"================================================================\n\n")

        f.write(f"MONEYLINES\n")
        f.write(f"{'─'*70}\n")
        f.write(f"  {'Team':<30} {'Model%':>7} {'Side':<5} {'ML Odds':>8}  vs\n")
        f.write(f"{'─'*70}\n")
        for m in ml_picks:
            odds_str = f"{m['odds']:+d}" if m["odds"] else "N/A"
            f.write(f"  {m['team']:<30} {m['prob']:>7.1%} {m['side']:<5} {odds_str:>8}  vs {m['opp']}\n")
        f.write(f"{'─'*70}\n\n")

        f.write(f"PROP LEGS  (sorted by model probability, highest first)\n")
        f.write(f"{'─'*70}\n")
        f.write(f"  {'Player':<26} {'Stat':<4} {'Line':>5} {'Proj':>5} {'Model%':>7} {'Conf':<6} {'Odds':>6}  Matchup\n")
        f.write(f"{'─'*70}\n")
        for l in scored:
            mkt   = MKTLABEL.get(l["market"], l["market"])
            odds  = f"{l['over_odds']:+d}" if l["over_odds"] > 0 else str(l["over_odds"])
            game  = f"{l['away_team'].split()[-1]} @ {l['home_team'].split()[-1]}"
            flag  = " [!]" if mkt == "ast" else ""
            f.write(f"  {l['player']:<26} {mkt:<4} {l['line']:>5.1f} {l['proj']:>5.1f} "
                    f"{l['model_prob']:>7.1%} {l['confidence']:<6} {odds:>6}  {game}{flag}\n")
        f.write(f"{'─'*70}\n")
        f.write(f"Total props: {len(scored)}  |  [!] = AST model unreliable (41% hit rate on 2026-03-12)\n")

    print(f"\n  Saved -> {out}\n")

if __name__ == "__main__":
    main()
