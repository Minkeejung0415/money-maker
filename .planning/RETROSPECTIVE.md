# Retrospective

## Milestone: v1.7 - Tactical Calibration and Validation

**Shipped:** 2026-06-22
**Phases:** 1 | **Plans:** 3

### What Was Built

- Direct ESPN-cache historical tactical row reconstruction with strict as-of provenance.
- Regularized residual outcome and goal models with chronological selection.
- Corrected bootstrap promotion gates and versioned runtime artifacts.
- Explicit baseline fallback and one-distribution-per-SGP behavior.

### What Worked

- Cross-AI review caught infeasible holdout and incoherent mixed-market assumptions before execution.
- Fail-closed sample gates allowed an honest result when real coverage was inadequate.
- Focused tests caught runtime issues quickly before the four-minute complete suite.

### What Was Inefficient

- Legacy roadmap headings confused GSD milestone scoping and required archive correction.
- The complete suite was rerun several times because `.env` values leaked into explicit-empty-key tests.
- Initial dataset work validated prepared rows but did not enumerate the cache until the milestone audit caught the omission.

### Patterns Established

- Treat model promotion and model implementation as separate outcomes.
- Seal validation/audit event IDs and fingerprints before examining results.
- A same-game probability must come wholly from one coherent distribution.

### Key Lessons

- Data attainability should be measured before choosing sample thresholds.
- Small calibration gains are not evidence without paired uncertainty and control recalibration.
- “No model promoted” is a successful outcome when the alternative is deploying noise.

## Cross-Milestone Trends

| Milestone | Verification | Main Lesson |
|-----------|--------------|-------------|
| v1.7 | 792 passed, 5 skipped | Evidence gates must be allowed to block deployment |
