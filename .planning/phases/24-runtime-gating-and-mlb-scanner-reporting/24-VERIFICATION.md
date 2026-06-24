# Phase 24 Verification

## Commands

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/engines/test_mlb_model.py tests/unit/engines/test_mlb_artifact_gate.py tests/unit/engines/test_mlb_player_modeling.py tests/unit/engines/test_mlb_sgp_builder.py -q --tb=short --basetemp=.tmp-tests\pytest-phase24
```

Result: 39 passed.

```powershell
git diff --check
```

Result: passed with no whitespace errors. Git reported normal CRLF working-copy warnings on Windows.

## Coverage Against Success Criteria

1. Scanner-facing predictions include v1.8, v1.3 fallback, and market-implied labels with fallback reasons.
2. Player-aware uncertainty flags suppress pick eligibility when starter, lineup, bullpen, or source-confidence gates fail.
3. Runtime report exposes coverage, selective win rate, all-games accuracy, Brier score, and log loss fields when present in artifact metrics.
4. High-confidence player-aware scanner output can print starter, lineup, bullpen, absence, and missing-feature context.
5. Runtime rejects legacy non-bundle artifacts and does not use the old crude injury-adjusted moneyline model path.

