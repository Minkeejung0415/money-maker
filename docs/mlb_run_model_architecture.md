# MLB Run Model Architecture

Status: **moneyline MVP — paper mode only**. Real-money execution is
disabled by design and there is no code path that places a wager.

## Components

| Layer | Module | Cost |
|---|---|---|
| Schedule + probable pitchers | `alpha/data/ingestion/mlb_schedule.py` | FREE (MLB StatsAPI) |
| Moneyline odds | `alpha/data/ingestion/mlb_odds_api.py` | PAID (The Odds API, budgeted) |
| Starter features | `alpha/data/ingestion/mlb_starter_features.py` | FREE (pybaseball / Baseball Savant) |
| Team offense baseline | `alpha/data/ingestion/mlb_team_offense.py` | FREE (pybaseball) |
| Feature schema | `alpha/engines/sports/mlb_features.py` | — |
| Run model + paper gate | `alpha/engines/sports/mlb_run_model.py` | — |
| Prediction log | `alpha/engines/sports/mlb_prediction_logger.py` | — |
| Scanner CLI | `scripts/mlb_moneyline_scanner.py` | — |
| Grading CLI | `scripts/grade_mlb_predictions.py` | FREE (StatsAPI finals) |

## Feature schema (`mlb_features.py`)

- `StarterFeatures` — probable starter rates (ERA/xERA/FIP/WHIP, K/BB/HR
  per 9, xwOBA allowed), workload (days rest, last pitch count, velocity
  delta over last 3 starts) and sample sizes.
- `TeamOffenseFeatures` — season + last-10 runs per game, wOBA/OBP/SLG,
  K%/BB% (lineup-agnostic MVP baseline).
- `TeamSideFeatures` — starter + offense for one side, plus intentionally
  unsourced MVP placeholders (`lineup_confirmed`, `bullpen_xera`) that the
  paper gate must keep seeing as missing.
- `GameContext` — event identifiers, venue, doubleheader flag, probable
  pitcher confirmation, park factor and weather (both unsourced ⇒ missing).

Fail-closed rule: a value that cannot be sourced stays `None` and its name
appears in `missing_features`. Nothing is ever invented.

### Hierarchical shrinkage

`shrink_to_prior(value, n, prior, k)` pulls small-sample rates toward
league priors with pseudo-count `k` (40 innings for starter rates).
Shrinkage only transforms observed values — `None` stays `None`.

## Run model (`mlb_run_model.py`)

Expected runs per side:

```
league_rpg × offense_factor × opposing_starter_factor × park_factor × home/away_factor
```

- `offense_factor`: shrunk season RPG blended 70/30 with last-10 RPG.
- `opposing_starter_factor`: innings-shrunk xERA (fallback FIP, then ERA)
  relative to league xERA.
- Factors are clamped to [0.70, 1.30] so one bad feed cannot produce an
  absurd probability.
- Missing inputs become NEUTRAL factors (1.0) and are recorded in
  `neutral_factors_used`.

Win probability: Pythagenpat with dynamic exponent `(RS+RA)^0.287`.

## Paper-bet gate (fail closed)

`evaluate_paper_gate` refuses (`NO_BET`) when ANY of:

- `calibrator_not_fitted` — always, until ≥ `MIN_CALIBRATION_SAMPLES`
  (150) graded chronological predictions exist and a calibrator is fitted.
- `required_features_missing` — any feature in `missing_features`.
- `neutral_factors_substituted` — model fell back to a neutral factor.
- `probable_pitchers_not_confirmed`
- `real_odds_missing`

The gate governs whether a *paper* bet is actionable. There is no
real-money path; the scanner enforces `--paper-only` unconditionally.

## Odds budget

See `docs/mlb_odds_budget_policy.md`. Summary: the free events endpoint
discovers the slate; at most **one paid h2h fetch per day** by default;
no automatic polling anywhere; manual `--force-refresh-odds` or
`--selected-event-id` only.

## Versioning

- `MODEL_VERSION = mlb_run_model_v1`
- `FEATURE_SCHEMA_VERSION = mlb_features_v1`

Both are stamped into every prediction log record.

## Known gaps (next phase, intentionally missing)

- Confirmed lineups + projected lineup wOBA
- Bullpen xERA / fatigue
- Park factors and weather
- Umpire assignments
- Calibration (needs graded history first)

MLB totals and pitcher props are explicitly out of scope for this MVP.
