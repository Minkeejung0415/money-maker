# Betting Accuracy & EV Audit — 2026-07-02

Scope: sports betting scanners, backtests, calibration, EV math, and pick
generation. Goal: fewer, better, more honestly calibrated picks — not more
picks. Evidence was gathered by reading the live code paths (`scripts/`,
`alpha/engines/sports/`, `alpha/data/ingestion/`) rather than headline docs.

## Top 10 accuracy / EV risks (ranked)

### 1. `--validate` never validated anything (FIXED in this audit)

- **Files:** `alpha/engines/sports/prop_backtester.py` → `_backtest_player_market()`
- **What:** `pred_prob = 1 - norm.cdf(synthetic_line, loc=mean(history_slice), ...)`
  where `synthetic_line == mean(history_slice)`. Every prediction was exactly
  0.50, so Brier was 0.25 by construction, the calibration table had one
  populated bucket, and the high-confidence hit rate was always 0. The
  scanner's "validation" gate was mathematically inert and never exercised
  the real `PropModel` at all.
- **Severity:** Critical — every NBA prop pick ever emitted was effectively
  unvalidated while appearing validated.
- **Fix applied:** projection is now the exponential-decay weighted average
  over the 20-game window (mirrors `PropModel`), evaluated against the flat
  10-game synthetic line. Regression test asserts predictions are not
  constant 0.5.
- **Proof metric:** calibration buckets now populate across deciles;
  per-player Brier varies with data.
- **Still open:** the backtester still does not call `PropModel.predict_prop`
  itself (no opponent adjustment, no temperature scaling, no XGBoost path).
  A true walk-forward replay of the production model against real
  sportsbook lines is Phase 2 work.

### 2. WC parlay "edge" was computed against fabricated -110 odds (FIXED)

- **Files:** `alpha/data/ingestion/football_data_client.py`,
  `scripts/wc_scanner.py`, `alpha/engines/sports/wc_sgp_builder.py`
- **What:** the football-data.org free tier has no odds, so every game was
  ingested with placeholder `-110/-110`. The WC parlay builder computed
  `edge = model_prob − implied(-110)` on those placeholders — any team the
  model liked above ~52.4% showed a fully fabricated "edge", got an EV, and
  got a Kelly stake. Several `picks/wc_parlay_*.txt` artifacts were produced
  this way. Placeholder two-way -110 odds are doubly wrong for a
  three-outcome soccer market.
- **Severity:** Critical for real money — stake sizing on invented prices.
- **Fix applied:** ingestion marks placeholder odds `has_market_odds: False`;
  the scanner excludes such games from parlay/edge building (override odds
  from `data/wc_odds_override.json` set the flag true); and `_best_wc_leg`
  now returns `None` when neither side has positive EV (the same fix the NBA
  `_best_ml_leg` already received).
- **Proof metric:** parlay mode with no odds override prints the exclusion
  notice and emits no edge/stake output; regression test
  `test_best_wc_leg_rejects_negative_ev_sides`.

### 3. `recommend_bet_types` recommended bets when nothing qualified (FIXED)

- **Files:** `alpha/engines/sports/parlay_constructor.py`
- **What:** when no pick cleared `min_edge`, the code silently fell back to
  "top 5 by EV" — including zero- and negative-edge picks — and still printed
  single/parlay recommendations with Kelly stakes.
- **Severity:** High — directly converts "no edge today" into staked bets.
- **Fix applied:** returns `[]` when nothing passes; regression test added.
- **Proof metric:** `test_all_picks_below_min_edge_returns_empty`.

### 4. Confidence tiers reward maximum disagreement with the market

