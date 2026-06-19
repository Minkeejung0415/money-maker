# Requirements: v1.2 — Draw Algorithm

## Milestone Goal

Replace the flat 25% draw rate with a match-strength-dependent draw probability calibrated to historical WC group-stage data.

## Active Requirements

### Draw Probability

- [ ] **DRAW-01**: Model computes draw probability as a function of |Elo difference| for group-stage games, not a flat constant — so Spain (Δ745) and Scotland (Δ54) get materially different draw rates
- [ ] **DRAW-02**: Draw probability is calibrated to historical WC group-stage draw rates by Elo band (Δ<100 → ~30%, Δ200-400 → ~18%, Δ>500 → ~8%), using an exponential decay or equivalent formula
- [ ] **DRAW-03**: Knockout round behavior unchanged — p_draw = 0.0 always regardless of Elo difference

### Testing

- [ ] **TEST-01**: Parameterized tests cover draw probability output at multiple representative Elo difference values (Δ=0, Δ=100, Δ=300, Δ=500, Δ=750); all 619 existing tests pass with zero regressions

## Future Requirements

- Dynamic draw calibration using live WC 2026 result feed (after tournament closes)
- WC player props pipeline (deferred to v1.3 — requires Odds API Business tier)

## Out of Scope

- EPL/UCL draw model changes — WC-only scope
- NBA/MLB changes — no cross-vertical impact
- New data sources — uses existing Elo priors only

## Traceability

| REQ-ID  | Phase | Plan |
|---------|-------|------|
| DRAW-01 | TBD   | TBD  |
| DRAW-02 | TBD   | TBD  |
| DRAW-03 | TBD   | TBD  |
| TEST-01 | TBD   | TBD  |

---
*Last updated: 2026-06-18 — v1.2 requirements defined*
