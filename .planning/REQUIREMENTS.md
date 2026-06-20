# Requirements: v1.4 - Soccer Mode Upgrade

**Defined:** 2026-06-19
**Core Value:** EPL and UCL percentages must come from independent, auditable model inputs rather than silent market-implied fallback.

## Data Pipeline

- [x] **SDATA-01**: Last-five team form includes W/D/L, points, goals for, goals against, and goal difference.
- [x] **SDATA-02**: Last-five head-to-head meetings expose home wins, draws, away wins, and home win rate.
- [x] **SDATA-03**: Pregame days rest is available as an integer bounded from 0 to 7.
- [x] **SDATA-04**: Club Elo and FBref set-piece features are cached under an EPL/UCL namespace isolated from World Cup data.

## Soccer Models

- [ ] **SMODEL-01**: Retrain and calibrate the EPL model on the expanded pregame feature schema.
- [ ] **SMODEL-02**: Build a Club Elo logistic UCL model with independent W/D/L probabilities.
- [ ] **SMODEL-03**: Preserve explicit, league-specific fallback behavior and prevent cross-routing.

## Draw Betting and Scanner

- [ ] **SDRAW-01**: Include draw legs only when independent model EV exceeds 5%.
- [ ] **SDRAW-02**: Annotate accepted draw legs with `*DRAW RISK*` and reject fallback-derived draw legs.
- [ ] **SSCAN-01**: Route EPL scans to the EPL model and UCL scans to the UCL Elo model.
- [ ] **STEST-01**: Cover all new soccer components and pass the full repository suite without regression.

## Out of Scope

- In-play prediction
- Travel-distance fatigue
- Paid soccer data feeds
- Automatic sportsbook wagering

## Traceability

| Requirement | Phase | Status |
|---|---|---|
| SDATA-01 | Phase 12 | Complete |
| SDATA-02 | Phase 12 | Complete |
| SDATA-03 | Phase 12 | Complete |
| SDATA-04 | Phase 12 | Complete |
| SMODEL-01 | Phase 13 | Pending |
| SMODEL-02 | Phase 13 | Pending |
| SMODEL-03 | Phase 13 | Pending |
| SDRAW-01 | Phase 14 | Pending |
| SDRAW-02 | Phase 14 | Pending |
| SSCAN-01 | Phase 14 | Pending |
| STEST-01 | Phase 14 | Pending |

**Coverage:** 11 requirements, 11 mapped, 0 unmapped.

---
*Requirements updated: 2026-06-19 after Phase 12 completion*
