# NBA Props & Moneyline Pipeline — Audit Report

Branch: `fix/nba-props-moneyline-pipeline`
Scope: NBA player props + NBA moneyline only. Crypto, equities, soccer,
MLB, SGP-builder, and parlay code were not touched. No real-money
wagering exists or was added; all betting evaluation is paper-only.

---

## Bugs fixed

| # | Bug | Fix |
|---|---|---|
| 1 | Prop dedup by `(player, market)` kept highest over_odds, silently merging **different lines** (Over 25.5 -110 vs Over 26.5 +105) into one record | Raw records keyed by `(event_id, player, market, line, bookmaker)`; `aggregate_prop_lines()` groups per line with best/median prices. Alternative lines survive. |
| 2 | Moneyline `_extract_best_odds()` returned the **first** usable bookmaker, not the best price or a consensus | All bookmaker pairs retained; `home_odds`/`away_odds` = best price per side with book attribution; median per-book no-vig consensus computed. |
| 3 | Consensus risk: combining best prices across books fakes a low-vig pair | `build_consensus_moneyline()` removes vig **per book**, then takes the median fair home probability; away = 1 − home. Fails closed (None) with zero valid books. |
| 4 | Trainer used constants `opp_def_rtg=112`, `opp_pace=100` while inference used real values (train–inference mismatch) | Shared builder (`prop_features.py`) used by both; missing opponent context is NaN (XGBoost-native missing) and explicitly tracked — never a constant. |
| 5 | XGBoost output was re-multiplied by minutes/rest/pace/opponent factors that were already model inputs (double counting) | Two clean paths in `PropModel.predict_prop`: XGBoost projection goes straight to the CDF; multipliers exist only on the rule-based fallback path. |
| 6 | `is_home` derived from `location="all"` default → always "away" in the XGB features | Live inference requires an explicit `is_home` bool; without it the XGBoost path is skipped (logged) instead of guessing. Training reads it from the historical matchup string. |
| 7 | Inference `rest_days` was reverse-engineered from a rest **multiplier** | `rest_days`, `back_to_back`, `games_last_4_days` computed from actual game dates in both training and inference. |
| 8 | Trainer dropped rows where the **target game** had < 20 minutes (selection bias — conditions on postgame info) | Target rows always included; the 20-minute floor applies to history games only. Regression test included. |
| 9 | `player_threes` fetched but unmapped in `PropModel` (wasted credits) | `player_threes → FG3M` mapped (Poisson CDF) and a `fg3m` trainer target added; the market remains **disabled by default** at ingestion until validated. |
| 10 | Moneyline model selection scored `(mtime, accuracy)` — a newer file beat a better-validated one | Validated metric first (`.meta.json` sidecar accuracy, else filename), mtime only as tie-breaker. |
| 11 | `_build_game_features` paired teams by **positional iloc** against `team_index_current` ordering | TEAM_NAME-based row lookup; fails closed on unknown teams or missing column. |
| 12 | Missing XGBoost features were silently dropped to the overlapping subset | Schema validated: any missing expected feature fails closed to the market benchmark with a logged reason. |
| 13 | Market-implied fallback was labeled like a model (`source="market_implied"`) and could emit "edges" against itself | Renamed `market_benchmark`; `independent_model_prob=None`; `evaluate_bet()` returns `no_bet` unless `allow_market_fallback_bets=True` (research only, default False). |
| 14 | Legacy XGB prop pickles had no schema metadata and would run on mismatched features | `XGBoostPropModel.load()` rejects pickles without `feature_names`/`feature_schema_version` or with a version mismatch (`PropSchemaError`). |

## Files changed

- `alpha/data/ingestion/player_props.py` — rewritten (line-aware records, aggregation, budget cache, quota headers, configurable markets)
- `alpha/data/ingestion/odds_api.py` — rewritten (per-book retention, best price, consensus, regions config, budget cache, free `fetch_events()`)
- `alpha/engines/sports/prop_features.py` — **new** shared pregame feature builder (schema v2.0.0)
- `alpha/engines/sports/xgb_prop_model.py` — v2: shared schema, fail-closed validation, metadata, early stopping
- `alpha/engines/sports/prop_model.py` — two-path projection (XGB vs rule), FG3M mapping, explicit `is_home`, fail-closed model loading
- `alpha/engines/sports/nba_model.py` — benchmark separation, fallback-bet gate, model-selection fix, TEAM_NAME lookup, schema validation, heuristic flags
- `alpha/engines/sports/evaluation.py` — **new** metrics + walk-forward + ablation configs
- `alpha/engines/sports/paper_betting_logger.py` — **new** paper-bet JSONL log with CLV/PnL settlement
- `scripts/train_xgb_prop_model.py` — rewritten (chronological splits, early stopping, baselines gate, metadata, importance, `--ablation`)
- `scripts/evaluate_props_walkforward.py`, `scripts/evaluate_moneyline_walkforward.py` — **new**
- `docs/odds_api_budget_policy.md`, `docs/nba_props_moneyline_audit.md` — **new**

