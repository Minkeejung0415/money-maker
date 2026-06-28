# Roadmap: v2.0 - Runtime Truth and Artifact Registry

**Milestone:** v2.0
**Phases:** 2 (Phase 33 -> Phase 34)
**Requirements:** 10 total | All mapped
**Phase numbering:** Continues from v1.9 (last phase: 32)

---

## Phase Summary

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|-----------------|
| 33 | Runtime Truth | Make WC scanner model selection explicit, fail closed, and support shadow logging. | RUNTIME-01..06 | 5 |
| 34 | Lightweight Artifact Registry | Validate runtime model metadata from JSON before scanners trust promoted artifacts. | ARTIFACT-01..04 | 4 |

---

## Phase Details

### Phase 33: Runtime Truth

**Goal:** Ensure every WC scanner run clearly reports the requested model, active model, fallback status, fallback reason, and shadow model status.

**Requirements:**
- RUNTIME-01 through RUNTIME-06

**Success criteria:**
1. `scripts/wc_scanner.py --help` shows `--model {elo,hybrid,player,auto}` and `--shadow-model {none,elo,hybrid}`.
2. `--model auto` and `--model player` fail closed when no valid promoted artifact exists.
3. `--allow-fallback` permits fallback only with explicit `fallback_used=true` and `fallback_reason=...` output.
4. `--shadow-model hybrid` writes shadow predictions without changing active picks.
5. Scanner output includes `requested_model`, `active_model`, `fallback_used`, and shadow status.

### Phase 34: Lightweight Artifact Registry

**Goal:** Introduce a small JSON metadata validator for runtime artifact trust gates, avoiding a heavyweight registry service.

**Requirements:**
- ARTIFACT-01 through ARTIFACT-04

**Success criteria:**
1. `alpha.engines.model_registry.validate_runtime_artifact()` validates required metadata fields.
2. Validation rejects missing, malformed, unpromoted, runtime-disallowed, schema-mismatched, and unsupported artifacts with explicit reasons.
3. WC `--model auto/player` routes through the validator before selecting a runtime model.
4. Unit tests cover success and failure paths.

---

## Coverage Audit

| Category | Requirements | Phase |
|----------|--------------|-------|
| Runtime Truth | RUNTIME-01 through RUNTIME-06 (6) | Phase 33 |
| Artifact Registry | ARTIFACT-01 through ARTIFACT-04 (4) | Phase 34 |

**Total: 10 / 10 requirements mapped**

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| Users expect `auto` to silently use Elo | Fail closed by default; fallback requires `--allow-fallback` and prints labels. |
| `player` model is not implemented yet | Expose the contract but error clearly until a promoted player runtime exists. |
| Shadow logging affects picks accidentally | Shadow predictions are collected separately and never passed to the builder. |
| Registry grows too complex | Keep v2.0 to JSON metadata validation only. |

---

*Roadmap created: 2026-06-28*
*Milestone: v2.0 | Phases 33-34 | 10 requirements | 2 phases*
