**For practical NBA player prop prediction, Bayesian updating with exponential decay weighting is the best default approach; formal change-point detection and regime-switching models are theoretically superior but face severe sample-size constraints that limit their real-time utility for individual players.**

This question sits at a fascinating intersection where the statistical literature is rich but the sports-specific applications are sparse. Let me synthesize what's available.

## The Non-Stationarity Problem in NBA Data

NBA player performance is non-stationary in at least four distinct ways, each with different statistical signatures:

1. **Hot/cold streaks** (within-game and across games): autocorrelated success probabilities
2. **Role changes** (trade, lineup shift, new coach): abrupt mean shifts in usage, minutes, shot distribution
3. **Injury recovery curves**: gradual non-linear return to baseline
4. **Seasonal aging/decline**: slow drift over multi-year timescales

Sun & Wang (2012) argued that the hot hand debate itself is fundamentally about non-stationarity: "nonstationarity may manifest as a residual effect when the changes in shooting accuracy are interrupted by activities such as shot selection and defense effort." <citations>0</citations> This framing is critical — many methods designed to detect streaks have low power precisely because the non-stationarity is masked by confounding game dynamics.

## Method-by-Method Assessment

### 1. Bayesian Hidden Markov Models (Regime-Switching)

Calvo, Armero & Spezia (2024) developed a Bayesian longitudinal hidden Markov model specifically to examine the hot hand phenomenon in consecutive basketball shots. Their model defines latent "hot" and "cold" states with different success probabilities and transition matrices, estimated via MCMC. <citations>1</citations> This is the most theoretically rigorous approach to modeling performance regimes.

Hamaker & Grasman (2012) applied regime-switching state-space models to psychological processes including "shifts between a 'hot hand' and a 'cold hand' in a top athlete," using Kim's (1994) algorithm for joint estimation of latent states and model parameters. <citations>2</citations>

Bendtsen (2017) used gated Bayesian networks to represent performance regimes in baseball players' careers and found that "baseball players do indeed go through different regimes throughout their career, where each regime can be associated with a certain level of performance." Some transitions aligned with trades or injuries, but others had no observable cause. <citations>3</citations> This is a key insight for prop modeling: not all regime changes are detectable from external signals.

The limitation: HMMs require substantial data per player to reliably estimate transition probabilities. With ~82 games per season and high game-to-game variance, the model often cannot distinguish a genuine regime shift from random fluctuation until many games after the shift occurred.

### 2. Change-Point Detection

Glazer (2025) developed tractable changepoint detection algorithms for player performance metrics, applied to MLB batting and pitching data. The method combines likelihood-based detection with split-sample inference to control false positives, and incorporates a shift parameter allowing users to specify the minimum magnitude of change to detect. <citations>4</citations> This is the most directly relevant methodological work.

Yung et al. (2022) demonstrated change-point detection for return-to-sport rehabilitation, noting that "the CP approach holds promises for informing clinicians the rate of progression in rehabilitation" — directly analogous to modeling injury recovery curves. <citations>5</citations>

Yang (2004) proposed a Bayesian binary segmentation procedure specifically for detecting streakiness in sports, using nested hypothesis tests with Bayes factors to locate changepoints and estimate associated success rates simultaneously. <citations>6</citations>

Change-point detection's main advantage is that it formally identifies *when* a shift occurred. Its disadvantage for real-time prop prediction is latency: you need several post-change observations to detect the change with confidence, and by then the betting market may have already adjusted.

### 3. Continuous-Time State-Space Models

Mews & Ötting (2020) investigated the hot hand using data on 110,513 NBA free throws with a continuous-time state-space model based on the Ornstein-Uhlenbeck process. Their results "support the existence of the hot hand, but the magnitude of the estimated effect is rather small as the underlying success probabilities are elevated by only a few percentage points." <citations>7</citations>

This is a crucial quantitative finding for prop bettors: even when hot/cold streaks are statistically real, the effect size is small enough (~2-5 percentage points on shooting) that it may not create exploitable edge after accounting for the vig.

### 4. Bayesian Updating / Dynamic Priors

Song & Shi (2020) developed a gamma process model for NBA scoring processes with a Bayesian dynamic forecasting procedure that "utilizes the in-match information to update the scale parameter of the model as the match progresses." <citations>8</citations> Williams et al. (2024) proposed "Expected Points Above Average" using a Bayesian hierarchical framework where players are clustered based on shooting propensities and abilities using posterior predictive distributions. <citations>9</citations>

Bayesian updating's practical appeal is that it naturally handles the bias-variance tradeoff: a strong prior (season average) stabilizes predictions early, while observed data gradually shifts the posterior as evidence accumulates. This is essentially what exponential decay weighting does, but with a principled probabilistic framework.

### 5. Exponential Decay Weighting

Exponential decay is the implicit regime-adaptation mechanism in most production models. It doesn't detect regimes — it just weights recent data more heavily, which provides a smooth, continuous adaptation to any kind of non-stationarity. Jacobs (2011) studied adaptation to non-stationarity using growing predictor ensembles and noted that in non-stationary settings, "the best we can hope to do is bound regret" rather than expected loss. <citations>10</citations> Rosenfeld et al. (2016) found that their exponential decay prediction algorithm provided up to 41% improvement over classic time-series methods on non-stationary data. <citations>11</citations>

## Head-to-Head Comparison

| Method | Regime Detection | Adaptation Speed | Sample Efficiency | Implementation Complexity | Best Use Case |
|---|---|---|---|---|---|
| Exponential decay | None (implicit) | Moderate (tunable $$\alpha$$) | Excellent | Very low | Default baseline for props |
| Bayesian updating | None (smooth posterior) | Moderate-fast | Good | Low-moderate | Player-level priors + updating |
| Change-point detection | Explicit, delayed | Slow (detection lag) | Poor for individuals | Moderate | Post-hoc analysis; detecting trades/injuries |
| HMM / regime-switching | Explicit regimes | Fast once detected | Poor for individuals | High | Multi-season career modeling |
| Ornstein-Uhlenbeck state-space | Continuous latent state | Moderate | Moderate | High | Research; shooting % modeling |

## The Crux: Sample Size

The fundamental tension is between statistical sophistication and data scarcity. A single NBA player generates ~82 data points per season for counting stats. Formal change-point detection requires roughly 15-20 observations *after* a change to detect it reliably. An HMM needs hundreds of observations to estimate transition probabilities well. Meanwhile, exponential decay weighting works game-by-game from the first observation.

This is why exponential decay dominates in practice despite being the least theoretically interesting method. It's not that regime-switching models are wrong — they're right about the structure of the data. It's that they can't be estimated precisely enough from individual player samples to improve real-time predictions.

## Practical Recommendation

The best approach for a production prop model combines elements:

1. **Exponential decay as the core mechanism**: Use a weighted average with $$\alpha \approx 0.1$$–$$0.2$$ (half-life of 5–7 games) for your recency features
2. **Bayesian shrinkage toward a prior**: Anchor predictions to a season/career baseline with a mixing parameter that decreases as the season progresses and you accumulate more data
3. **External signal detection for role changes**: Don't rely on statistical change-point detection to discover that a player got traded — detect that *exogenously* (from news/transaction data) and reset your priors accordingly
4. **Monitor for drift**: Track your model's rolling prediction error per player; if it spikes, flag the player for manual review rather than trying to auto-detect the regime change statistically

The formal methods (HMM, change-point detection) are better suited for *post-hoc* analysis — understanding a player's career trajectory, identifying when a decline began, studying injury recovery curves — than for real-time prediction with an 82-game sample.