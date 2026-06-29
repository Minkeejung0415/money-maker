# Requirements: Alpha Terminal - Automated MLB Player Data and Accuracy Upgrade

**Defined:** 2026-06-28
**Milestone:** v2.3 - Automated MLB Player Data and Accuracy Upgrade
**Core Value:** Every prop line the scanner outputs must have a >55% historical hit rate; if the model cannot beat a coin flip, it is not worth betting.

## v2.3 Requirements

### Data Source Resilience

- [ ] **DATA-01**: MLB runtime does not require Fangraphs/pybaseball scraping to produce daily probabilities.
- [ ] **DATA-02**: MLB schedule and probable-pitcher identity use official MLB game ids where available.
- [ ] **DATA-03**: Data-source failures are recorded with explicit source, fallback, and freshness labels.
- [ ] **DATA-04**: Cached/local player data can be used for scanner runs when external sources are blocked or unavailable.

### Player Database Automation

- [ ] **DB-01**: User can run one command to update the local MLB player-stat database for a requested date or date range.
- [ ] **DB-02**: Imported batter, starter, bullpen, lineup, and absence rows are normalized into deterministic local schemas.
- [ ] **DB-03**: Database snapshots preserve raw components, source names, import time, game date, and MLB game id links.
- [ ] **DB-04**: The update command is idempotent and can safely re-run without duplicating rows.

### Feature Interpretation

- [ ] **FEAT-01**: Event-level feature files are generated per slate and keyed by MLB game id.
- [ ] **FEAT-02**: Starter features interpret raw stats through rolling form, workload, rest, quality, and uncertainty.
- [ ] **FEAT-03**: Lineup features interpret batter strength, confirmation coverage, missing starters, and absence impact.
- [ ] **FEAT-04**: Bullpen features interpret recent workload, fatigue, availability, quality, and missing-data risk.
- [ ] **FEAT-05**: Feature files include source confidence, stale flags, component coverage, and last-updated metadata.

### Model Accuracy and Promotion

- [ ] **MODEL-01**: MLB training can consume the richer event-level player features without target-game leakage.
- [ ] **MODEL-02**: Walk-forward evaluation compares baseline, starter-only, lineup, bullpen, absence, and full feature sets.
- [ ] **MODEL-03**: Candidate models are calibrated and evaluated with Brier score, log loss, accuracy, selective win rate, and coverage.
- [ ] **MODEL-04**: A richer MLB player-aware artifact is promoted only when it beats the current runtime baseline under documented gates.
- [ ] **MODEL-05**: Promotion metadata records feature schema hash, dataset fingerprint, training window, calibration, metrics, and runtime allowance.

### Scanner Runtime

- [ ] **SCAN-01**: MLB scanner auto-loads the date-specific local player feature file when present.
- [ ] **SCAN-02**: MLB scanner keeps manual `--player-features-file` override support.
- [ ] **SCAN-03**: Scanner output explains active data source, freshness, fallback reason, feature confidence, and suppression reason.
- [ ] **SCAN-04**: Scanner suppresses betting picks, while still returning research probabilities, when required player-data confidence is weak.

## Future Requirements

### Deeper Baseball Modeling

- **DEEP-01**: Add handedness/platoon splits, pitch mix, catcher framing, park/weather, umpire, and travel features.
- **DEEP-02**: Add live lineup confirmation monitoring after official lineups post.
- **DEEP-03**: Add automatic post-game result ingestion and shadow-prediction scoring.
- **DEEP-04**: Add real sportsbook odds feed integration for MLB edge and EV recommendations.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Paid data feeds | This milestone should improve the free/local pipeline first. |
| MLB player props | Requires prop odds and separate prop-specific targets. |
| Automatic betting/staking recommendations without market odds | Probabilities can be shown, but EV requires real prices. |
| Full pitch-level deep model | Too large for this milestone; start with major player/team stats and grow from there. |
| Replacing WC runtime work | v2.3 is MLB-focused; WC player runtime remains separate future work. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | Phase 38 | Pending |
| DATA-02 | Phase 38 | Pending |
| DATA-03 | Phase 38 | Pending |
| DATA-04 | Phase 38 | Pending |
| DB-01 | Phase 39 | Pending |
| DB-02 | Phase 39 | Pending |
| DB-03 | Phase 39 | Pending |
| DB-04 | Phase 39 | Pending |
| FEAT-01 | Phase 40 | Pending |
| FEAT-02 | Phase 40 | Pending |
| FEAT-03 | Phase 40 | Pending |
| FEAT-04 | Phase 40 | Pending |
| FEAT-05 | Phase 40 | Pending |
| MODEL-01 | Phase 41 | Pending |
| MODEL-02 | Phase 41 | Pending |
| MODEL-03 | Phase 41 | Pending |
| MODEL-04 | Phase 41 | Pending |
| MODEL-05 | Phase 41 | Pending |
| SCAN-01 | Phase 42 | Pending |
| SCAN-02 | Phase 42 | Pending |
| SCAN-03 | Phase 42 | Pending |
| SCAN-04 | Phase 42 | Pending |

**Coverage:**
- v2.3 requirements: 22 total
- Mapped to phases: 22
- Unmapped: 0

---
*Requirements defined: 2026-06-28*
*Last updated: 2026-06-28 after starting milestone v2.3*
