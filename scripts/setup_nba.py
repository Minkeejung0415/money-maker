"""
One-time setup + daily refresh for the NBA XGBoost model.

Run this before bet_scanner.py if team stats are stale, or any time you want
to make sure everything is fully loaded.

Usage:
    .\\venv\\Scripts\\python.exe .\\scripts\\setup_nba.py
"""
import os
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NBA_DIR = ROOT / "NBA-Machine-Learning-Sports-Betting"
TEAM_DB = NBA_DIR / "Data" / "TeamData.sqlite"
MODEL_DIR = NBA_DIR / "Models" / "XGBoost_Models"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(NBA_DIR))


def check_xgboost_models():
    print("\n[1/3] Checking XGBoost models...")
    models = list(MODEL_DIR.glob("*ML*.json"))
    if not models:
        print("  ERROR: No XGBoost ML models found in", MODEL_DIR)
        print("  These should already be in the repo. Check the Models/XGBoost_Models/ folder.")
        return False
    for m in models:
        print(f"  Found: {m.name}")
    return True


def refresh_team_stats():
    print("\n[2/3] Refreshing NBA team stats from stats.nba.com...")
    print("  (This pulls cumulative season stats up to today — may take 1-2 min)")

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_get_data",
            NBA_DIR / "src" / "Process-Data" / "Get_Data.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main()
        print("  Stats refresh complete.")
        return True
    except Exception as e:
        print(f"  WARNING: Stats refresh failed: {e}")
        print("  Will use cached data if available.")
        return False


def verify_team_data():
    print("\n[3/3] Verifying TeamData.sqlite...")
    if not TEAM_DB.exists():
        print("  ERROR: TeamData.sqlite not found")
        return False

    with sqlite3.connect(TEAM_DB) as con:
        cur = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = sorted([r[0] for r in cur.fetchall()])

    date_tables = []
    for t in tables:
        try:
            date_tables.append(datetime.strptime(t, "%Y-%m-%d"))
        except ValueError:
            continue

    if not date_tables:
        print("  ERROR: No date tables in TeamData.sqlite")
        return False

    latest = max(date_tables)
    today = datetime.today()
    days_stale = (today - latest).days
    print(f"  Latest data: {latest.strftime('%Y-%m-%d')} ({days_stale} days ago)")

    if days_stale > 3:
        print("  WARNING: Data is more than 3 days stale — predictions may be less accurate")
    else:
        print("  Data is fresh.")
    return True


def test_prediction():
    print("\n[Bonus] Running a test prediction...")
    from alpha.engines.sports.nba_model import NBAModel
    model = NBAModel()
    if not model._xgb_models_loaded:
        print("  WARNING: XGBoost model did not load — check xgboost is installed")
        print("  Run: .\\venv\\Scripts\\python.exe -m pip install xgboost joblib")
        return

    test_game = {
        "home_team": "Boston Celtics",
        "away_team": "Miami Heat",
        "home_odds": -200,
        "away_odds": +165,
        "league": "nba",
    }
    result = model.predict(test_game)
    print(f"  Model source: {result['source']}")
    print(f"  Boston Celtics win prob: {result['home_win_prob']:.1%}")
    print(f"  Miami Heat win prob:     {result['away_win_prob']:.1%}")
    if result["source"] == "xgboost":
        print("  XGBoost is ACTIVE and working.")
    else:
        print("  XGBoost not active — using market-implied fallback.")


if __name__ == "__main__":
    print("=" * 55)
    print("  NBA Model Setup & Data Refresh")
    print("=" * 55)

    ok = check_xgboost_models()
    if ok:
        refresh_team_stats()
        verify_team_data()
        test_prediction()

    print("\n" + "=" * 55)
    print("  Done. Run bet_scanner.py to get today's picks.")
    print("=" * 55)
