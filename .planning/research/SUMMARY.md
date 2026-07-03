# Research Summary: v2.4 WC Hybrid Route Offset

## Recommendation

Build route-offset as a bounded adapter over the current WC hybrid baseline. The hybrid model remains the production prior; projected-XI and tactical-duel data may only move route-level expected goals, then scoreline-derived markets are regenerated from the adjusted lambdas.

## Architecture

- Keep baseline hybrid lambdas and probabilities visible.
- Add role-strength snapshots for GK, CB, FB, DM, winger, and striker.
- Evaluate a small set of tactical duel rules: wing isolation, aerial/set-piece mismatch, press-vs-build.
- Convert duel outputs into capped route deltas for center, wing, set-piece, and counterattack xG.
- Recompute scoreline, BTTS, O/U2.5, WDL, and advance probabilities from adjusted lambdas.
- Log all deltas, cap hits, missing roles, and shrinkage in scanner output.

## Validation Standard

Promotion requires paired validation versus the current hybrid baseline on the same fixtures:

- Brier score
- Log loss
- Calibration
- Selective hit rate where relevant
- BTTS probability quality
- O/U2.5 probability quality
- Coverage and missing-data diagnostics

## Key Decision

Do not model player and tactical data as raw WDL inputs. Model them as explainable route-xG offsets so the scoreline engine stays coherent and the existing hybrid calibration is not casually discarded.

## Roadmap Implication

The milestone should be split into five phases:

1. Contracts and baseline harness
2. Role-strength/projected-XI runtime inputs
3. Tactical duel engine
4. Route xG integration and shadow scanner output
5. Paired validation, promotion gates, and UAT readiness
