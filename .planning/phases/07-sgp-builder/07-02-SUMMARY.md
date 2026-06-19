---
plan: 07-02
phase: 07-sgp-builder
status: complete
requirements_addressed:
  - SCAN-01
  - SCAN-02
  - TEST-01
commits:
  - b57f436  # test(07-02): add failing wc_scanner tests
  - 3630628  # feat(07-02): implement wc_scanner.py
---

# Plan 07-02 Summary: wc_scanner.py CLI

## What Was Built

New file `scripts/wc_scanner.py` — standalone WC 2026 match parlay generator:

### Pipeline
1. **[1/4] Fetch WC fixtures** via `FootballDataClient.fetch_wc_games(date_from, date_to)`
2. **[2/4] Run Elo model** via `WCMatchModel.predict(game)` per fixture (mutates game dict)
3. **[3/4] Build combos** via `WCSGPBuilder.build(enriched_games, top_n)`
4. **[4/4] Print ranked output** with `*ELO EDGE*` annotation

### CLI Args
```
--mode parlay          # Only mode in v1.1
--date-from YYYY-MM-DD # Default: today
--date-to YYYY-MM-DD   # Default: today+7
--bankroll FLOAT       # Default: 10000
--min-edge FLOAT       # Default: 0.04
--max-legs INT         # Default: 4
--top INT              # Default: 5
--validate             # Print model info
```

### Output format (SCAN-02)
```
WC SCANNER — Mode: PARLAY  |  2026-06-26 to 2026-07-02  |  Min edge: 4.0%
...
#1  EV: 12.3%  |  Edge: 8.1%  |  Odds: 3.45x  |  Stake: $23.50
    Legs:
      * Brazil WIN  (1.82x)  model: 68.4%  [Elo: 2100]  *ELO EDGE*
```

### Run command
```
./venv/Scripts/python.exe scripts/wc_scanner.py --mode parlay
```

## Test Results
- **5/5 scanner tests passing** in `tests/unit/test_wc_scanner.py`
- **625/625 full suite passing** (0 regressions)
