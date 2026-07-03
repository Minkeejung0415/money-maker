# Research: Architecture for WC Hybrid Route Offset

## Target Flow

1. Build baseline WC hybrid probabilities and lambdas.
2. Load projected-XI role-strength snapshot for the fixture.
3. Evaluate tactical duel rules with missing-data shrinkage.
4. Convert duel outputs into capped route-level xG deltas.
5. Recompose adjusted home/away lambdas.
6. Regenerate scoreline, BTTS, O/U2.5, WDL, and advance probabilities.
7. Emit baseline-vs-adjusted diagnostics in shadow mode.

## Route Model

Use four route buckets:

- Center
- Wing
- Set-piece
- Counterattack

Each duel rule may affect one or more buckets, but total team delta should be capped. A simple first implementation can use deterministic caps and weights, then later promote learned weights only after enough graded data exists.

## Promotion Gates

Route-offset output may affect production picks only when:

- Artifact/config identity is explicit.
- Role-strength schema matches runtime expectations.
- Shadow coverage is sufficient.
- Paired Brier/log loss does not regress.
- Calibration remains acceptable.
- Market-specific behavior for BTTS and O/U2.5 is not worse than baseline.
- Scanner can explain every non-zero offset.

## Failure Behavior

- If artifact/config missing: use hybrid baseline.
- If role snapshot missing: use hybrid baseline and label fallback.
- If coverage partial: shrink offsets and label missing roles.
- If caps hit too often: keep shadow-only and flag for tuning.

## Decision

The route-offset layer should be built as an explainable, fail-closed adapter around the existing hybrid model, not as a second model competing silently with it.
