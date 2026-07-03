# Phase 47 Summary

Implemented paired validation and promotion gates.

## Delivered

- `scripts/validate_wc_route_offsets.py`
- paired baseline-vs-route metrics
- WDL Brier/log-loss
- O/U2.5 and BTTS binary Brier/log-loss
- minimum sample and no-regression gates
- JSON/JSONL input support and optional report output

## Tests

- `test_validate_rows_passes_when_route_improves_on_same_fixtures`
- `test_validate_rows_blocks_when_sample_too_small`
- `test_validate_rows_blocks_brier_regression`
- `test_load_rows_accepts_jsonl`
