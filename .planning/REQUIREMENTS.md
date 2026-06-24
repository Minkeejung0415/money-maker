# Requirements: Alpha Terminal - Player-Aware MLB Moneyline Model

**Defined:** 2026-06-24
**Core Value:** Every prop line the scanner outputs must have a >55% historical hit rate - if the model can't beat a coin flip, it's not worth betting.

## v1.8 Requirements

### Data Foundation

- [ ] **MLBDATA-01**: User can build a historical MLB games table with canonical game IDs, dates, teams, venue, status, doubleheader context, final target, and probable or actual starter IDs.
- [ ] **MLBDATA-02**: User can build a historical game-player slots table containing lineup players, batting order, side, position, starter role, player IDs, and confirmation/source status.
- [ ] **MLBDATA-03**: User can join MLBAM, Retrosheet, and internal player references through a stable ID mapping layer with explicit unmatched-player reporting.
- [ ] **MLBDATA-04**: User can refresh day-of MLB starter, lineup, roster, and injury availability inputs without using paid data providers.

### Player Features

- [ ] **MLBFEAT-01**: User can generate shifted starting-pitcher quality and rest features from only information available before first pitch.
- [ ] **MLBFEAT-02**: User can generate lineup strength and platoon-matchup aggregates from projected or confirmed hitters, including missing-player counts and source-confidence flags.
- [ ] **MLBFEAT-03**: User can generate bullpen freshness and relief-depth features from recent appearances without allowing target-game usage.
- [ ] **MLBFEAT-04**: User can represent injury and absence deltas as structured player-availability features instead of crude team batting-average penalties.
- [ ] **MLBFEAT-05**: User can run automated leakage checks proving rolling player and team features exclude the target game.

### Modeling and Validation

- [ ] **MLBMODEL-01**: User can reproduce the existing v1.3 eight-feature MLB model as the baseline scorecard.
- [ ] **MLBMODEL-02**: User can train starter-only, starter-plus-lineup, starter-plus-lineup-plus-bullpen, and full player-aware ablations.
- [ ] **MLBMODEL-03**: User can evaluate candidates with date-based walk-forward splits, a separate calibration block, Brier score, log loss, all-games accuracy, and calibration buckets.
- [ ] **MLBMODEL-04**: User can tune and compare regularized logistic regression, HistGradientBoosting, and LightGBM when the dependency is available.
- [ ] **MLBMODEL-05**: User can persist a player-aware model artifact with schema version, feature names, split dates, data-source fingerprints, metrics, and promotion gates.

### Runtime and Reporting

- [ ] **MLBRUN-01**: User can run the MLB scanner and see whether each prediction comes from the validated v1.8 player-aware artifact or the v1.3 baseline fallback.
- [ ] **MLBRUN-02**: User can suppress or downgrade picks when starter, lineup, injury, or player-feature uncertainty exceeds configured thresholds.
- [ ] **MLBRUN-03**: User can report selective win rate, coverage, all-games accuracy, Brier score, and log loss for confidence-gated MLB picks.
- [ ] **MLBRUN-04**: User can inspect why a game received a high-confidence pick, including starter, lineup, bullpen, and absence feature contributions.
- [ ] **MLBRUN-05**: User is protected from moneyline paths that reuse synthetic MLB prop features or legacy crude injury penalties.

## Future Requirements

### Advanced Baseball Context

- **MLBFUT-01**: Add catcher framing, defense, and baserunning feature blocks after the starter, lineup, bullpen, and injury layers are validated.
- **MLBFUT-02**: Add paired statistical significance tests such as McNemar, Diebold-Mariano, and block bootstrap confidence intervals.
- **MLBFUT-03**: Add optional odds-aware EV reporting only after the accuracy-first player-aware model is validated.
- **MLBFUT-04**: Replace every fallback source with official MLB/Retrosheet/Savant equivalents where practical.

## Out of Scope

| Feature | Reason |
|---------|--------|
| MLB player props | The report explicitly targets game-level moneyline accuracy, and prop modeling needs separate odds/data validation. |
| MLB parlay optimization | Single-game probabilities must improve first before combining them into parlays. |
| Paid data feeds | v1.8 should prove the lift using free/official sources already aligned with the project constraints. |
| Odds/EV-driven promotion | The milestone is accuracy and win-rate focused; odds can remain optional comparison context. |
| Exact batting-order overfitting | The report ranks player talent and matchup quality above slot-level effects. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| MLBDATA-01 | Phase 21 | Pending |
| MLBDATA-02 | Phase 21 | Pending |
| MLBDATA-03 | Phase 21 | Pending |
| MLBDATA-04 | Phase 21 | Pending |
| MLBFEAT-01 | Phase 22 | Pending |
| MLBFEAT-02 | Phase 22 | Pending |
| MLBFEAT-03 | Phase 22 | Pending |
| MLBFEAT-04 | Phase 22 | Pending |
| MLBFEAT-05 | Phase 22 | Pending |
| MLBMODEL-01 | Phase 23 | Pending |
| MLBMODEL-02 | Phase 23 | Pending |
| MLBMODEL-03 | Phase 23 | Pending |
| MLBMODEL-04 | Phase 23 | Pending |
| MLBMODEL-05 | Phase 23 | Pending |
| MLBRUN-01 | Phase 24 | Pending |
| MLBRUN-02 | Phase 24 | Pending |
| MLBRUN-03 | Phase 24 | Pending |
| MLBRUN-04 | Phase 24 | Pending |
| MLBRUN-05 | Phase 24 | Pending |

**Coverage:**
- v1.8 requirements: 19 total
- Mapped to phases: 19
- Unmapped: 0

---
*Requirements defined: 2026-06-24*
*Last updated: 2026-06-24 after v1.8 milestone definition*
