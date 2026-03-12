# Phase 1 Baseline — March 11 Validation

## Run Info
- **Timestamp:** 2026-03-12 ~20:17 UTC
- **Command:** `./venv/Scripts/python.exe scripts/validate_picks.py --date 2026-03-11`
- **Mode:** nba_api live box scores + 2025-26 pre-game season logs (free, no Odds API)
- **Players validated:** 73
- **Games:** 6

## Results

pts=49.3% (count=36/73)
reb=34.2% (count=25/73)
ast=49.3% (count=36/73)
3pm=41.1% (count=30/73)
overall=43.5% (count=127/292)

## Notes
- Synthetic line = model projection rounded to nearest 0.5
- 50% = random; model is currently below random on all stats except pts/ast (at random)
- Rebounds at 34.2% is the worst — model over-projects rebounds significantly
- 3pm at 41.1% indicates no opponent 3P defense adjustment