## Tests added

- `tests/unit/test_player_props_budget.py` (13): line preservation, same-line aggregation, best-over/under from different books, daily-cache/no-duplicate-paid-calls, force refresh, selected-event refresh, quota headers, market config, legacy cache
- `tests/unit/data/test_odds_api_budget.py` (15): first-book ≠ best, per-book retention, vig removal, consensus median (and not cross-book best pairing), fail-closed consensus, regions config, cache/force-refresh/quota, free events endpoint
- `tests/unit/engines/test_prop_features.py` (15): train/live parity, is_home, rest/B2B/3+ days, schedule density, future-row leakage guard, history-minutes vs target-minutes, NaN missingness, fail-closed vector, threes support, legacy/stale pickle rejection
- `tests/unit/test_prop_model_paths.py` (7): XGB not double-adjusted, explicit is_home required, undated-log fallback, schema-error fallback, rule path preserved, threes scoring, missing-context tracking
- `tests/unit/engines/test_xgb_prop_model.py` (rewritten, 9): v2 schema round-trip, fail-closed predict, early stopping metrics
- `tests/unit/engines/test_nba_model_benchmark.py` (17): probability separation, no-bet-from-benchmark, flags (h2h off by default, tanking guard), model selection (metric first, mtime tiebreak, meta.json override), metadata round-trip, TEAM_NAME lookup, schema fail-closed
- `tests/unit/engines/test_evaluation.py` (10) and `tests/unit/engines/test_paper_betting_logger.py` (9)
- `tests/integration/test_train_prop_dataset.py` (5): selection-bias regression, is_home/rest from data, NaN opp context, trainer↔builder parity
- `tests/integration/test_paper_betting_flow.py` (1): full log→settle→evaluate cycle

## Validation commands

```bash
# Unit + integration tests for the NBA scope
python -m pytest tests/unit/test_player_props.py tests/unit/test_player_props_budget.py \
  tests/unit/data/test_odds_api.py tests/unit/data/test_odds_api_budget.py \
  tests/unit/test_prop_model.py tests/unit/test_prop_model_paths.py \
  tests/unit/engines/test_prop_features.py tests/unit/engines/test_xgb_prop_model.py \
  tests/unit/engines/test_nba_model.py tests/unit/engines/test_nba_model_benchmark.py \
  tests/unit/engines/test_evaluation.py tests/unit/engines/test_paper_betting_logger.py \
  tests/integration/test_train_prop_dataset.py tests/integration/test_paper_betting_flow.py

# Retrain prop models (requires data/historical_logs.csv)
python scripts/fetch_historical_logs.py          # one-time, ~2-3h, free nba_api
python scripts/train_xgb_prop_model.py           # add --ablation for the slow report
```

## How to run daily budget mode

Nothing changed for callers: `OddsAPIClient().fetch_nba_games()` and
`PlayerPropsClient().fetch_all_game_props(games)` make at most one paid
fetch cycle per day and serve the date cache afterward. Default
`regions=["us"]`, default markets points/rebounds/assists. Estimated
default daily usage: **1 credit (moneyline) + ~3 credits x games on the
slate** (≈31 for a 10-game night). See `docs/odds_api_budget_policy.md`.

## How to force refresh selected events

```python
events = OddsAPIClient().fetch_events()           # FREE slate discovery
props  = PlayerPropsClient().fetch_all_game_props(
    games, force_refresh=True, selected_event_ids=["<event_id>"])
```

## How to run paper betting

```python
from alpha.engines.sports.paper_betting_logger import PaperBettingLogger
log = PaperBettingLogger()                        # data/paper_bets/paper_bets.jsonl
pid = log.log_prediction(event_id=..., sport="nba", market="player_points",
                         side="over", offered_odds=-110, line=25.5,
                         final_calibrated_prob=0.62, model_version=...,
                         feature_schema_version=..., suggested_stake=20.0, ...)
# after the game:
log.settle(pid, "win", closing_line=25.5, closing_odds=-120)
```

## How to run walk-forward evaluation

```bash
python scripts/evaluate_props_walkforward.py --stat pts --folds 5   # projection folds
python scripts/evaluate_props_walkforward.py --paper-log data/paper_bets/paper_bets.jsonl
python scripts/evaluate_moneyline_walkforward.py                    # paper-log report
python scripts/evaluate_moneyline_walkforward.py --list-ablations   # NBAModel ablation configs
```

