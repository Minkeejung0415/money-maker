**Gradient-boosted trees (XGBoost/LightGBM) remain the pragmatic best choice for NBA player prop prediction; deep learning architectures offer marginal or no improvement on tabular game-log data, though they unlock value when modeling player interactions or spatiotemporal sequences.**

This is a question where the academic evidence, practitioner experience, and ML theory all converge on the same answer — but with important nuances about *when* deep learning earns its complexity cost.

## Deep Learning vs. Gradient Boosting: The Core Comparison

The most directly relevant study is Campbell & Khan (2025), who benchmarked a compact transformer against a 128-unit LSTM for forecasting NBA player stat-lines from 10-game windows. The transformer cut mean absolute error by 18% versus the LSTM baseline, demonstrating that attention mechanisms capture game-to-game dependencies better than recurrent architectures for this task. <citations>0</citations> However, neither paper compared against gradient-boosted trees — a telling omission.

Rios et al. (2025) built an LSTM architecture trained on 20 seasons of NBA data (9,840-game sequences) for game outcome prediction and found that long-sequence LSTM addresses concept drift across seasons. <citations>1</citations> Nguyen et al. (2021, 51 citations) applied both traditional ML and deep learning to NBA player performance prediction and found that deep learning offered incremental improvements but was not dramatically superior for tabular statistical features. <citations>2</citations>

A hybrid RNN-LSTM architecture by Kumari et al. (2025) claims improved results over Ridge Regression, Gradient Boosting, and SVR for player performance evaluation, arguing that temporal dependencies in sequential game data justify the added complexity. <citations>3</citations> Chen (2025) proposed a Transformer-LSTM hybrid for athlete performance forecasting across sports and reported strong results, but on biometric data (heart rate, speed, workload) rather than box-score statistics. <citations>4</citations>

The practical reality, well understood in the ML community but underrepresented in sports-specific publications: on structured/tabular data with <100 features, gradient-boosted trees consistently match or beat deep learning. The XGBoost time-series approach described by Rangarajan (2025) — using lagged features, rolling averages, and engineered interaction terms — is the dominant production architecture for player props. <citations>5</citations>

## When Deep Learning Adds Genuine Value

Graph neural networks are the most promising deep learning approach for basketball specifically, because they can model player interactions that tabular models cannot.

Luo & Krishnamurthy (2023) developed GATv2-GCN, a graph attention network with temporal convolution, to predict player performance by constructing dynamic player interaction graphs. The model captures how each player's output depends on who else is on the court. <citations>6</citations> Zhao et al. (2023) fused GCN with Random Forest for NBA game outcome prediction and achieved improved accuracy by representing inter-team interactions as graph structures — outperforming models that treated team statistics as flat vectors. <citations>7</citations> NBA2Vec (Guan et al. 2023) used a Word2Vec-inspired network trained on 3.5M plays to learn dense player embeddings that encode lineup context, achieving 0.3 KL-divergence from empirical play distributions. <citations>8</citations>

The key insight: GNNs and embedding approaches add value specifically because they encode *who is on the court together* — something flat feature vectors can't naturally represent. For a player prop model, lineup-aware embeddings as *input features* to a GBT model may be the best of both worlds.

## Input Feature Architecture

Nguyen & Nguyen (2020, from prior search) used the transformer's self-attention mechanism to treat each player as a vector of statistics and learn relationships between players, finding results comparable to simpler models (smoothed L1 loss ~10.10). <citations>9</citations> Ahmadalinezhad et al. (2019) used network analysis to model lineup performance, demonstrating that lineup context (who plays together) significantly affects prediction quality. <citations>10</citations>

The feature hierarchy for player props, ranked by predictive contribution:

| Feature Category | Architecture Fit | Why It Matters |
|---|---|---|
| Time-series game logs (rolling stats) | GBT or LSTM | Core signal; 5-10 game weighted windows capture form |
| Matchup/opponent data (DRTG, pace) | GBT (multiplicative adjustments) | Moderate lift; noisy on small samples |
| Lineup context (who's on court) | GNN embeddings → GBT | Captures usage shifts from roster changes |
| Spatiotemporal tracking data | Transformer/LSTM | Highest ceiling but requires tracking data access |

## Optimal Training Window

Training window size is under-studied in sports-specific literature, but general findings from time-series ML are directly applicable. Yao et al. (2025) found that under concept drift (which NBA data exhibits due to rule changes, pace shifts, roster turnover), expanding training windows can actually *degrade* performance once concept shift is present. <citations>11</citations> Petersen et al. (2026) showed that even computing a simple average across different window sizes reduces prediction error versus selecting a single fixed window. <citations>12</citations> Skabar & Cloete (2003) demonstrated that dynamically adjusting window sizes based on recent trends outperforms static windows for financial prediction with neural networks. <citations>13</citations>

For NBA player props specifically, the practitioner consensus converges on:
- **Lookback context window:** 5–10 games for recency features (form, fatigue)
- **Training data:** 1–2 seasons of game logs for model fitting (roughly 82–164 games per player)
- **Retraining cadence:** Monthly or after significant roster changes
- **Multi-season data:** Useful for learning general patterns (position effects, pace adjustments) but should be down-weighted relative to current season

Campbell & Khan (2025) specifically used 10-game windows as input context and found this optimal for their transformer architecture. <citations>0</citations> Khalifeh & AlMeqdadi (2024) found that larger windows generally improve LSTM performance on time-series prediction by capturing temporal dependencies, while CNNs perform better with smaller windows. <citations>14</citations>

## Practical Recommendation

For a production NBA player prop model: use XGBoost or LightGBM as your primary architecture with 10–15 engineered features including rolling weighted averages, opponent adjustments, and rest/schedule context. If you want to incorporate lineup context, train player embeddings separately (via GNN or NBA2Vec-style approach) and feed them as additional features to the GBT. Reserve LSTM/Transformer architectures for situations where you have access to tracking data or need to model sequential play-by-play dynamics. The marginal accuracy gain from deep learning on standard box-score features does not justify the engineering and maintenance overhead for most use cases.