# Research: Stack Fit for WC Hybrid Route Offset

## Scope

v2.4 should extend the current World Cup hybrid model without replacing it. The route-offset layer should sit between baseline team lambdas and scoreline probability generation, so existing WDL, BTTS, totals, SGP, artifact, and fallback contracts remain understandable.

## Existing Stack Signals

- Runtime entry point: `scripts/wc_scanner.py`
- Core WC probability logic: `alpha/engines/sports/wc_model.py`
- Hybrid/runtime model selection: current scanner supports explicit `elo`, `hybrid`, `player`, and `auto` behavior with fallback labels.
- Current route-adjacent outputs: scoreline lambdas, BTTS, over/under 2.5, WDL, advance probabilities.
- Existing safety pattern: fail-closed model identity, artifact metadata, source labels, uncertainty flags, and shadow output already exist elsewhere in the repo.

## Recommended Stack Shape

- Add a small route-offset module rather than folding tactical/player logic directly into WDL.
- Keep the current hybrid output as the production prior.
- Represent player and tactical inputs as typed runtime snapshots, not loose kwargs.
- Emit diagnostics as structured JSON-friendly fields so scanner text and future grading can share the same source.
- Store offset caps and rule weights in versioned config or artifact metadata, not hidden constants.

## Validation Fit

Use paired comparisons against the same fixtures:

- Baseline hybrid probabilities
- Route-offset shadow probabilities
- Delta by market: WDL, BTTS, O/U2.5, expected goals
- Probability-quality metrics: Brier, log loss, calibration
- Coverage diagnostics: projected XI completeness, missing roles, cap hits

## Decision

The route-offset stack is compatible with the repo if it is implemented as a bounded pre-scoreline adjustment layer and kept in shadow mode until paired validation proves it improves probability quality.
