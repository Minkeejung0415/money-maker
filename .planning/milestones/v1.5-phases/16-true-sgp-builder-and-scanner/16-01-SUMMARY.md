---
phase: 16-true-sgp-builder-and-scanner
plan: 01
status: complete
completed: 2026-06-21
requirements: [WCSGP-06, WCSGP-07, WCSGP-08, WCSGP-09, WCSGP-10, WCSGP-11, WCSGP-12]
---

# Phase 16 Plan 01 Summary

Added a normalized local odds contract for 1X2, over/under 2.5, and BTTS markets while retaining the legacy home/away override schema. `WCSGPBuilder.build_same_game()` now creates compatible 2-3 leg selections from one event, calculates exact scoreline joint probability, ranks by EV, and excludes regulation-time 1X2 legs in knockout rounds.

`wc_scanner.py --mode sgp` routes to this builder and explains when the supplied odds file lacks compatible market families. Classic `--mode parlay` remains unchanged.

## Verification

- Focused WC tests: 37 passed
- Scanner tests after final message refinement: 8 passed
- Full suite: 753 passed in 235.68s
- Live June 21 smoke run: 3 fixtures fetched; no SGP emitted because the current override contains only opposing 1X2 prices and no totals/BTTS prices

## Price Note

The displayed combined price is the product of supplied standalone market prices. A sportsbook may apply a different correlated SGP quote; that quote must replace the indicative product before treating the displayed edge as actionable.

