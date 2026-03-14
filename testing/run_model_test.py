"""
testing/run_model_test.py
=========================
One-command model accuracy test.

Usage:
    ./venv/Scripts/python.exe testing/run_model_test.py              # yesterday
    ./venv/Scripts/python.exe testing/run_model_test.py 2026-03-13   # specific date

What it does:
  1. Fetches actual NBA box scores for the given date (free, nba_api)
  2. For each player who played 20+ min, fetches their season logs
  3. EXCLUDES any game ON or AFTER that date — simulates pre-game prediction
  4. Runs the current PropModel logic (decay, rest, location, opponent, TEAMMATE)
  5. Compares projection vs actual — prints hit rate per stat
  6. Appends to data/validation_log.csv for multi-day tracking

Zero Odds API credits used.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Re-use the walk-forward engine from validate_picks.py
from scripts.validate_picks import _run_walkforward_validation  # noqa: E402


def main() -> None:
    if len(sys.argv) > 1:
        test_date = sys.argv[1]
    else:
        test_date = str(date.today() - timedelta(days=1))

    print(f"\n{'='*65}")
    print(f"MODEL TEST — {test_date}")
    print(f"{'='*65}\n")
    _run_walkforward_validation(test_date)


if __name__ == "__main__":
    main()
