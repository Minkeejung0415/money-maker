# Phase 23 Verification

## Commands

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/engines/test_mlb_player_modeling.py tests/unit/engines/test_mlb_player_features.py tests/unit/engines/test_mlb_training.py -q --tb=short --basetemp=.tmp-tests\pytest-phase23
```

Result: 12 passed.

```powershell
git diff --check
```

Result: passed with no whitespace errors.

## Coverage Against Success Criteria

1. v1.3 eight-feature baseline is reproduced by `baseline_v1_3` and asserted against `FEATURE_NAMES`.
2. Starter, lineup, bullpen, and full player-aware ablations are defined and tested.
3. Walk-forward folds use chronological train, later calibration, and later test blocks with Brier score, log loss, accuracy, and calibration buckets.
4. Logistic regression and HistGradientBoosting are always available; LightGBM is included only when installed.
5. Metadata builder includes schema version, feature names, split dates, source fingerprints, metrics, and promotion gates.

