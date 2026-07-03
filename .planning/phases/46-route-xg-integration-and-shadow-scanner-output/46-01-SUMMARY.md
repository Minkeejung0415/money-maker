# Phase 46 Summary

Integrated route offsets into scoreline and scanner output.

## Delivered

- `route_offset_apply` and `route_offset_recompute_wdl` hooks
- baseline and adjusted lambda diagnostics
- baseline and shadow probabilities for WDL, O/U2.5, and BTTS
- scanner output line for route-offset status, eligibility, xG movement, O2.5, and BTTS
- promoted mode applies adjusted WDL only when eligible

## Tests

- `test_route_offset_can_recompute_scoreline_markets_without_recalibration`
- `test_main_route_offset_shadow_prints_diagnostics`
- `test_main_route_offset_promoted_updates_model_label`
