# Roadmap: v2.4 - WC Hybrid Route Offset

**Milestone:** v2.4
**Phases:** 5 (Phase 43 -> Phase 47)
**Requirements:** 21 total | All mapped and complete
**Phase numbering:** Continues from Phase 42

---

## Phase Summary

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|-----------------|
| 43 | Route Offset Contracts and Baseline Harness | Establish the runtime contract that keeps hybrid as the prior and route-offset as shadow-only by default. | BASE-01..04 | Complete |
| 44 | Role Strength Snapshot and Projected XI Inputs | Build event-level projected-XI role-strength inputs with coverage and uncertainty labels. | ROLE-01..04 | Complete |
| 45 | Tactical Duel Engine and Capped Route Deltas | Convert a narrow set of football-native tactical duels into bounded route-level xG offsets. | DUEL-01..04 | Complete |
| 46 | Route xG Integration and Shadow Scanner Output | Recompose adjusted lambdas and regenerate scoreline-derived markets from one coherent distribution. | ROUTE-01..04 | Complete |
| 47 | Paired Validation and Promotion Gates | Validate route-offset shadow output against the hybrid baseline and prepare UAT evidence. | VAL-01..05 | Complete |

---

## Phase Details

### Phase 43: Route Offset Contracts and Baseline Harness

**Goal:** Ensure route-offset behavior is an auditable adapter around the existing WC hybrid model, not a silent model replacement.

**Requirements:**
- BASE-01 through BASE-04

**Success criteria:**
1. Route-offset runtime has an explicit schema/config identity.
2. Hybrid baseline probabilities and lambdas remain available for every route-offset run.
3. Shadow mode can run without changing production pick eligibility.
4. Missing/stale/schema-mismatched route-offset inputs fail closed to hybrid baseline.
5. Tests cover baseline fallback and identity mismatch.

### Phase 44: Role Strength Snapshot and Projected XI Inputs

**Goal:** Create runtime projected-XI role-strength payloads with honest coverage and uncertainty labels.

**Requirements:**
- ROLE-01 through ROLE-04

**Success criteria:**
1. Event-level payloads represent GK, CB, FB, DM, winger, and striker strength.
2. Payload metadata records source, update time, schema version, role coverage, and missing roles.
3. Missing-role coverage shrinks offsets toward zero.
4. Critical missing roles suppress route-offset pick eligibility but still return research probabilities.
5. Tests cover complete, partial, stale, and missing projected-XI snapshots.

### Phase 45: Tactical Duel Engine and Capped Route Deltas

**Goal:** Translate high-leverage tactical matchups into capped route-level xG movements.

**Requirements:**
- DUEL-01 through DUEL-04

**Success criteria:**
1. Wing isolation, aerial/set-piece mismatch, and press-vs-build rules are implemented.
2. Each active duel emits rule id, involved roles, direction, magnitude, and missing-data adjustment.
3. Route and match-level caps prevent implausible xG movement.
4. Rule/config identity is versioned and included in diagnostics.
5. Tests cover rule activation, cap hits, and uncertainty shrinkage.

### Phase 46: Route xG Integration and Shadow Scanner Output

**Goal:** Feed adjusted lambdas through the existing scoreline surface so BTTS, totals, WDL, and advance probabilities remain coherent.

**Requirements:**
- ROUTE-01 through ROUTE-04

**Success criteria:**
1. Baseline lambdas are allocated into center, wing, set-piece, and counterattack buckets.
2. Route deltas recompose into adjusted home/away lambdas before scoreline generation.
3. BTTS, over/under 2.5, WDL, and advance probabilities come from one adjusted distribution.
4. Scanner output shows baseline vs adjusted values, cap hits, shrinkage, and active duel explanations.
5. Tests prove the adjusted distribution remains normalized and fallback-safe.

### Phase 47: Paired Validation and Promotion Gates

**Goal:** Decide with evidence whether route-offset improves the hybrid model enough to affect production picks.

**Requirements:**
- VAL-01 through VAL-05

**Success criteria:**
1. Validation compares baseline and route-offset on identical fixtures.
2. Reports include Brier, log loss, calibration, coverage, BTTS, and O/U2.5 behavior.
3. Promotion is blocked unless documented gates are met.
4. Scanner/artifact metadata exposes promotion status and runtime allowance.
5. UAT examples explain active duels, missing-data handling, and pass/fail evidence.

---

## Dependency Flow

Phase 43 defines the contract and safety rails. Phase 44 supplies projected-XI role data. Phase 45 converts role/tactical matchups into capped route deltas. Phase 46 integrates those deltas into scoreline-derived probabilities. Phase 47 validates and decides whether promotion is allowed.

## Verification Plan

- Unit tests for contracts, role snapshots, duel rules, caps, fallback behavior, and scoreline normalization.
- Scanner smoke tests for shadow output and fallback labels.
- Paired validation report comparing route-offset to hybrid baseline.
- UAT examples for at least three fixtures with different duel/missing-data profiles.

---
*Roadmap defined: 2026-07-03*
*Last updated: 2026-07-03 after phases 43-47 completed*
