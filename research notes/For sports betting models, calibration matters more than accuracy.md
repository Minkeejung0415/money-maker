**For sports betting models, calibration matters more than accuracy 
nand isotonic regression is the most robust post-hoc calibration method for NBA prop prediction, though the choice depends on your sample size and model architecture.**

This is one of the few areas where there *is* a directly relevant published benchmark on NBA data. Let me walk through each method and what the evidence says.

## The Foundational Finding: Calibration > Accuracy for Betting

Walsh & Joshi (2023/2024) conducted the most directly relevant study, training models on NBA data over several seasons and running betting experiments using published odds. Their key finding: selecting models based on calibration rather than accuracy yielded dramatically better returns 
nROI of +34.69% vs. -35.17% for calibration-selected vs. accuracy-selected models in the average case, and +36.93% vs. +5.56% in the best case. <citations>0</citations> This is a striking result. A model that is 72% accurate but poorly calibrated (predicting 0.85 when the true probability is 0.72) will systematically misjudge edge, leading to overbetting on false value. A well-calibrated model identifies *when* its edge over the bookmaker's line is genuine.

## Comparing Calibration Methods

| Method | Best For | Strengths | Weaknesses |
|---|---|---|---|
| Platt Scaling | Neural networks, SVMs | Simple (2 params); works well on sigmoid-shaped miscalibration | Assumes logistic relationship; poor when miscalibration is non-monotonic |
| Isotonic Regression | Tree-based models (XGBoost, RF) | Non-parametric; captures arbitrary miscalibration shapes | Overfits on small calibration sets (<500 samples); can be non-smooth |
| Temperature Scaling | Deep learning classifiers | Single parameter; preserves accuracy; very fast | Only rescales confidence; can't fix non-uniform miscalibration across classes |
| Conformal Prediction | Prediction intervals for props | Distribution-free coverage guarantees; model-agnostic | Provides sets/intervals, not point probabilities; marginal not conditional coverage |

Guo et al. (2017, 7,275 citations) established the foundational result that modern neural networks are poorly calibrated and that temperature scaling 
nlna single-parameter variant of Platt Scaling 
nlis "surprisingly effective" as a post-hoc fix across most datasets. <citations>1</citations> However, this work was on image classification, not sports prediction. Biçici & Saribas (2023) compared isotonic regression, Platt scaling, neural networks, spline regression, and temperature scaling on CTR prediction (an imbalanced binary task similar in structure to sports betting) and found that isotonic regression improved calibration the most and was the fastest method. <citations>2</citations>

For NBA specifically, a large-scale scikit-learn calibration study found that decision trees and Naive Bayes are significantly overconfident out-of-the-box, while logistic regression and neural networks produce better-calibrated probabilities natively. Both Platt scaling and isotonic regression improved calibration, but the relative benefit depended on the base model and dataset. <citations>3</citations>

## NBA-Specific Calibration Evidence

Montrucchio et al. (2026) built a fully uncertainty-aware NBA forecasting framework using an RNN with Monte Carlo dropout, evaluated against XGBoost, logistic regression, CNN, and GRU baselines. They assessed calibration using ECE (expected calibration error) and MCE (maximum calibration error) alongside Brier score and log-loss. The uncertainty-aware model delivered "systematically better calibration than non-Bayesian baselines." <citations>4</citations> This suggests that for deep learning approaches, Bayesian uncertainty estimation (MC dropout) may be superior to post-hoc calibration for sports prediction.

Yeh, Rice & Dubin (2020) introduced calibration surface plots for evaluating continuously updated NBA win probability forecasts and found that ESPN's real-time forecasts were well-calibrated but did not demonstrate significantly improved skill over simple logistic regression models. <citations>5</citations> This reinforces that calibration is a necessary but not sufficient condition 
nlyou also need discrimination.

## Method Recommendations by Model Type

For GBT models (XGBoost/LightGBM) predicting player props, isotonic regression is the strongest choice. These models output leaf-node averages that can have arbitrary miscalibration shapes, and isotonic regression's non-parametric nature handles this well. The key practical constraint is sample size: you need a held-out calibration set of at least 500
to1,000 predictions to avoid isotonic regression overfitting. For a single player over one season (~82 games), this means you must calibrate across players, not per-player.

For neural network architectures, temperature scaling is the natural starting point 
nlit's effective, single-parameter, and preserves rank ordering. <citations>1</citations> Adaptive variants that learn per-sample or per-class temperatures show further improvements: Balanya et al. (2022, 43 citations) proposed entropy-based temperature scaling that scales confidence according to the relationship between prediction entropy and overconfidence, achieving state-of-the-art results robust to data scarcity. <citations>6</citations> Frenkel & Goldberger (2021) showed that calibration error differs across classes and proposed class-specific temperature scaling. <citations>7</citations>

## Conformal Prediction: A Different Tool for a Different Problem

Conformal prediction answers a different question than Platt scaling or isotonic regression. Rather than calibrating point probability estimates, it produces prediction intervals with guaranteed marginal coverage. For player props, this means: instead of predicting "LeBron scores 27.3 points," conformal prediction produces "LeBron scores between 19 and 35 points with 90% coverage."

Dabah & Tirer (2024) studied the interplay between temperature scaling and conformal prediction and found, surprisingly, that calibration has a *detrimental* effect on popular adaptive conformal prediction methods 
nlit frequently leads to larger prediction sets. <citations>8</citations> This means you should not naively stack calibration and conformal prediction; they can work against each other.

For player prop betting, conformal prediction is most useful for identifying *when not to bet* 
nlif the conformal interval is wide (high uncertainty), the expected value calculation is unreliable. The WagerProof guide recommends using reliability plots, Brier score, log loss, and ECE as core calibration metrics, with regular recalibration using Platt scaling or isotonic regression. <citations>9</citations>

## Practical Calibration Pipeline

1. Train your base model (XGBoost for props) on training data
2. Reserve a calibration set (~20% of data, chronologically held out)
3. Apply isotonic regression to the model's raw predictions on the calibration set
4. Evaluate with reliability diagrams, Brier score, and ECE on a test set
5. Recalibrate monthly 
nlcalibration drifts as the season progresses (Davis et al. 2017 showed calibration deteriorates over time even when discrimination is maintained) 
6. Use the calibrated probabilities to calculate expected value against the sportsbook line, and only bet when EV exceeds a threshold (typically 2
5%)

The Walsh & Joshi result bears repeating: this pipeline 
nlcalibration-first model selection 
nlis the difference between +35% ROI and -35% ROI on NBA betting. <citations>0</citations>