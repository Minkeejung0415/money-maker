"""Run this to get today's NBA bet recommendations."""
import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NBA_DIR = ROOT / "NBA-Machine-Learning-Sports-Betting"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(NBA_DIR))

from dotenv import load_dotenv
load_dotenv()

# Auto-refresh NBA team stats so XGBoost has today's data
import importlib.util
_spec = importlib.util.spec_from_file_location("_get_data", NBA_DIR / "src" / "Process-Data" / "Get_Data.py")
if _spec:
    try:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _mod.main()
    except Exception as _e:
        print(f"[warn] Stats refresh skipped: {_e}")

from alpha.data.ingestion.odds_api import OddsAPIClient
from alpha.data.ingestion.nba_injuries import get_team_injury_impact
from alpha.engines.sports.engine import SportsEngine

games = OddsAPIClient().fetch_nba_games()
print(f"\nFetched {len(games)} NBA games\n")

if not games:
    print("No games found. Check your ODDS_API_KEY in .env")
    sys.exit(1)

# Fetch injury data once
print("Fetching injury/availability report...")
injury_impact = get_team_injury_impact()

print("\nTODAY'S GAMES:")
for g in games:
    home, away = g['home_team'], g['away_team']
    print(f"\n  {away} @ {home}  ({g['away_odds']:+d} / {g['home_odds']:+d})")
    for team in (home, away):
        impact = injury_impact.get(team)
        if impact and impact["out"]:
            names = ", ".join(
                f"{p['name']} ({p['pts']:.1f}ppg)" for p in impact["out"] if p.get("pts", 0) > 0
            ) or ", ".join(p["name"] for p in impact["out"])
            safe = names.encode("ascii", "replace").decode("ascii")
            print(f"    OUT ({team}): {safe}")

engine = SportsEngine(bankroll=10000, min_edge=0.04, kelly_fraction=0.25)
result = engine.run(games)

print("\n" + "="*55)
if not result["bets"]:
    print("No bets with >4% edge found today. No recommended bets.")
else:
    print("RECOMMENDED BETS:")
    for bet in result["bets"]:
        team = bet["bet_side"] == "home" and bet.get("home_team", bet["team"]) or bet["team"]
        impact = injury_impact.get(bet["team"], {})
        print(f"\n  BET:   {bet['team']} ({bet['bet_side'].upper()})")
        print(f"  EV:    {bet['ev']:.1%}")
        print(f"  Prob:  {bet['model_prob']:.1%} win")
        print(f"  Odds:  {bet['decimal_odds']:.2f} decimal")
        print(f"  Stake: ${bet['stake']:.2f}  (Kelly on $10,000 bankroll)")
        opp_team = bet["home_team"] if bet["bet_side"] == "away" else bet.get("away_team", "")
        opp_impact = injury_impact.get(opp_team, {})
        if opp_impact and opp_impact.get("out"):
            out_str = ", ".join(
                f"{p['name']} ({p['pts']:.1f}ppg)" for p in opp_impact["out"] if p.get("pts", 0) > 0
            )
            if out_str:
                safe = out_str.encode("ascii", "replace").decode("ascii")
                print(f"  OPP OUT: {safe}")
    print(f"\nTotal stake: ${result['total_stake']:.2f}")
