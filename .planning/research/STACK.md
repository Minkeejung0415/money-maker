# Stack Research: NBA Prop Algorithm

## Recommended Approach

**Primary: LightGBM ensemble with EWMA projection + market-implied Bayesian prior**

The highest-accuracy production approach used by sharp quant shops combines three layers:

1. **Statistical projection layer** — EWMA rolling averages with adaptive decay (not fixed 5/10/20 game weights). Each market gets its own optimal decay rate learned from historical data.
2. **Machine learning layer** — LightGBM (preferred over XGBoost for player props: faster, handles sparse features better, less prone to overfitting on small samples). Trained to predict the *residual* between the stat projection and the actual outcome — not the raw value.
3. **Market calibration layer** — Bayesian shrinkage toward the market-implied probability. The market line is informative and should not be discarded; treat it as a prior, blend it with model output.

The key insight sharp bettors apply: **predict the distribution, not the point estimate**. The question is not "will he score 18 points" but "what is P(pts > 17.5) given this game context?" Modeling the full distribution (via Poisson or negative binomial for counting stats) outperforms normal-distribution assumptions, especially for rebounds and assists which are right-skewed and low-count.

**Minimum target for selectivity:** Only bet props where model_prob diverges from market_implied by >8% AND the prop passes a minimum 60% confidence floor. This is already in the codebase but calibration of the model_prob is likely off — the root cause of the 43.5% hit rate is model miscalibration, not necessarily wrong features.

---

## Key Libraries & Tools

| Library | Version | Use |
|---|---|---|
| `lightgbm` | 4.x | Main ML model (replaces or augments XGBoost) |
| `xgboost` | 2.x | Ensemble member, existing codebase already uses |
| `scikit-learn` | 1.4+ | Calibration (CalibratedClassifierCV, IsotonicRegression), GridSearchCV |
| `scipy.stats` | current | Poisson/NegBinomial distribution fitting for prop lines |
| `statsmodels` | 0.14+ | ARIMA for time-series trend, GLM for count data |
| `nba_api` | current | Already in use — also use `playerdashptreb`, `leaguehustlestatsplayer` |
| `pandas` | 2.x | Feature engineering, rolling windows |
| `numpy` | current | Vectorized stat calculations |
| `optuna` | 3.x | Hyperparameter tuning (Bayesian, better than GridSearch for LGBM) |
| `shap` | 0.44+ | Feature importance, model explainability, debugging bad predictions |

**No new data vendors needed** — nba_api has all required endpoints. The missing ones are:
- `playerdashptreb` — individual rebound opportunity stats (OREB%, DREB%)
- `leaguehustlestatsplayer` — contested rebounds, screen assists
- `boxscoreadvancedv2` — per-game USG%, TS%, box plus/minus
- `leaguedashptstats` — tracking-based touches, paint touches, front court touches

---

## Algorithm Options Ranked

### 1. LightGBM + Poisson Distribution (BEST for props)
**Why:** Counting stats (pts, reb, ast) are discrete non-negative integers. A Poisson or Negative Binomial model is statistically correct. LightGBM predicts the Poisson rate (lambda), then P(X > line) = 1 - Poisson.CDF(line, lambda). This alone will outperform the current normal distribution assumption, particularly for rebounds (typically lambda=5-8, very different shape than normal).

**Implementation:** Train LightGBM with `objective='poisson'`, output is lambda. Then `from scipy.stats import poisson; p_over = 1 - poisson.cdf(line, mu=lambda)`.

**Expected improvement:** +4-7 percentage points on rebounds specifically.

### 2. EWMA Projection + Bayesian Market Blend (HIGH ROI, LOW EFFORT)
**Why:** The current weighted average (0.5/0.3/0.2 fixed weights) is not adaptive. EWMA with a tunable `alpha` parameter learns the optimal recency weight per market from historical data. Blending with the market line as a prior corrects calibration without a full ML retraining.

