# MLB Moneyline MVP — Usage

Paper mode only. There is no real-money execution path anywhere in this
vertical, and the paper-bet gate fails closed (see below).

## Install

```bash
pip install -e ".[dev]"
pip install pybaseball   # free FanGraphs/Baseball Savant data
```

Set the (paid, budgeted) Odds API key in `.env` or the environment:

```bash
export ODDS_API_KEY=your_key_here   # the-odds-api.com
```

Without a key the scanner still runs: schedule, pitchers, and model
output all work; odds stay missing and every game refuses with
`real_odds_missing`.

## Run the scanner

```bash
python scripts/mlb_moneyline_scanner.py --date 2026-06-12
```

Options:

| Flag | Effect | Credit cost |
|---|---|---|
| `--date YYYY-MM-DD` | Slate date (default: today) | — |
| `--team SUBSTR` | Filter games by team substring | — |
| `--force-refresh-odds` | Manually spend an extra paid full-slate fetch | ~1 credit |
| `--selected-event-id ID` | Manually refresh one Odds-API event (repeatable) | ~1 credit per event |
| `--verbose` | Full missing-feature list, expected runs, debug logs | — |
| `--paper-only` | Always on; exists to state intent. Cannot be disabled. | — |

First run of the day performs the single paid odds fetch; every rerun the
same day is served from `data/cache/mlb/odds/h2h_<date>.json` at zero
cost. Schedule and probable pitchers are FREE and refresh every 15
minutes (configurable TTL).

## Sample output

```
Toronto Blue Jays @ New York Yankees
Probable pitchers:
  Toronto Blue Jays: Kevin Gausman
  New York Yankees: Gerrit Cole

Independent model:
  Toronto Blue Jays: 44.2%
  New York Yankees: 55.8%

Market consensus (no-vig):
  Toronto Blue Jays: 42.1%
  New York Yankees: 57.9%

Missing features:
  home.lineup_confirmed
  home.bullpen_xera
  context.park_factor
  context.weather

Paper-bet decision:
  NO BET
  Reasons:
  - calibrator_not_fitted
  - required_features_missing
```

`NO BET` with `calibrator_not_fitted` is the EXPECTED state for the MVP:
the model is uncalibrated and key feeds (lineups, bullpen, park, weather)
are intentionally unsourced. The gate only opens once those exist — it
never weakens by default.

## Inspect logs

Append-only JSONL under `data/mlb_predictions/`:

- `predictions.jsonl` — one immutable snapshot per scan per game
- `settlements.jsonl` — final results (idempotent, first wins)
- `closing_odds.jsonl` — closing market snapshots, stored separately

```bash
python -c "import json,sys; [print(json.dumps(json.loads(l), indent=2)) for l in open('data/mlb_predictions/predictions.jsonl')]"
python scripts/grade_mlb_predictions.py --list-ungraded
```

## Grade predictions

```bash
python scripts/grade_mlb_predictions.py                # settle all final games (free StatsAPI)
python scripts/grade_mlb_predictions.py --date 2026-06-12
python scripts/grade_mlb_predictions.py --dry-run
```

Grading uses the FREE StatsAPI schedule endpoint, settles only games
whose status is Final, is idempotent across reruns, and reports whether
enough graded history exists to fit a calibrator (150 minimum — fitting
itself is a future milestone, not automatic).

CLV appears in merged views only after closing odds are recorded for a
prediction (`MLBPredictionLogger.record_closing_odds`).

## Why real-money execution stays disabled

1. The model is **uncalibrated** — raw Pythagenpat probabilities have no
   demonstrated edge; no profitability claim is made or implied.
2. Required feeds are missing (confirmed lineups, bullpen state, park
   factors, weather, umpires).
3. No graded history exists yet to validate the model against closing
   lines (CLV).

## Missing feeds required for the next phase

- Confirmed lineup feed + projected lineup wOBA
- Bullpen xERA / recent usage (fatigue)
- Park factors per venue
- Weather (wind/temperature) at first pitch
- Umpire assignments
- Closing-odds capture job (manual, near first pitch)

Out of scope until further notice: MLB totals, pitcher props, real-money
wagering of any kind.
