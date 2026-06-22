# Phase 20 Context

## Why This Phase Exists

The fixed tactical layer was evaluated chronologically on 35 completed 2026 World Cup matches. It changed 1X2 accuracy from 60.0% to 57.1%, Over 2.5 accuracy from 65.7% to 62.9%, and left BTTS accuracy at 60.0%. It produced only tiny Brier/log-loss improvements for 1X2 and totals while making BTTS probability quality worse. That is not enough evidence to deploy hand-set weights.

## Locked Decisions

- This work belongs to a new v1.7 milestone, not a reopening of archived v1.6.
- Primary optimization target is probability quality: Brier score and log loss. Accuracy is secondary because threshold flips can hide or exaggerate calibration changes.
- The existing no-tactics model is the production fallback.
- Single tactical markets are promoted independently. Evidence for 1X2 never authorizes totals or BTTS. Every SGP combination must use one distribution; if all constituent market families are not approved on that distribution, the entire combination uses the no-tactics distribution.
- All eligible completed World Cup matches from 2026-06-11 through the frozen manifest creation cutoff remain a never-trained external audit. The manifest must contain at least 30 matches and cannot be appended in place; later tournament audits require a new version.
- Missing, incompatible, undersized, or unvalidated artifacts fail closed.
- Promotion requires at least 200 development matches plus 50 later pre-tournament chronological validation matches before the separate World Cup audit is examined.

## Technical Direction

- Learn tactical influence as a residual conditional on existing baseline probabilities and goal rates, limiting double counting with Elo and recent form.
- Keep the seven explainable component names, but use strong L2 shrinkage and chronological hyperparameter selection.
- Fit outcome residuals separately from goal-rate residuals. Derive totals and BTTS from the coherent scoreline distribution.
- Retain the current tactical Elo and goal-multiplier bounds.
- Use only information available before kickoff for every training and validation row.

## Agent Discretion

- Exact regularization grid and calibration-bin count. Bootstrap repetitions, interval level, multiplicity correction, and promotion deltas are locked below.
- Whether score-state bias is handled through exclusions, control features, or both, provided the choice is documented and tested.
- Exact artifact serialization format, provided it is deterministic, versioned, human-auditable, and schema checked.

## Deferred

- Paid event or tracking data.
- Player-level tactical effects.
- Formation-only prediction rules.
- Betting thresholds or bankroll sizing; this phase evaluates probabilities, not staking.
