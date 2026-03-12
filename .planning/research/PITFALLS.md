# Pitfalls Research: NBA Prop Model Tuning

> Written 2026-03-12. Grounded in this codebase's actual bugs and backtest structure.
> Feed directly into what NOT to do during implementation.

---

## Critical Mistakes (will kill accuracy)

### 1. Synthetic Line = Model Projection (the single worst error)
**What it is:** Setting `synthetic_line = round(proj * 2) / 2` — the line IS the model's own mean.
**Why it's lethal:** By definition, actual values cluster around the mean. Hit rate will converge to ~50% regardless of model quality. This is what produced the 43.5% baseline. A model that hits 43.5% on its own mean is actually quite bad — it means the projection is biased high (real results land below model expectation more often than not).
**Fix:** Test against real sportsbook lines (from Odds API, DraftKings, or manually scraped lines), not synthetic ones. If real lines aren't available, at least compute whether the model's projection directional bias is correct, not whether actual > own-projection.
**Status in this codebase:** `validate_picks.py` `_run_mar11_live_validation()` does exactly this on line 364-365. Every hit rate number from the March 11 walk-forward is measuring model-vs-own-mean, not model-vs-market. The "43.5%" baseline number is meaningless as a quality signal.

### 2. Wrong Season Data
**What it is:** Fetching 2024-25 stats when the model needs 2025-26 data.
**Why it's lethal:** A player's averages, role, team, minutes, and health are completely different year-over-year. Using last season's data to predict this season is equivalent to not having data at all.
**Status:** Was already fixed before this session. Re-verify by checking `PropModel.__init__` uses `"2025-26"` by default. Watch for any code that hardcodes `"2024-25"` in test fixtures.

