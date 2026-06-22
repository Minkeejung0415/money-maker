# Phase 20 Context

## Why This Phase Exists

The fixed tactical layer was evaluated chronologically on 35 completed 2026 World Cup matches. It changed 1X2 accuracy from 60.0% to 57.1%, Over 2.5 accuracy from 65.7% to 62.9%, and left BTTS accuracy at 60.0%. It produced only tiny Brier/log-loss improvements for 1X2 and totals while making BTTS probability quality worse. That is not enough evidence to deploy hand-set weights.

## Locked Decisions

- This work belongs to a new v1.7 milestone, not a reopening of archived v1.6.
- Primary optimization target is probability quality: Brier score and log loss. Accuracy is secondary because threshold flips can hide or exaggerate calibration changes.
- The existing no-tactics model is the production fallback.
- Tactical markets are promoted independently. Evidence for 1X2 never authorizes totals or BTTS.
- The current World Cup matches remain an untouched final holdout.
- Missing, incompatible, undersized, or unvalidated artifacts fail closed.

## Technical Direction

- Learn tactical influence as a residual conditional on existing baseline probabilities and goal rates, limiting double counting with Elo and recent form.
- Keep the seven explainable component names, but use strong L2 shrinkage and chronological hyperparameter selection.
- Fit outcome residuals separately from goal-rate residuals. Derive totals and BTTS from the coherent scoreline distribution.
- Retain the current tactical Elo and goal-multiplier bounds.
- Use only information available before kickoff for every training and validation row.

## Agent Discretion

- Exact regularization grid, bootstrap method, and calibration-bin count.
- Whether score-state bias is handled through exclusions, control features, or both, provided the choice is documented and tested.
- Exact artifact serialization format, provided it is deterministic, versioned, human-auditable, and schema checked.

## Deferred

- Paid event or tracking data.
- Player-level tactical effects.
- Formation-only prediction rules.
- Betting thresholds or bankroll sizing; this phase evaluates probabilities, not staking.
