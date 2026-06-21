---
status: resolved
trigger: "look for similar issues and possible incorrect options and fix"
created: 2026-06-21
updated: 2026-06-21
---

# Debug Session: WC Stale Goal Priors

## Symptoms

- **Expected:** World Cup totals and BTTS probabilities use recent, pre-match international team form and strength-aware opponent adjustments.
- **Actual:** `WCScorelineModel` uses StatsBomb aggregates from only the 2018 and 2022 World Cups. Spain vs Saudi Arabia assigns Saudi a 1.365 goal rate, 62.3% chance to score, and 61.2% BTTS Yes.
- **Errors:** No exception; outputs are numerically valid but potentially miscalibrated.
- **Timeline:** Exposed immediately after probability-only SGP mode was run on 2026-06-21.
- **Reproduction:** Run `scripts/wc_scanner.py --mode sgp --date-from 2026-06-21 --date-to 2026-06-21` and inspect Spain vs Saudi Arabia BTTS selections.

## Current Focus

- **hypothesis:** Confirmed.
- **test:** Last-10 pre-match EloRatings form, current Elo overrides, strength-adjusted goal rates, focused tests, live three-game audit, and full suite.
- **expecting:** Resolved outputs remain coherent for every fixture and fail closed without five recent matches.
- **next_action:** None; session resolved.

## Evidence

- timestamp: 2026-06-21
  observation: Spain cached stats are avg_xG 2.3657 and defense_score 1.6853; Saudi Arabia avg_xG 1.0449 and defense_score 1.7601.
- timestamp: 2026-06-21
  observation: Equal averaging produces lambdas Spain 2.0629 and Saudi Arabia 1.3651; calibrated Saudi scoring probability is 62.35%.
- timestamp: 2026-06-21
  observation: football-data.org free access returned only one prior match for Spain and Saudi Arabia, insufficient for rolling form.
- timestamp: 2026-06-21
  observation: EloRatings TSV supplies dated scores and pre-match/current Elo for every audited team through June 2026.
- timestamp: 2026-06-21
  observation: Live global audit loaded last-10 form for all six teams across all three June 21 fixtures.
- timestamp: 2026-06-21
  observation: Corrected Spain-Saudi output gives Saudi 29.9% to score and BTTS Yes 27.1%; top combination is Spain win plus BTTS No at 64.6%.
- timestamp: 2026-06-21
  observation: 70 focused tests and 766 full-suite tests pass.

## Eliminated

- hypothesis: Spain-Saudi team-name mismatch caused fallback stats.
  reason: Both teams existed in the historical cache and recent TSV feed; the formula and stale inputs were the defect.
- hypothesis: football-data.org alone could provide a stable recent window.
  reason: Current free access exposed only one or two completed WC matches per national team.

## Resolution

- root_cause: Runtime goal markets used 2018/2022-only StatsBomb aggregates, equal attack/defense averaging ignored matchup strength, and outcome Elo could lag in a static file.
- fix: Added leakage-safe last-10 EloRatings form for every fixture/team, opponent-strength normalization, per-match current Elo overrides, matchup-adjusted goal rates, six-hour cache, and fail-closed minimum history.
- verification: Live June 21 audit covered Spain-Saudi Arabia, Belgium-Iran, and Uruguay-Cape Verde; 70 focused tests and 766 full tests passed.
- files_changed: alpha/data/ingestion/wc_recent_form.py, alpha/engines/sports/wc_goal_markets.py, alpha/engines/sports/wc_model.py, scripts/wc_scanner.py, and corresponding tests.
