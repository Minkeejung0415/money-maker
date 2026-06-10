# MLB Moneyline — Run-Distribution Simulation Architecture

The MLB moneyline model is **not** a direct team-win classifier. Win
probabilities are derived from simulated run distributions:

```
TeamSideFeatures (away)  ─┐
TeamSideFeatures (home)  ─┼─► estimate_expected_runs() per team
GameContext (park/weather)┘            │
                                       ▼
        fit_run_distribution(historical runs)  →  Poisson vs NegBin by AIC
                                       │   (family + dispersion reused,
                                       ▼    mean re-centered per game)
              simulate_game(n_sims ≥ 10,000, extra-innings tie resolution)
                                       │
                                       ▼
   independent_home_win_prob / independent_away_win_prob
   expected_total_runs / over_prob / under_prob (vs total line)
                                       │
                                       ▼
        ProbabilityCalibrator (fit on chronologically LATER holdout)
                                       │
                                       ▼
                evaluate_paper_bet()  — fail-closed gates
```

Modules: `alpha/engines/sports/mlb_run_model.py` (estimation, fitting,
simulation, calibration, gating) and `alpha/engines/sports/mlb_features.py`
(feature schema, Statcast helpers, shrinkage). The legacy `MLBModel`
classifier wrapper is untouched for compatibility.

## Expected runs

`estimate_expected_runs(batting, opposing, context)` multiplies a shrunk
base rate (team runs/game toward league 4.5) by capped, documented
factors:

- **lineup vs handedness** — shrunk lineup wOBA against the opposing
  starter's throwing hand, elasticity `(wOBA/league)^1.8`
- **starter** — starter xERA vs league, weighted by expected innings
  share (clamped 30–85%); capped at ±30%
- **bullpen** — bullpen xERA for the remaining innings, inflated by
  recent workload (`bullpen_ip_last3` above ~9 IP), high-leverage and
  closer unavailability
- **park** — `park_factor_runs` (1.0 neutral)
- **weather** — temperature/wind, capped ±12%, suppressed entirely when
  `roof_status` is `closed`/`dome`

Missing optional inputs contribute a **neutral** factor and are returned
in the missing list — never invented values.

## Run distribution

`fit_run_distribution(samples)` fits Poisson and Negative Binomial
(method-of-moments dispersion, `var = mu + alpha*mu^2`) on historical
per-game run totals and keeps the lower-AIC family. MLB runs are
overdispersed, so NegBin generally wins — but the choice is fit, not
assumed. The fitted family/dispersion is reused per game with the mean
re-centered (`RunDistribution.with_mean`).

## Simulation

`simulate_game()` draws ≥10,000 regulation totals per team, then resolves
ties inning-by-inning (per-inning mean = mu/9) like extra innings — no
ties in the output. Reports win probabilities, expected totals, and
over/under/push probabilities against a total line.

## Probabilities are kept separate

- `independent_home_win_prob` — pure simulation output
- `market_consensus_home_prob` — no-vig consensus, carried through
  untouched (benchmark / future ensemble feature; never blended)
- `final_calibrated_home_prob` — simulation probability passed through
  the fitted calibrator; `None` until a calibrator is fitted

Calibration is logistic on the logit scale and must be fit on a
**chronologically later holdout** (`chronological_calibration_split()`
provides the split; the calibration window never overlaps the data used
to build simulation inputs).

## Paper-bet gates (all required, fail closed)

`evaluate_paper_bet()` emits a paper bet only when:

1. **real odds present** — `game["has_real_odds"] is True`; StatsAPI
   placeholder −110s (tagged at the source in `mlb_stats.fetch_today_games`)
   never qualify
2. **probable pitchers confirmed** on both sides
3. **required features available** (`REQUIRED_FOR_BET`: confirmed
   pitcher, starter xERA, lineup wOBA vs both hands) on both sides
4. **fitted calibrator** — uncalibrated edges are not edges
5. **calibrated edge** vs the no-vig market exceeds `min_edge`
   (default 0.03)

Otherwise it returns `bet_side="no_bet"` with the explicit failed-gate
reasons. Paper only — no wagering automation exists or may be added.

## Feature priority & ablation groups

Features live in ordered groups (`mlb_features.FEATURE_GROUPS`) and must
be adopted cumulatively, one validated group at a time
(`mlb_feature_group_ablations()`): **starter → lineup → bullpen →
park/weather → market → advanced Statcast**. A group is kept only if it
improves chronologically-later holdout metrics. Do not bulk-add Statcast
fields.

## Statcast usage

Official fields consumed: `launch_speed`, `launch_angle`,
`estimated_woba_using_speedangle`, `release_speed`, `release_spin`,
`pitcher_days_since_prev_game`, `n_thruorder_pitcher`, `stand`,
`p_throws`, plus the zone coordinates below.

**2026 ABS schema change:** `plate_x`, `plate_z`, `sz_top`, `sz_bot`
definitions changed in 2026 to align with the ABS system. Mandatory
handling (`mlb_features`):

- `abs_era(season)` → 1 when `season >= 2026`
- `normalize_zone_features_by_era()` z-scores zone columns within each
  era (`*_norm` columns)
- `assert_zone_features_era_safe()` **raises** when raw zone coordinates
  span the 2026 boundary without normalization — call it before any
  training on zone features

## Small-sample handling

`shrink(observed, n, prior, k)` empirical-Bayes shrinkage with documented
pseudo-counts (`SHRINKAGE_K`): batter wOBA (k≈220 PA), pitcher xERA
(k≈150 BF), handedness splits (k≈250 PA, two-level via
`shrink_handedness_split` — split → overall → league), recent-form run
windows, bullpen xERA.

## Current limitations

- Ingestion adapters for xERA/xwOBA, lineups, bullpen logs, park factors,
  and weather are not built yet — the model consumes `TeamSideFeatures` /
  `GameContext` and fails closed on missing requirements, so it emits no
  bets until those feeds exist and a calibrator is fitted on real
  outcomes.
- Adjustment elasticities are modest documented defaults, not tuned
  values; tune only on chronologically earlier data, never the holdout.
- Home team batting in fewer innings when leading is not modeled at the
  game-total level (simulation samples full-game totals).
