This is a multi-part question that sits at the intersection of sports analytics and ML engineering. I'll address each sub-question drawing from both academic research and practitioner evidence. A caveat up front: there is no peer-reviewed literature specifically studying NBA *player prop* prediction feature engineering in a controlled experimental setting. Most evidence comes from team-level game outcome prediction studies and practitioner projects, with general ML dimensionality principles filling the gaps.

## Optimal Feature Count

The convergent finding across NBA prediction studies is that a small, curated feature set (roughly 5–15 features) outperforms large feature sets. Zhao et al. (2024) tested K-means clustering for feature selection on NBA game prediction and found peak accuracy of 78.6% with K=4 clusters and just 5 top features per cluster — outperforming both PCA and LASSO-based reduction. <citations>0</citations> This aligns with a general dimensionality reduction study by Głowania et al. (2023), which found that reduced feature sets allowed "equally effective classification" in sports performance prediction while improving model interpretability. <citations>1</citations>

For player-level props specifically, practitioner models converge on 10–20 engineered features. A portfolio project by Dawkins built a player prop engine for points, rebounds, and assists using opponent defensive rating, home/away splits, back-to-back fatigue, minutes trends, pace of play, and season-over-season evolution. <citations>2</citations> The BettorEdge guide similarly identifies usage rate, target share, pace, and matchup-specific adjustments as the highest-signal features. <citations>3</citations>

The key principle: adding features beyond ~15–20 for a per-player regression model almost always degrades out-of-sample performance due to overfitting, especially given the small effective sample sizes (a player has ~82 regular season games).

## Rolling Weighted Averages vs. Simple Moving Averages

Weighted moving averages generally outperform simple moving averages for time-series forecasting — this is a robust finding across domains. Ekhosuehi & Dickson (2016) found that exponential weighted moving averages performed best among moving average variants when all models were compared on out-of-sample forecast performance. <citations>4</citations> A 2026 production forecasting study confirmed that WMA achieved lower MAPE than SMA across multiple period lengths. <citations>5</citations>

For NBA player props, the reasoning is straightforward: a player's performance 3 games ago is more informative than 15 games ago due to fatigue, form streaks, lineup changes, and injury recovery. Practitioner models typically use exponentially decayed weights with a 5–10 game recency window as the core feature, supplemented by a longer-horizon season average (often weighted ~60% season / ~40% recent form). <citations>6</citations> The magnitude of improvement over SMA is modest — typically 1–3% in MAPE — but consistent.

## Opponent Defensive Adjustments

Opponent-level adjustments improve out-of-sample accuracy, but the gain is smaller than most modelers expect and comes with overfitting risk. Aryan & Sharafat (2014) demonstrated that incorporating opposing team data improved prediction error rates for NBA game outcomes. <citations>7</citations> Yao et al. (2018) identified defensive field goal percentage and points per game allowed as the most significant interaction terms in their NBA winning percentage model (R² > 95%). <citations>8</citations> South (2024) showed that using Bayesian hierarchical models with modern positional clustering for defensive efficiency estimation produced modest improvements in RMSE for team-level predictions. <citations>9</citations>

For player props, the most useful opponent features are:
- Opponent defensive rating (points allowed per 100 possessions)
- Pace (possessions per game — this directly affects counting stats)
- Position-specific defensive matchup data

The risk is that opponent defensive metrics are noisy on small samples and can introduce more variance than signal, especially early in the season. A practical rule: use rolling 15–20 game opponent defensive averages rather than season-long or short-window metrics, and keep these as multiplicative adjustments (pace multiplier, matchup factor) rather than raw features.

## Feature Importance Hierarchy

Park et al. (2025) used Random Forest, Gradient Boosting, and XGBoost across 23 years of NBA data to identify feature importance for team winning, finding that the top predictors shifted across eras — but shooting efficiency and turnover rate consistently ranked highest. <citations>10</citations> For individual player props, the practitioner consensus on feature importance roughly ranks as:

1. Minutes played / projected minutes (overwhelmingly the top predictor for all counting stats)
2. Usage rate / shot attempts per minute
3. Recent rolling averages (weighted, 5–10 game window)
4. Season average (baseline)
5. Pace of play (team + opponent)
6. Home/away indicator
7. Rest days / back-to-back flag
8. Opponent defensive rating (position-specific when available)

## Dimensionality Reduction Approaches

PCA is commonly applied but often underperforms targeted feature selection for prediction tasks. Bruce (2015) used PCA on NBA tracking data and found 4 principal components explaining 68% of variance — useful for player comparison and clustering but not necessarily optimal for prediction. <citations>11</citations> Yahyasoltani et al. (2021) found that PCA produced a smaller feature set with higher information content for predicting basketball player efficiency, and that position-specific models outperformed one-size-fits-all models. <citations>12</citations>

The practical recommendation for prop models: use embedded feature selection (L1 regularization, tree-based importance) rather than PCA. PCA destroys interpretability and doesn't guarantee the retained components are the most *predictive* ones — they're the most *variable* ones, which is a different thing.

## Summary

For NBA player prop prediction: use 10–15 carefully engineered features; prefer exponentially weighted rolling averages over SMA (5–10 game window); include opponent pace and defensive rating as multiplicative adjustments but be cautious about overfitting to noisy opponent splits; and use embedded feature selection (LASSO, XGBoost importance) rather than PCA for dimensionality reduction. The single most important feature is projected minutes, and the single biggest source of overfitting is adding too many opponent-specific or situational features with insufficient sample sizes.