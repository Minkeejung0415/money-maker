# Requirements: Alpha Terminal - Runtime Truth and Artifact Registry

**Defined:** 2026-06-28
**Milestone:** v2.0 - Runtime Truth and Artifact Registry
**Core Value:** Every prop line the scanner outputs must have a >55% historical hit rate; if the model cannot beat a coin flip, it is not worth betting.

## v2.0 Requirements

### Runtime Truth

- [x] **RUNTIME-01**: WC scanner supports explicit `--model elo`, `--model hybrid`, `--model player`, and `--model auto` choices.
- [x] **RUNTIME-02**: `elo` remains an always-available baseline and `hybrid` remains an explicit challenger.
- [x] **RUNTIME-03**: `auto` and `player` fail closed when a promoted runtime artifact is unavailable or invalid; they do not silently fall back to Elo.
- [x] **RUNTIME-04**: Explicit fallback requires `--allow-fallback` and prints `requested_model`, `active_model`, `fallback_used`, and `fallback_reason`.
- [x] **RUNTIME-05**: WC scanner supports `--shadow-model` for challenger logging that does not affect picks or rankings.
- [x] **RUNTIME-06**: Scanner output labels the active model and shadow model status for every run.

### Artifact Registry

- [x] **ARTIFACT-01**: Runtime artifacts can be validated from lightweight JSON metadata stored beside model artifacts.
- [x] **ARTIFACT-02**: Metadata includes model ID, league, market, created date, feature schema hash, dataset fingerprint, calibration method, promotion status, and runtime allowance.
- [x] **ARTIFACT-03**: Scanner runtime accepts artifacts only when `promotion_passed=true`, `allowed_runtime=true`, league and market match, and schema/model gates pass.
- [x] **ARTIFACT-04**: Unsupported, missing, malformed, unpromoted, or runtime-disallowed artifacts return explicit rejection reasons.

## Future Requirements

### Runtime Model Registry Expansion

- **REGISTRY-01**: MLB scanner supports the same `--model`, `--shadow-model`, and `--allow-fallback` contract.
- **REGISTRY-02**: `--model auto` can rank promoted artifacts across leagues by approved runtime priority.
- **REGISTRY-03**: Shadow predictions are evaluated automatically after results settle.

### Player Runtime

- **PLAYER-01**: WC `--model player` loads a real promoted player-aware artifact once the player runtime is implemented.
- **PLAYER-02**: Player-aware runtime includes projected XI, goalkeeper, tournament-state, tactical, and context feature snapshots.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Full MLflow-style registry service | JSON metadata is enough for v2.0; avoid overbuilding governance infrastructure. |
| Automatic promotion of hybrid to default | Requires shadow evidence and post-result scoring before default promotion. |
| WC player model runtime implementation | Larger modeling task; v2.0 only makes the runtime contract honest. |
| Invented odds or synthetic EV | Recommendations still require real supplied prices. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| RUNTIME-01 | Phase 33 | Complete |
| RUNTIME-02 | Phase 33 | Complete |
| RUNTIME-03 | Phase 33 | Complete |
| RUNTIME-04 | Phase 33 | Complete |
| RUNTIME-05 | Phase 33 | Complete |
| RUNTIME-06 | Phase 33 | Complete |
| ARTIFACT-01 | Phase 34 | Complete |
| ARTIFACT-02 | Phase 34 | Complete |
| ARTIFACT-03 | Phase 34 | Complete |
| ARTIFACT-04 | Phase 34 | Complete |

**Coverage:**
- v2.0 requirements: 10 total
- Mapped to phases: 10
- Unmapped: 0

---
*Requirements defined: 2026-06-28*
*Last updated: 2026-06-28 after autonomous execution*
