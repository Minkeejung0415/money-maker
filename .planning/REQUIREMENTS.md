# Requirements: Tactical Calibration and Validation

**Milestone:** v1.7
**Defined:** 2026-06-21
**Status:** Planned

## Historical Dataset

- [x] **WCCAL-01**: Build deduplicated historical international-match rows with final scores and tactical matchup components.
- [x] **WCCAL-02**: Every feature must use only matches completed before the target fixture kickoff.
- [x] **WCCAL-03**: Run a source-coverage preflight and exclude source matches with known red cards, extra-time contamination, unsupported competition context, or missing required summaries.
- [x] **WCCAL-04**: Persist dataset provenance, feature schema, cutoff timestamps, exclusions, and coverage diagnostics.

## Training and Evaluation

- [x] **WCCAL-05**: Fit tactical effects as strongly regularized residual adjustments conditional on the existing Elo and scoreline baseline.
- [x] **WCCAL-06**: Select hyperparameters using expanding-window chronological validation, never random cross-validation.
- [x] **WCCAL-07**: Use at least 50 later pre-tournament matches for chronological validation and seal at least 30 completed 2026 World Cup matches as a never-trained external audit.
- [x] **WCCAL-08**: Report multiplicity-corrected paired-bootstrap uncertainty, calibration diagnostics, sample counts, and comparisons against no-tactics, fixed-weight, and baseline-only recalibration controls.
- [x] **WCCAL-09**: Refuse model promotion when the historical sample is below the declared minimum or improvement is not robust out of sample.

## Safe Deployment

- [ ] **WCCAL-10**: Store trained weights and validation metadata in a versioned, schema-checked artifact.
- [ ] **WCCAL-11**: Gate single-market 1X2, totals, and BTTS independently, while every multi-leg SGP uses exactly one coherent scoreline distribution and falls back as a whole when any constituent family is unapproved.
- [ ] **WCCAL-12**: Preserve bounded adjustments, probability coherence, tactical explanations, and all existing stage rules.
- [ ] **WCCAL-13**: Scanner output must identify the active artifact and show whether each market passed, failed, or fell back.
- [ ] **WCCAL-14**: Focused tests and the complete regression suite must pass before any tactical artifact becomes the default.

## Out of Scope

- Guaranteed-pick claims or optimization for raw hit rate alone.
- Fitting seven free weights directly to the current 35-match World Cup sample.
- Paid tracking data, player coordinates, or inferred coaching intent.
- Enabling a market because another market improved.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| WCCAL-01..04 | Phase 20 / Plan 01 | Planned |
| WCCAL-05..09 | Phase 20 / Plan 02 | Planned |
| WCCAL-10..14 | Phase 20 / Plan 03 | Planned |

---
*Last updated: 2026-06-21 after Phase 20 planning*
