# Phase 24 Code Review

## Findings

No blocking issues found after the fallback fix.

## Review Notes

- v1.8 artifacts now require schema version, validation flag, all promotion gates, known feature schema, model, and calibrator.
- Legacy non-bundle MLB moneyline artifacts are rejected and recorded in `runtime_report()["rejections"]`.
- The loader keeps scanning after a valid v1.8 artifact so it can also retain a validated v1.3 fallback bundle.
- Missing player-aware game features fall back to v1.3 when available; this has regression coverage.
- Player-aware uncertainty flags set `confidence="LOW"` and `pick_eligible=False`, and scanner parlay construction excludes ineligible games.
- Existing prediction keys are preserved for compatibility.

## Residual Risk

- A disabled legacy loader method remains in the file only because the old block contains encoded text that resisted a low-risk patch removal. It is not called; the active `_load_xgb_models` method is the gated implementation.
- Live construction of player-aware feature rows remains deferred. Runtime now enforces the contract for precomputed player-aware features.

## Verification Reviewed

- `.venv\Scripts\python.exe -m pytest tests/unit/engines/test_mlb_model.py tests/unit/engines/test_mlb_artifact_gate.py tests/unit/engines/test_mlb_player_modeling.py tests/unit/engines/test_mlb_sgp_builder.py -q --tb=short --basetemp=.tmp-tests\pytest-phase24`
- `git diff --check`

