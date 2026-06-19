# MLB Win Probability Research Summary

## Recommendation

Build a leakage-safe, time-ordered MLB game dataset and benchmark a calibrated logistic model against a calibrated gradient-boosted model. Ship the model with the best untouched future-window Brier score/log loss, not the model with the flashiest training accuracy.

## Reuse

The repository already contains the runtime `MLBModel`, daily fixture ingestion, team/pitcher statistic readers, scanner integration, and probability evaluation utilities. The missing pieces are a reproducible historical dataset builder, trainer, calibration/evaluation pipeline, and validated artifact.

## Release Gate

- Every feature is demonstrably available before first pitch.
- Train, calibration, and test windows are chronological and disjoint.
- The chosen model beats 50/50 and historical home-win baselines on Brier score and log loss.
- Reliability buckets are reported with adequate sample counts.
- Artifact metadata records schema, dates, metrics, and model version.
- Scanner refuses silent 50/50 output and labels fallback/unvalidated states clearly.

## Scope

Game-level home/away win probabilities and fair odds only. Manual sportsbook odds may be compared after modeling, but paid feeds, props, and parlays remain deferred.