- **Files:** `alpha/engines/sports/prop_model.py` → `_classify_confidence()`
- **What:** `HIGH` confidence = |model − no-vig market| > 0.08. The market is
  the strongest single predictor available; an 8-point-plus disagreement is
  far more often model error than market error (adverse selection /
  winner's-curse). This inverts risk: the system's *largest probable errors*
  are labeled its *best picks*, feed SGP construction, and drive edge, which
  is the same quantity — confidence and edge are double-counted.
  RESUME.md's "live results" (97-98% model probs, +45% edges) are the
  signature of this: v1.0's documented hit rate is 48.6%, below the ~52.4%
  breakeven at -110.
- **Severity:** Critical (design), needs data to fix well.
- **Smallest fix:** blend model prob toward the no-vig market prob
  (e.g. 60-70% market weight, as the market-blend used in `mlb_model.py`
  does), and cap displayed edge; grade every logged pick via
  `grade_predictions.py` and fit a shrinkage weight on outcomes.
- **Proof metric:** Brier/log-loss of blended vs raw model on graded
  prediction logs; bucket calibration at 0.7/0.8/0.9+.

### 5. Prop probabilities have no empirical calibration layer

- **Files:** `alpha/engines/sports/prop_model.py`
  (`_apply_temperature_scaling`, `_compute_p_over`)
- **What:** temperature T=0.75 is hard-coded "per research", not fit to this
  model's outcomes. Poisson/neg-binomial CDFs around a point projection
  understate real variance (minutes volatility, blowout benching, role
  changes), so tail probabilities of 95%+ survive even after scaling. The WC
  side has a real isotonic calibrator (`wc_calibration.py`, fit on
  validation folds only) — NBA props have nothing equivalent.
- **Severity:** High.
- **Smallest fix:** fit isotonic or Platt on the graded prediction log
  (`log_predictions.py` → `grade_predictions.py` already exists); apply at
  scan time; hard-cap model prob at ~0.90 until n>1000 graded picks say
  otherwise (MLB already caps via `MAX_XGB_CONF`).
- **Proof metric:** reliability table by decile on graded picks; Brier before
  vs after; count of >90% predictions that actually hit >85%.

### 6. Correlation matrix is built on misaligned, leaky vectors

- **Files:** `alpha/engines/sports/correlation.py`
  (`_fetch_player_vectors`, `_compute_r`)
- **What:** two independent defects: (a) each player's binary over/under
  vector is aligned by *array index* (`vec_a[:shared_len]`), not by game
  date — for non-teammates the paired entries are unrelated games, and even
  teammates misalign after any DNP; (b) the "rolling avg" is a single mean of
  the 20 *most recent* games applied to the whole season — future data
  binarizes past games. The resulting r values are noise, then injected into
  SGP joint probabilities via the copula adjustment, and positive r *raises*
  combined model prob (and EV) against multiplied leg odds.
- **Severity:** High for SGP modes.
- **Smallest fix:** join vectors on `GAME_ID`/`GAME_DATE`; binarize each game
  against the trailing average of prior games only; require ≥15 shared games,
  else r=0. Also: same-game books reprice SGP legs, so product-of-leg-odds
  overstates payout — treat SGP EV as upper bound in output.
- **Proof metric:** unit test with synthetic shared/disjoint schedules
  (teammates with known co-movement ⇒ r>0; different-team players with
  shifted schedules ⇒ r≈0); distribution of |r| should shrink sharply.

### 7. Parlay EV uses vig-inflated "market prob" and multiplied leg odds

- **Files:** `alpha/engines/sports/sgp_builder.py` (`_score_prop_combo`,
  `_score_mixed_combo`), `parlay_constructor.py`
- **What:** `combined_market = Π implied(odds)` retains the vig of every leg
  (~4.5% each), so `edge = model − market` looks *conservative*, but EV is
  computed against `Π decimal_odds`, which a real book will not pay on
  same-game legs (SGP repricing). Mixed combos multiply the ML leg in as
  independent even when the note says "positively correlated" — the
  correlation warning is cosmetic, never numeric. Legs default to `-110`
  when odds are missing (`p.get("over_odds", -110)`) — fabricated prices
  again, silently.
- **Severity:** Medium-high.
- **Smallest fix:** remove per-leg vig before computing displayed edge; drop
  legs with missing odds instead of defaulting to -110; label SGP EV
  "assuming book pays multiplied odds (upper bound)".
- **Proof metric:** test that a leg without odds is excluded, and a
  known-vig two-leg parlay shows edge equal to hand-computed no-vig value.

### 8. UNDER legs are priced with the OVER's model distribution and, if
   missing, the OVER's odds

- **Files:** `scripts/sgp_scanner.py` (UNDER leg generation, ~line 458)
- **What:** `under_prob = 1 − p_over` is fine only if the distribution is
  well-calibrated in both tails (it isn't, see #5), and
  `under_odds = raw.get("under_odds", raw.get("over_odds", -110))` invents a
  price when the book didn't post one. UNDER confidence tiers are hard-coded
  (0.65/0.72) and bypass `_classify_confidence`, the blowout gate, and the
  recent-trade cap applied to overs.
- **Severity:** Medium.
- **Smallest fix:** skip UNDER legs when `under_odds` is absent; route UNDER
  through the same confidence pipeline as OVER.
- **Proof metric:** scanner test: prop without under odds produces no under leg.

### 9. Context evaluator wires the wrong opponent and team

- **Files:** `scripts/sgp_scanner.py` (context step): every prop dict gets
  `"opponent_team": leg.away_team` — wrong for away players (their opponent
  is the home team); and re-built legs get `player_team=cs.get("home_team")`,
  overwriting the correct team resolved earlier, which breaks the
  ML+same-team correlation logic downstream.
- **Severity:** Medium (context is opt-in via `--context`), but it silently
  degrades the feature it exists to provide.
- **Smallest fix:** resolve opponent via `player_team` vs home/away; carry
  `leg.player_team` through unchanged.
- **Proof metric:** unit test: away player's opponent == home team; player_team
  preserved after context adjustment.

### 10. MLB team state and cross-season drift

- **Files:** `alpha/engines/sports/mlb_training.py`, `mlb_model.py`
- **What:** the MLB path is the most defensible in the repo (chronological
  split, separate calibration fold, vig removal, fail-closed artifact gates,
  probability cap, `has_market_odds` gating). Remaining risks: Elo /
  win_pct / run_diff accumulate across seasons with no between-season
  regression to the mean, and the runtime `team_state` is frozen at the
  artifact's `training_end` — the longer since retrain, the staler every
  feature. sklearn version-mismatch warnings on artifact load (noted in
  STATE.md) add silent-drift risk.
- **Severity:** Medium.
- **Smallest fix:** regress Elo toward 1500 (e.g. ×⅔ + 500) and reset
  win/run counters at season boundaries in `build_pregame_rows`; print
  `training_end` age in scanner output and refuse `pick_eligible` when the
  state is older than N days; re-save artifacts under the current sklearn.
- **Proof metric:** walk-forward Brier/log-loss across season boundaries
  before vs after; scanner shows state-age warning.

## Cross-cutting observation

The honest infrastructure largely exists — `evaluation.py` has Brier,
log-loss, reliability tables, CLV, walk-forward splits; `log_predictions.py`
/ `grade_predictions.py` can grade every emitted pick; `wc_calibration.py`
has a leakage-disciplined isotonic calibrator with a promotion gate; the MLB
pipeline has fail-closed artifact gates. The gaps are that the NBA prop
path (the one with live picks in RESUME.md) is wired to none of it, and its
one "validation" hook was inert (#1).

## 3-phase plan

### Phase 1 — highest impact, low risk (this commit + immediate follow-ups)

1. ✅ Fix inert PropBacktester prediction (done).
2. ✅ Stop recommending bets when nothing clears min_edge (done).
3. ✅ Gate WC parlay/edge output on real market odds; reject non-positive-EV
   WC legs (done).
4. Drop legs with missing odds everywhere instead of defaulting to -110
   (`sgp_builder`, `parlay_constructor`, scanner UNDER path).
5. Cap emitted model probability at 0.90 for NBA props (mirror MLB's
   `MAX_XGB_CONF`) until graded data justifies more.

### Phase 2 — validation and calibration

1. Grade the accumulated prediction log; publish Brier, log loss, and a
   decile reliability table per market (all code exists in `evaluation.py`).
2. Fit isotonic/Platt calibration on graded NBA prop predictions; apply at
   scan time; retire the hard-coded T=0.75 or fit T empirically.
3. Reframe confidence: base tiers on calibrated probability and sample
   size, not on disagreement with the market; shrink model prob toward
   no-vig market prob with a weight fit on outcomes.
4. Replace the correlation matrix construction with date-joined, trailing-
   average vectors and a minimum shared-game floor; add synthetic-data unit
   tests.
5. Extend `PropBacktester` to replay the actual `PropModel` walk-forward
   (with cached logs, no live API), reporting per-market calibration.

### Phase 3 — bigger model/data upgrades

1. Real historical odds/closing lines (even one book) so backtests measure
   ROI and CLV against actual prices instead of synthetic lines; make CLV
   the primary promotion metric.
2. Distributional upgrade for props: model minutes separately (the #1
   driver), then stat-per-minute; or quantile/negative-binomial regression
   with fitted dispersion instead of a 20-game sample std with floor 1.0.
3. MLB: season-boundary state regression, artifact re-save, and the
   pending full retrain once the local player database has real coverage.
4. SGP repricing model: estimate the book's correlation haircut so SGP EV
   is computed against a realistic payout, not multiplied leg odds.
5. Live odds feed for soccer/WC (paid tier or alternate book API) to retire
   the manual override file.

## Addendum 2026-07-02 — probability-only operation (no odds feed)

Operator direction: there is no sportsbook odds source, so edge/EV/Kelly
output is secondary; the system's job is emitting CORRECT probabilities.
Under that framing the following pure-probability fixes were implemented:

- **#6 Correlation engine — FIXED.** Vectors are now keyed and joined by
  game date (never array index); pairs with < 10 shared dates return r=0;
  each game is binarized against the trailing average of up to 20 strictly
  earlier games (no future leakage). Cache moved to `.corr_cache_v2.pkl` so
  stale v1 matrices cannot be reused. Regression tests: disjoint schedules
  → r=0, offset schedules align on shared dates, rising series proves no
  future leakage.
- **Probability cap — ADDED.** `PropModel` now clips emitted probability to
  [0.10, 0.90] (`_MAX_PROP_CONF`), symmetric so derived UNDER probabilities
  are capped identically. Raise only when graded prediction-log buckets
  above 0.90 prove calibrated.
- **#9 + primary-path opponent bug — FIXED.** The scanner passed
  `away_team` as every player's opponent, so away players' projections were
  adjusted against their own team's defense. The player's team is now
  resolved from the team map; opponent, `is_home`, `player_team`, and
  `team_win_prob` are passed through. Side effects: the trained XGBoost
  projection path (which requires explicit `is_home`) and the blowout
  confidence gate (which requires `team_win_prob`) now actually engage at
  runtime — previously both silently never fired from the scanner. The
  context-evaluator path got the same opponent fix and no longer overwrites
  `player_team` with `home_team`.

Revised priority order without odds:

1. Run the grading loop (`log_predictions.py` already logs every scanner
   pick; run `scripts/grade_predictions.py` after each slate). Nothing else
   can be calibrated until graded outcomes exist.
2. Once ≥ several hundred graded picks exist: publish the reliability table
   (`evaluation.py`), fit isotonic/temperature per market, and replace the
   hard-coded T=0.75 and the 0.90 cap with fitted values.
3. Rebase confidence tiers on calibrated probability + sample quality
   (games used, recency, variance), not on gap vs a market prob that is a
   constant 0.5 when odds are absent. Today, with no odds, every leg above
   the 0.60 floor grades HIGH — the label carries no information.
4. Known remaining gap: `scripts/sgp_scanner.py`'s prediction loop has no
   pipeline-level test harness, so the opponent-resolution fix is covered
   by reading, not by a test. A thin extraction of the leg-scoring loop
   into a testable function is the cheapest way to lock it in.

## Deferred: MLB retrain package (agreed 2026-07-02)

Decision: risk #10 stays documented-but-unpatched until it can ship as one
atomic package, because changing season-boundary feature semantics without
retraining would create a code/artifact mismatch — worse than the known
drift. MLB remains the most defensible pipeline in the repo until then.

The package (do together, in order):

1. Season-boundary state regression in `mlb_training.py`
   (regress Elo toward 1500, reset win/run counters between seasons).
2. Unit tests around that regression behavior.
3. Surface artifact `training_end` / team-state snapshot age in
   `mlb_scanner.py` output.
4. Gate or suppress `pick_eligible` when runtime team state is stale
   (older than N days).
5. Retrain via `train_mlb_moneyline.py` and re-validate via
   `evaluate_moneyline_walkforward.py` against local historical data
   (operator machine — training data lives in gitignored `data/`),
   then re-save artifacts under the current sklearn version.

## What was NOT changed and why

- Confidence-tier inversion (#4) and prop calibration (#5): the right fix
  needs graded outcome data to fit blend weights/calibrators. Changing the
  tier logic blind would just move the miscalibration around. The evidence
  missing: a graded sample (≥ several hundred picks) from
  `data/predictions/` via `grade_predictions.py`.
- Correlation rebuild (#6): DONE in the probability-only addendum above
  (date-joined vectors, trailing-average binarization, min shared games).
  The copula chaining in adjust_multi_leg_prob remains the first-order
  approximation — still treat 4+ leg joint probabilities as bounds.
- Kelly math itself was checked and is correct (quarter-Kelly, 5% cap,
  display cap noted separately); EV formula `p(d−1)−(1−p)` is correct.