## Features added

- Line-aware prop records with per-book best/median aggregation
- Per-book moneyline retention + median no-vig consensus
- Free events endpoint for slate discovery
- Budget cache metadata + quota header tracking on both clients
- Shared pregame feature schema (v2.0.0) with explicit missingness
- Baseline-gated training with chronological splits, early stopping, feature/permutation importance, optional ablation
- Market-benchmark / independent-model / final-calibrated probability separation
- Heuristic feature flags (h2h off by default) + ablation configs
- Paper-betting log with CLV/PnL and walk-forward evaluation scripts

## Features intentionally deferred

- **player_threes by default** — mapped and trainable, but stays off until walk-forward validation on real FG3M lines.
- **Historical opponent context** — per-game opponent def-rtg/pace backfill (the features are NaN in training until a leak-free historical source exists; XGBoost ignores them accordingly).
- **Schema fields without leak-free sources**: `starter_status`, `spread`, `game_total`, `team_implied_total`, `role_change_flag`, `teammates_out_minutes`, `vacated_usage_proxy`, and the market-specific extras (usage rate, FGA/3PA per minute, rebound competition, potential assists, etc.). Listed as reserved names in `prop_features.py`; never approximated with constants.
- **Moneyline retraining in-repo** (incl. market consensus as an ensemble feature and the recommended feature list): requires a historical odds+results dataset; collect it via the paper log first. The existing NBA-ML model is consumed, validated, and gated — not retrained here.
- **Probability calibration model for props** (temperature scaling retained); isotonic/Platt on walk-forward folds once a graded sample exists.

## Remaining risks / limitations

1. **No historical prop-line dataset** — projection quality is measurable walk-forward, but P(over) calibration and ROI can only be measured prospectively via the paper log. Do not interpret any current numbers as evidence of profitability.
2. **Moneyline XGBoost feature drift** — the model comes from the NBA-ML side repo; schema validation now fails closed, but a retrain pipeline in-repo is still missing.
3. **Trainer opponent features are inert** until historical opponent stats are backfilled (deliberate: NaN over fake constants).
4. **nba_api dependency** — game logs and team stats come from stats.nba.com, which rate-limits and occasionally changes shape; all call sites degrade gracefully but a daily failure means rule-path-only predictions that day.
5. **Closing-line capture is manual** — CLV requires settling with closing odds; a selected-event refresh near tipoff is the supported way to capture them (costs credits).
6. The aggregated back-compat `over_odds/under_odds` pair comes from the best-over book; consumers wanting best-under must read `best_under_odds`/`best_under_book` explicitly.

---

## Addendum: standalone detailed-pick (`--show-ev`) safety gates

The detailed single-pick analysis can display **diagnostic edges** for
research visibility, but a diagnostic edge is not a bet:

- Every prop result and pick row carries `source` (`"xgb"` |
  `"rule_fallback"`), `recommendation_eligible: bool`, and
  `refusal_reasons`.
- **Only rows with `recommendation_eligible=True` are actionable
  candidates.** Eligibility requires: an XGBoost-backed prediction with
  valid feature-schema metadata, held-out validation metrics
  (calibration evidence), all required live features available, a
  reliable projected-minutes estimate, and recent low-minute risk at or
  below the policy maximum (0.30, a fixed constant — never tuned on the
  current slate).
- **Fallback (`rule_fallback`) results are never eligible for real-money
  staking.** They render with `Edge: … (Diagnostic edge only)`, the
  banner `RESEARCH ONLY — fallback model is not eligible for real-money
  recommendations`, their refusal reasons, and **no Kelly stake, no
  bet-size recommendation, and no BET/VALUE BET labeling**.
- XGB-backed picks that fail validation checks render `RESEARCH ONLY —
  model validation incomplete` with the same suppression.
- `recommend_bet_types()` (the BET TYPE RECOMMENDATIONS section) only
  ever considers eligible picks; when none are eligible it emits nothing.
- The gating fails **safe**: a pick missing its safety fields is treated
  as fallback/research-only, never as eligible.

Refusal reason identifiers: `fallback_model`, `model_metadata_missing`,
`calibration_missing`, `required_features_missing`,
`projected_minutes_unreliable`, `low_minutes_risk_too_high`.

Paper logging (`scripts/log_predictions.py` and
`alpha/engines/sports/paper_betting_logger.py`) **retains diagnostic
rows** — they feed calibration — but every record stores
`recommendation_eligible`, `research_only`, and `refusal_reasons` so
research rows can never be confused with actionable wagers when grading.
