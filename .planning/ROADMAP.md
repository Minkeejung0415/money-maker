# Roadmap: v2.3 - Automated MLB Player Data and Accuracy Upgrade

**Milestone:** v2.3
**Phases:** 5 (Phase 38 -> Phase 42)
**Requirements:** 22 total | All mapped
**Phase numbering:** Continues from Phase 37

---

## Phase Summary

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|-----------------|
| 38 | MLB Data Source Resilience | Remove Fangraphs scraping as a required runtime dependency and formalize source/fallback labels. | DATA-01..04 | 5 |
| 39 | Automated Player Database Updates | Add repeatable daily/date-range MLB player database update commands. | DB-01..04 | 5 |
| 40 | Player Feature Interpretation Layer | Turn raw player/team stats into event-level starter, lineup, bullpen, absence, and uncertainty features. | FEAT-01..05 | 6 |
| 41 | MLB Accuracy Retraining and Promotion | Retrain and gate richer player-aware MLB moneyline artifacts using walk-forward evaluation. | MODEL-01..05 | 6 |
| 42 | MLB Scanner Auto-Load Runtime | Auto-load local player features in scanner output with truthful source/freshness/confidence labeling. | SCAN-01..04 | 5 |

---

## Phase Details

### Phase 38: MLB Data Source Resilience

**Goal:** Ensure MLB runtime probabilities do not depend on live Fangraphs/pybaseball scraping and every data-source fallback is visible.

**Requirements:**
- DATA-01 through DATA-04

**Success criteria:**
1. MLB scanner can run when Fangraphs/pybaseball calls fail or are disabled.
2. Official MLB game ids and probable-pitcher fields are preferred for runtime identity.
3. Runtime feature context reports source, fallback reason, freshness, and confidence.
4. Tests simulate external-source failures and prove scanner output remains labeled and usable.
5. Documentation names which sources are runtime-required versus optional enrichment.

### Phase 39: Automated Player Database Updates

**Goal:** Add one-command local MLB player database updates for requested dates/date ranges.

**Requirements:**
- DB-01 through DB-04

**Success criteria:**
1. A script such as `scripts/update_mlb_player_database.py --date YYYY-MM-DD` writes normalized local data.
2. Batter, starter, bullpen, lineup, and absence inputs share deterministic schema/version metadata.
3. Re-running the same date is idempotent and does not duplicate rows.
4. Snapshots preserve raw stat components, source names, import time, game date, and game id links.
5. Unit tests use local fixtures only and require no internet access.

### Phase 40: Player Feature Interpretation Layer

**Goal:** Convert local player database rows into stronger event-level features that reflect baseball context rather than raw stat dumps.

**Requirements:**
- FEAT-01 through FEAT-05

**Success criteria:**
1. Date-specific feature files are emitted with event ids matching scanner games.
2. Starter features include rolling quality, workload, rest, and uncertainty.
3. Lineup features include batter strength, confirmation coverage, missing starters, and absence value.
4. Bullpen features include recent workload, fatigue, availability, quality, and missing-data risk.
5. Feature files include source confidence, stale flags, coverage, and last-updated metadata.
6. Tests prove same-series games can diverge through starter/lineup/bullpen context.

### Phase 41: MLB Accuracy Retraining and Promotion

**Goal:** Train, calibrate, and promote a richer MLB player-aware model only if the new feature interpretation improves probability quality.

**Requirements:**
- MODEL-01 through MODEL-05

**Success criteria:**
1. Training rows consume richer event-level features without target-game leakage.
2. Walk-forward evaluation compares baseline, starter-only, lineup, bullpen, absence, and full-player feature sets.
3. Metrics include Brier score, log loss, accuracy, selective win rate, and coverage.
4. Promotion gates reject candidates that fail to beat the current runtime baseline.
5. Promoted artifact metadata includes schema hash, dataset fingerprint, training window, calibration, metrics, and runtime allowance.
6. Tests cover artifact rejection, promotion metadata, and feature schema mismatch.

### Phase 42: MLB Scanner Auto-Load Runtime

**Goal:** Make the MLB scanner automatically use local date-specific player features when available, while labeling all fallbacks and suppressions.

**Requirements:**
- SCAN-01 through SCAN-04

**Success criteria:**
1. `scripts/mlb_scanner.py --date YYYY-MM-DD` auto-loads the matching local feature file when present.
2. Manual `--player-features-file` override still works and is clearly labeled.
3. Individual output shows active data source, freshness, fallback reason, confidence, and suppression reason.
4. Weak/stale/missing player data suppresses betting picks while retaining research probabilities.
5. Smoke tests cover runs with local features present, absent, stale, and manually overridden.

---

## Coverage Audit

| Category | Requirements | Phase |
|----------|--------------|-------|
| Data Source Resilience | DATA-01 through DATA-04 (4) | Phase 38 |
| Player Database Automation | DB-01 through DB-04 (4) | Phase 39 |
| Feature Interpretation | FEAT-01 through FEAT-05 (5) | Phase 40 |
| Model Accuracy and Promotion | MODEL-01 through MODEL-05 (5) | Phase 41 |
| Scanner Runtime | SCAN-01 through SCAN-04 (4) | Phase 42 |

**Total: 22 / 22 requirements mapped**

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| Free baseball sources change or block requests | Runtime uses local cached data and explicit source/fallback labels. |
| Raw stats improve labels but not probabilities | Phase 41 requires walk-forward ablations and promotion gates before runtime trust. |
| Feature files drift from artifact schema | Store schema hashes and reject mismatches at runtime. |
| Same-day lineup data causes leakage in training | Training rows must enforce pregame availability and date-based leakage checks. |
| Scanner appears confident on stale data | Stale flags and low source confidence suppress betting picks. |

---

*Roadmap created: 2026-06-28*
*Milestone: v2.3 | Phases 38-42 | 22 requirements | 5 phases*