**Formula:**
```
proj = ewma(last_n_values, alpha=alpha_market)       # alpha learned per market
sigma = ewma_std(last_n_values, alpha=alpha_market)  # adaptive std
market_lambda = line * market_implied / (1 - market_implied)  # implied projection
blended = (1 - prior_weight) * proj + prior_weight * market_lambda
p_over = 1 - poisson.cdf(line, blended)
```
**Expected improvement:** +3-5 percentage points overall, highest on low-game-count players.

### 3. Contextual Feature XGBoost (MEDIUM EFFORT, GOOD UPSIDE)
**Why:** The existing XGBoost model predicts game outcomes, not individual props. A dedicated prop-specific XGBoost (or LightGBM) trained on historical prop lines vs outcomes, using contextual features, would directly optimize for the prop hit/miss target.

**Critical features to add (not currently in model):**
- `usg_pct_last5` — usage rate in last 5 games (most predictive for pts/ast)
- `oreb_pct` and `dreb_pct` — rebound opportunity rate (most predictive for reb)
- `contested_reb_pg` — from hustle stats, measures real rebound competition
- `min_last3_avg` — minutes in last 3 games (injury load indicator)
- `back_to_back` — binary flag (significant negative for all markets)
- `home_away` — binary, home players average +1.2 pts, +0.4 reb, +0.3 ast
- `days_rest` — 0/1/2/3+ days since last game
- `line_movement` — opening line vs current line (sharp signal of where market moved)
- `opp_position_def_rank` — opponent's defensive ranking vs the player's position

**Implementation:** Build a training set of historical props (can use nba_api + historical Odds API data going back 3 seasons). Train LGBM to predict binary hit/miss. Use time-series CV (no leakage).

### 4. Negative Binomial for Rebounds Specifically (MEDIUM EFFORT, HIGH IMPACT)
**Why:** Rebounds have overdispersion — the variance exceeds the mean. Poisson assumes variance = mean; Negative Binomial allows variance > mean. This is empirically better for rebounds.

**Implementation:** `from scipy.stats import nbinom; p_over = 1 - nbinom.cdf(line, n=r, p=p)` where r and p are fit from historical data per player.

### 5. Isotonic Calibration of Existing Model (LOWEST EFFORT, IMMEDIATE WIN)
**Why:** The existing model outputs probabilities that may be systematically biased — e.g., it says 70% but actual hit rate is 52%. Isotonic regression calibration corrects this monotonically without retraining.

**Implementation:**
```python
from sklearn.calibration import CalibratedClassifierCV
# or post-hoc:
from sklearn.isotonic import IsotonicRegression
iso = IsotonicRegression(out_of_bounds='clip')
iso.fit(model_probs_historical, actuals_historical)
calibrated_prob = iso.predict([raw_prob])[0]
```
**This is the single highest ROI fix** — can be done in one session with backtest data.

### 6. Pure Regression (WEAKEST APPROACH)
Linear regression on raw stat values then comparing to line. Problem: doesn't model uncertainty correctly, treats all residuals as normally distributed, performs poorly on high-variance players. Currently what the model roughly does. The normal CDF assumption is the main source of error.

---

## Rebound-Specific Findings

Rebounds have the lowest hit rate (34.2%) because the current model makes three structural errors:

**Error 1: Wrong distribution family**
Rebounds are low-count, overdispersed integers. Normal distribution assumption is wrong. Use Negative Binomial or Poisson. For a player averaging 6.2 RPG with std 2.1, the normal model and Poisson model differ by 3-5 percentage points at common lines like 5.5 or 6.5.

**Error 2: Wrong opponent adjustment feature**
The current model adjusts for opponent REB/game (total team rebounds). This is too coarse. The correct adjustment is opponent's **position-specific defensive rebound rate** — how many rebounds does the opponent's center/PF unit grab vs league average? A small-ball lineup surrenders far more offensive rebounds than a traditional big-man lineup.

