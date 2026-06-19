# Requirements: v1.3 — MLB Win Probability Model

**Defined:** 2026-06-19
**Core Value:** Daily MLB percentages must come from a validated independent model, never a silent 50/50 placeholder.

## v1.3 Requirements

### Historical Data

- [x] **MLBD-01**: Build a reproducible historical MLB game dataset from free sources with final outcomes and canonical team identifiers.
- [x] **MLBD-02**: Every model feature is computed from information available before the target game's first pitch.
- [x] **MLBD-03**: Training and live inference use the same feature schema and transformations.

### Modeling

- [x] **MLBM-01**: Train at least one transparent baseline and one boosted candidate on chronological data.
- [x] **MLBM-02**: Calibrate probabilities using a validation window separate from training and final testing.
- [x] **MLBM-03**: Select the released model using out-of-time Brier score and log loss, with accuracy reported second.
- [x] **MLBM-04**: Persist estimator metadata including schema, training dates, metrics, calibration, and model version.

### Runtime

- [x] **MLBR-01**: MLBModel loads only schema-compatible validated artifacts and clearly reports its source/status.
- [x] **MLBR-02**: MLB scanner prints home/away percentages and fair decimal odds for every daily matchup.
- [x] **MLBR-03**: Scanner never presents placeholder -110/-110 probabilities as an independent model prediction.
- [x] **MLBR-04**: Optional manual sportsbook odds enable no-vig comparison and edge output without paid API usage.

### Verification

- [x] **MLBV-01**: Leakage, chronology, feature parity, artifact validation, and scanner output have automated tests.
- [x] **MLBV-02**: Full repository tests pass with no regressions.

## Future Requirements

- Player prop probabilities and prop odds ingestion
- Parlay construction and bankroll sizing from validated MLB probabilities
- Automated paid live moneyline feed

## Out of Scope

| Feature | Reason |
|---------|--------|
| Player props | Requires broader data and dependable prop odds |
| Parlays | Single-game probability quality must be proven first |
| Paid feeds | v1.3 is free-data only |
| In-game predictions | Pregame model only |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| MLBD-01 | Phase 9 | Complete |
| MLBD-02 | Phase 9 | Complete |
| MLBD-03 | Phase 9 | Complete |
| MLBM-01 | Phase 10 | Complete |
| MLBM-02 | Phase 10 | Complete |
| MLBM-03 | Phase 10 | Complete |
| MLBM-04 | Phase 10 | Complete |
| MLBR-01 | Phase 11 | Complete |
| MLBR-02 | Phase 11 | Complete |
| MLBR-03 | Phase 11 | Complete |
| MLBR-04 | Phase 11 | Complete |
| MLBV-01 | Phases 9-11 | Complete |
| MLBV-02 | Phase 11 | Complete |

**Coverage:** 13 requirements, 13 mapped, 0 unmapped.

---
*Requirements defined: 2026-06-19*
