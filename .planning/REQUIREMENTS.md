# Requirements: Alpha Terminal - WC Hybrid Route Offset

**Defined:** 2026-07-03
**Milestone:** v2.4 - WC Hybrid Route Offset
**Core Value:** Every prop line the scanner outputs must have a >55% historical hit rate; if the model cannot beat a coin flip, it is not worth betting.

## v2.4 Requirements

### Baseline and Runtime Contract

- [ ] **BASE-01**: WC route-offset runtime keeps the current hybrid model as the production prior.
- [ ] **BASE-02**: Route-offset output is available in shadow mode without affecting pick eligibility by default.
- [ ] **BASE-03**: Runtime output exposes requested model, active model, fallback status, fallback reason, and route-offset artifact/config identity.
- [ ] **BASE-04**: Missing, stale, or schema-mismatched route-offset inputs fail closed to the hybrid baseline.

### Role Strength Inputs

- [ ] **ROLE-01**: Event-level projected-XI snapshots provide role strengths for GK, CB, FB, DM, winger, and striker.
- [ ] **ROLE-02**: Role snapshots include source, update time, schema version, role coverage, missing roles, and uncertainty labels.
- [ ] **ROLE-03**: Missing or weak role coverage shrinks route offsets toward zero and is visible in scanner diagnostics.
- [ ] **ROLE-04**: Critical missing role data suppresses route-offset pick eligibility while still allowing research probabilities.

### Tactical Duel Engine

- [ ] **DUEL-01**: Tactical duel rules support wing isolation, aerial/set-piece mismatch, and press-vs-build interactions.
- [ ] **DUEL-02**: Duel outputs are explainable with active rule ids, contributing roles, direction, magnitude, and missing-data adjustments.
- [ ] **DUEL-03**: Duel effects are capped at both route and match levels to prevent implausible xG movement.
- [ ] **DUEL-04**: Rule/config identity is versioned so validation can reproduce the exact route-offset behavior.

### Route xG and Scoreline Integration

- [ ] **ROUTE-01**: Baseline home/away lambdas are decomposed or allocated into center, wing, set-piece, and counterattack route buckets.
- [ ] **ROUTE-02**: Route-level deltas recompose into adjusted lambdas before scoreline probabilities are generated.
- [ ] **ROUTE-03**: BTTS, over/under 2.5, WDL, and advance probabilities are regenerated from one coherent adjusted scoreline distribution.
- [ ] **ROUTE-04**: Runtime diagnostics show baseline lambdas, adjusted lambdas, route deltas, cap hits, and uncertainty shrink factors.

### Validation and Promotion

- [ ] **VAL-01**: Paired validation compares hybrid baseline and route-offset shadow output on identical fixtures.
- [ ] **VAL-02**: Validation reports Brier score, log loss, calibration, coverage, and market-specific BTTS/O/U2.5 behavior.
- [ ] **VAL-03**: Route-offset promotion is blocked unless probability quality beats or matches baseline under documented gates.
- [ ] **VAL-04**: Scanner and artifacts record promotion status so unvalidated route-offset behavior cannot silently affect production picks.
- [ ] **VAL-05**: UAT artifacts explain example fixtures, active duels, missing-data handling, and pass/fail promotion evidence.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Full learned player model | Not enough graded WC player/runtime data yet; begin with bounded deterministic offsets. |
| Raw player features directly in WDL | Risks double counting and breaks scoreline coherence. |
| Commercial data feeds | v2.4 remains compatible with free/manual/projected-XI inputs. |
| Automatic staking | Requires sportsbook price integration and separate bankroll policy. |
| Replacing MLB retrain package | MLB drift/retrain remains a separate documented work item. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| BASE-01 | Phase 43 | Planned |
| BASE-02 | Phase 43 | Planned |
| BASE-03 | Phase 43 | Planned |
| BASE-04 | Phase 43 | Planned |
| ROLE-01 | Phase 44 | Planned |
| ROLE-02 | Phase 44 | Planned |
| ROLE-03 | Phase 44 | Planned |
| ROLE-04 | Phase 44 | Planned |
| DUEL-01 | Phase 45 | Planned |
| DUEL-02 | Phase 45 | Planned |
| DUEL-03 | Phase 45 | Planned |
| DUEL-04 | Phase 45 | Planned |
| ROUTE-01 | Phase 46 | Planned |
| ROUTE-02 | Phase 46 | Planned |
| ROUTE-03 | Phase 46 | Planned |
| ROUTE-04 | Phase 46 | Planned |
| VAL-01 | Phase 47 | Planned |
| VAL-02 | Phase 47 | Planned |
| VAL-03 | Phase 47 | Planned |
| VAL-04 | Phase 47 | Planned |
| VAL-05 | Phase 47 | Planned |

**Coverage:**
- v2.4 requirements: 21 total
- Mapped to phases: 21
- Unmapped: 0

---
*Requirements defined: 2026-07-03*