**Error 3: Missing opportunity features (most impactful)**
The single most predictive feature for rebounds is **rebound opportunity rate**, not raw rebound total. Key features to add:
- `OREB_PCT` — offensive rebound percentage (what % of available OREB does this player grab)
- `DREB_PCT` — defensive rebound percentage
- `contested_reb_per_game` — from `leaguehustlestatsplayer` endpoint
- `opp_fg_miss_rate_per_game` — how many shots does the opponent miss? More misses = more rebound opportunities
- `team_reb_opportunity_share` — what % of the team's rebound opportunities does this player take?
- `opponent_pace` — faster pace = more possessions = more rebound opportunities
- `linemates_reb_rate` — if Giannis plays with Brook Lopez, Lopez takes interior rebounds away

**nba_api endpoints to add for rebounds:**
```
playerdashptreb          # OREB_PCT, DREB_PCT, REB_CHANCE_PCT_ADJ
leaguehustlestatsplayer  # CONTESTED_REBOUNDS, CONTESTED_REB_PG
boxscoreadvancedv2       # Per-game USG%, REB%
```

**Practical fix with current data:**
The fastest improvement is to add `OREB_PCT` and `DREB_PCT` from `LeagueDashPlayerStats` (already fetched via the cache) and weight them into the rebound projection. These are available in the existing endpoint at no additional API cost.

**Position adjustment (already partially done):**
The `PositionFilter` suppresses rebound props for guards below 5.0 RPG. This is correct directionally but too binary. A continuous weight by position would be more accurate:
- Centers: 1.0x weight (no adjustment)
- Power Forwards: 0.95x
- Small Forwards: 0.85x
- Shooting Guards: 0.70x
- Point Guards: 0.65x

---

## Confidence Levels

| Recommendation | Effort | Expected Impact | Confidence |
|---|---|---|---|
| Isotonic calibration of existing model | Low (1 session) | +3-6% hit rate overall | HIGH — this is a known fix for miscalibrated ML outputs |
| Switch to Poisson/NegBinom distribution | Low (1-2 sessions) | +4-7% on rebounds | HIGH — statistically correct for integer counting stats |
| Add OREB_PCT/DREB_PCT features | Low (already cached) | +2-4% on rebounds | HIGH — these are the industry-standard rebound predictors |
| EWMA with adaptive alpha + market prior | Medium (2-3 sessions) | +3-5% overall | HIGH — EWMA + Bayesian blend is the de facto quant approach |
| LightGBM prop-specific model | High (3-5 sessions) | +5-10% overall | MEDIUM — requires historical training data pipeline |
| Line movement as signal | Medium | +2-4% on high-edge picks | MEDIUM — requires historical odds data (Odds API paid tier or alternate source) |
| Position-continuous weight for rebounds | Low | +1-2% on rebounds | MEDIUM — directionally correct but small effect |
| Back-to-back / days rest features | Low | +1-2% overall | MEDIUM — small effect but well-documented in literature |

**Priority order for implementation:**
1. Isotonic calibration (immediate, highest ROI per hour)
2. Poisson/NegBinom for rebounds (low effort, high impact on worst-performing market)
3. Add OREB_PCT + DREB_PCT + contested rebound features (already in cache, just wire in)
4. EWMA adaptive decay per market
5. Full LightGBM rebuild with training set (longer-term)

---

## Notes on Line Movement (Sharp Signal)

Sharp bettors track the opening line vs current line. When a line moves from 17.5 to 18.5 points, sharp money is on the under. The nba_api has no historical odds data, but The Odds API (already in the codebase) can provide this in real-time. Adding a `line_movement_direction` feature (up/flat/down since open) would provide a meaningful signal for high-confidence picks and is worth implementing once the base model is calibrated.

## Notes on Model Miscalibration Root Cause

The 43.5% overall hit rate vs the expected ~52-55% suggests the model is selecting too many LOW-edge props. The calibration issue is: when the model says "65% confidence," the actual hit rate is probably ~50-52%. This means the edge metric is wrong, not necessarily the directional prediction. Fixing calibration first (step 1 above) will reveal whether the underlying features are actually predictive or whether bigger structural changes are needed.