### 3. Stale .pkl Cache
**What it is:** The `data/.prop_cache/` directory caches game logs by player+date. If the cache was built when the wrong season was active, all predictions are poisoned.
**Why it matters:** The cache TTL is same-day (filename = today's date), but if you ran the scanner yesterday with wrong season data, yesterday's cache files are still there with wrong data.
**Fix:** Delete `data/.prop_cache/` entirely before any validation run that is meant to measure a model change. Never trust cached data across algorithm changes.
**Specific risk:** `_load_pkl()` in validate_picks.py loads by filename date. If a file exists, it never re-fetches. This means a corrupted cache silently poisons results.

### 4. Confidence Score ≠ Calibration
**What it is:** The model outputs `model_prob` (P(over)) in the 0.50–0.99 range. Picks labeled "HIGH confidence" at 95%+ do not hit at 95% in reality.
**Evidence from this codebase:** March 12 picks included Trae Young O13.5 pts at 98.4% and Cameron Johnson O8.5 pts at 99%. These lines are near the player's floor — sportsbooks set lines below average for a reason. A 99% model probability on a line that's 5 pts below a player's 5-game average is a miscalibrated model, not a great pick.
**Fix:** Calibrate against empirical hit rates per confidence bucket before using confidence to filter. Until calibrated, treat any model_prob > 80% with suspicion — it almost always means the line is trivially low, not that the model found signal.

### 5. Overconfidence from Trivially Low Lines
**What it is:** When the market sets a line significantly below a player's average (injury concern, recent benching, tough schedule), the model sees "huge edge" and outputs 95%+ confidence. But the market already knows something the model doesn't.
**Example:** Cameron Johnson O8.5 pts at 99% model confidence — his avg is ~14 pts. The market moved the line down because of a reason. The model doesn't know why.
**Fix:** When `model_prob > 0.85`, check: is the line more than 1.5 stdev below the projection? If yes, the market is pricing in context the model lacks. Treat these as LOW confidence regardless of model output.

### 6. No Line Movement / Market Efficiency Signal
**What it is:** Using only the "closing line" without knowing where it opened or how it moved.
**Why it matters:** A line that opened at 15.5 and moved to 14.5 tells you sharp money is on the over. A line that opened at 14.5 and moved to 15.5 tells you the market is fading the over. The model currently ignores this entirely.
**Practical impact:** For a free project, this may not be fixable (line movement data costs money). But knowing this pitfall prevents over-trusting high model_prob on lines that moved against the pick direction.

---

## Rebound-Specific Pitfalls

### 1. The Opponent Rebound Adjustment Direction is Backwards for Players
**Current code (prop_model.py line 231-236):**
```python
# High-rebounding opponent → leaves fewer boards → scale down
league_avg = _LEAGUE_AVGS["reb_pg"]  # 43.5 total rebounds/game
opp_val = opp.get("reb_pg", league_avg)
scale = max(lo, min(hi, league_avg / opp_val))
```
**Problem:** Using opponent's own rebound rate as a proxy for defensive rebounding is conceptually muddled. A team that grabs many rebounds offensively inflates `reb_pg`, but what matters for an opposing player's rebounds is how many DEFENSIVE rebounds the opponent grabs (i.e., limiting offensive rebounds for the player's team). These are different things.
**Correct approach:** Use opponent's `DREB_pg` (defensive rebounds per game). A high `DREB_pg` opponent cleans the glass and leaves fewer offensive rebounds for the opposing player. But also: total rebounds = OREB + DREB, so total team reb_pg is a weak signal. Use opponent `OREB_pg` allowed (how many offensive boards they give up) for offensive rebounders, and opponent `DREB_pg` for defensive rebounders.
**Simpler fix:** Use opponent's total rebound rate relative to league, capped tighter at ±10%. The current ±15% cap allows swings that exceed the real effect size.

### 2. Position-Adjusted Rebound Baselines
**What it is:** A center averages 10 rebounds/game; a guard averages 3. Using a single `league_avg` of 43.5 total rebounds/game against a player's individual rebound average is scale-mismatch.
**The model's implicit assumption:** The opponent adjustment ratio `league_avg / opp_val` is the same multiplier for a center (10 reb) and a guard (3 reb). It should be applied to position-level averages, not league totals.
**Fix:** Fetch position-specific league averages. Center avg ~10.5 reb/g, PF ~7.5, SF ~5.5, SG ~4.0, PG ~3.5. Compute opponent adjustment relative to position average, not league total.

### 3. Pace Dependency (Ignored for Rebounds)
**What it is:** A team playing at 105 possessions/game generates more total rebounds than a team at 95 possessions/game. A player on a fast-paced team against a slow-paced opponent will see fewer total boards than his season average suggests.
**The model ignores pace entirely.** This is a primary driver of why rebounds are 34.2% vs a synthetic line: the model's projection doesn't adjust for pace mismatch, so actual rebound totals vary more than the model expects.
**Fix:** Multiply the projection by `(harmonic_mean_pace / player_team_pace)` where `harmonic_mean_pace` is the expected pace of the specific matchup. NBA API provides pace via `LeagueDashTeamStats` with `MeasureType=Advanced`.

### 4. Game Script Dependency
**What it is:** Rebounds are context-dependent in ways points and assists aren't. If a team blows out the opponent, bench players get the final 8 minutes and the starters' rebound counts drop. If a game is close, starters play 38+ minutes and get more opportunity.
**Why this is worse for rebounds than points:** A player in garbage time still gets some points from free throws and mid-range shots. A player on the bench gets zero rebounds. The volatility is asymmetric.
**The model uses std_dev to capture variance, but std_dev is symmetric.** Actual rebound distributions have negative skew due to blow-out scenarios.
**Practical fix:** Increase the rebound standard deviation floor from 1.0 to 1.5 (rebounds have higher game-to-game variance than points or assists). Consider using RMSE against recent games rather than stdev of values.

### 5. The "Rebound Projection Always High" Pattern
**Root cause identified from the 34.2% hit rate:** If projections are biased high and synthetic lines equal the projection, actual < projection more often than not. This means the model systematically overprojects rebounds.
**Mechanism:** The weighted average gives 50% weight to the last 5 games. If a player had 3 high-rebound games in their last 5 (e.g., playing against weak front courts), the projection is inflated. The next opponent may be a strong rebounding team — but the only adjustment is ±15% for team rebound rate.
**Fix:** Introduce regression to the mean. After computing the weighted rolling avg, blend it 70/30 with the player's season average. This prevents hot-streak inflation.

### 6. Minutes Variability Not Propagated
**What it is:** The `_MIN_MINUTES: int = 20` filter correctly excludes DNP games. But a player who plays 22 minutes in one game and 36 in another produces vastly different rebound totals — and both games pass the filter equally.
**The model treats a 22-minute game the same as a 36-minute game when computing averages.** Rebounds are highly minutes-dependent.
**Fix:** Use per-36-minute normalized stats rather than raw counts for the projection, then multiply back by expected minutes. Expected minutes = rolling average of qualifying games' minutes.

---

## Backtest Validity Issues

### 1. Synthetic Line = Own Projection Produces a Meaningless Baseline
As established above: the 43.5% number from the March 11 walk-forward is not a valid quality signal. Every test comparing actual > model_projection will converge to 50% for an unbiased model. The baseline is only useful for measuring directional bias (systematic over-projection → below 50%, systematic under-projection → above 50%).

**What validate_picks.py actually measures:**
- If hit rate is 43.5%: model is systematically biased HIGH (overprojects) for the tested stats. The model's mean is above the actual median outcome. This is useful info, but it's not the same as "accuracy."
- If hit rate were 56%: model is slightly biased LOW. Also useful, but not proof of sportsbook-beating edge.

**To get a meaningful number:** Need real sportsbook lines. Odds API `fetch_props()` provides this. Compare model_prob to the line actually offered, not the model's own line.

### 2. One Day of Games = ~70 Props = Statistically Noisy
**Sample size math:**
- One full NBA slate: ~9 games × ~8 qualifying players × 4 stats = ~288 prop opportunities
- After filtering (MIN minutes, MIN games, qualifying): ~70-80 rows
- Standard error of a proportion at n=75: `sqrt(0.5*0.5/75)` = 5.8%
- A 55% hit rate vs 50% baseline has a z-score of `(0.55-0.50)/0.058 = 0.86` — not statistically significant
- Need ~400 props (≈6 game days) to detect a 5% improvement at p<0.05

**Implication:** Do not make algorithm decisions based on one day of validation. The March 11 43.5% could easily be 45%-50% with 10 more game days. Tune the model first, then validate across a multi-week window.

### 3. Walk-Forward Requires True Pre-Game Snapshot
**The correct protocol (implemented in `_run_mar11_live_validation`):**
```python
pre_logs = [g for g in logs if str(g.get("GAME_DATE", ""))[:10] < TEST_DATE]
```
This is correct. But the cache-based validation (`_run_mar11_cache_validation`) is less clean — it assumes the mar-11 cache was built before the game, which is true only if you ran the scanner before tip-off. If the cache was built post-game, the mar-11 actual result is baked into the "pre-game" history.

**Risk:** Never re-run the scanner on the same day as the validation date after games have been played. The cache will include the game result in the "pre-game" logs, inflating accuracy.

### 4. Player Filtering Bias
**What it is:** The `_MIN_GAMES: int = 5` filter removes players with fewer than 5 qualifying games. These tend to be injured returners, recent callups, and traded players — exactly the players whose props are hardest to predict.
**The effect:** The backtest only measures the easy-to-predict players (stable veterans), making the model look better than it performs on the full scanner output, which includes difficult cases.
**Fix:** When reporting hit rates, segment by games_used (5-10 games vs 10-15 vs 15+). The 15+ group should be better calibrated. The 5-game group is mostly noise.

### 5. The Confidence Filter Fallacy
**What it is:** Reporting only HIGH-confidence picks and claiming that hit rate proves the model works.
**Why it fails:** HIGH confidence is defined as `|model_prob - market_implied| > 0.08`. If market_implied is always ~0.50 (−110 both sides), then HIGH confidence = model_prob > 0.58 or < 0.42. This just filters for extreme projections, not accurate ones.
**Observed in this codebase:** When the scanner outputs 95%+ confidence picks (Trae Young pts at 98.4%), those are almost certainly cases where the line is trivially low and the market already corrected — not genuine model edge.

---

## When to Stop Tuning

### 1. The "Overfitting Ratchet"
Every time you tune a parameter to improve a specific backtest, you risk fitting noise. The rebound cap at ±15% is already one tuned parameter. Adding opponent REB weight, pace adjustment, position normalization, and per-minute normalization creates 4-5 more knobs. Each additional knob narrows the signal and fits historical noise.

**Stop tuning when:** You've added a parameter and it improves the March 11 backtest but you can't articulate WHY it should generalize (i.e., the reason is domain knowledge, not "it fit the data better").

### 2. The Three-Day Rule
Run the model live for 3 consecutive game days without any changes. Record the picks, validate the next day. If hit rate is still below 50% on real sportsbook lines after 3 days, the problem is structural (wrong data, wrong signal) — not a tuning problem. Changing parameters won't fix it.

### 3. Validation Set Holdout
Before implementing any changes, designate March 6-10 game data as the holdout (never tuned against). Tune only on March 11 cache data. Validate on the March 6-10 holdout. If a change improves March 11 but hurts March 6-10, it's overfitting.

### 4. Ship When: Calibration Is Within 5%
The model is ready when: for props where model_prob is 60-70%, actual hit rate is 55-65% on real lines over 200+ sample props. Perfect calibration is not the goal. Within-5% calibration is the signal to ship.

### 5. Never Tune Away All Predictions
**Anti-pattern:** Tightening filters (confidence floor, MIN_GAMES, opp_adj_cap) until only 2 picks survive per day. Those 2 picks may look "safe" but you've eliminated your sample size entirely. A model that outputs 2 picks/day needs 200 days to validate.

---

## Phase-Specific Warnings

### Phase 1: Data Fixes (Season, Cache Invalidation)
- **Pitfall:** Assuming the cache is clean. Always delete `data/.prop_cache/` after any season-year change.
- **Pitfall:** Not verifying the nba_api returns 2025-26 data. Log the first row of any fetch and confirm `SEASON_YEAR` field.
- **Pitfall:** `_run_mar11_cache_validation()` uses cached .pkl files that may have been built with wrong season data. Treat all pre-existing cache files as suspect.

### Phase 2: Algorithm Changes (Weighted Avg, Opponent Adjustment)
- **Pitfall:** Tuning weights (0.5/0.3/0.2) against synthetic lines. Any change you observe is fitting noise because the baseline is meaningless. Tune weights only against real lines from Odds API.
- **Pitfall:** Adding per-minute normalization will shift all projections down (players don't always play 36 min). This will make confidence scores look worse. That's correct — it's removing false confidence, not breaking the model.
- **Pitfall:** The opponent rebound adjustment uses `opp.get("reb_pg")` which is the opponent's own rebounds per game. This is confounding offense and defense. Fix this before any other rebound tuning — if the adjustment direction is wrong, tuning the cap only makes it worse.

### Phase 3: Validation Against Real Lines
- **Pitfall:** Treating the Odds API response as ground truth for the line. Props lines have juice (−110 to −120). The "fair" line implied by −110 juice is that over/under each has 52.4% implied probability. A model that outputs 52.5% "HIGH edge" is within the vig — not a real edge.
- **Pitfall:** Sample size. 1 day = ~70 props. Statistical significance requires 300-400 props. Don't tune based on 1-day live validation.
- **Pitfall:** Selection bias in validation. The scanner only outputs players where the model found data. Players it skipped (no data → None return) are excluded. If those players systematically perform differently (rookies, injured returners), the validated hit rate overstates real-world performance.

### Phase 4: Production / SGP Construction
- **Pitfall:** Treating correlated props as independent. If Trae Young AST and Trae Young PTS are both in a parlay, their outcomes are correlated — a hot game boosts both. The parlay hit rate is not `P(ast) * P(pts)`.
- **Pitfall:** Kelly criterion on uncalibrated probabilities. If model_prob = 0.85 but real hit rate is 0.55, Kelly will recommend massive over-sizing. Always use fractional Kelly (0.25x) until calibration is proven.
- **Pitfall:** Category concentration (3 rebound props in one parlay). Rebounds are team-game-state dependent. Three rebound props all fail if the game blows out early. They're correlated through the blowout scenario even for players on different teams.

---

## Summary: The 5 Things That Kill NBA Prop Models

| Rank | Mistake | Kill mechanism |
|------|---------|---------------|
| 1 | Synthetic lines (testing model vs own projection) | Produces meaningless baseline, can't detect real edge |
| 2 | Wrong season data in cache | Projects from entirely wrong player state |
| 3 | Opponent rebound adjustment direction wrong | Systematic bias baked into every reb prediction |
| 4 | No pace adjustment for rebounds | High-variance residuals destroy hit rate |
| 5 | Tuning on 1 game day | Any parameter change that "works" is pure noise |
