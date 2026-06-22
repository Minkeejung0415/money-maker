# Phase 14: Draw Betting + Scanner Integration — Context

**Gathered:** 2026-06-19
**Milestone:** v1.4 — Soccer Mode Upgrade
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire everything together and enable draw betting:
1. **Draw legs** in `SoccerSGPBuilder` when model EV > 5% (annotated `*DRAW RISK*`)
2. **Scanner routing** in `soccer_scanner.py`: EPL → XGBoost, UCL → UCLEloModel
3. **Full test coverage** for all v1.4 components; total test count ≥ 636

This is the integration phase — models and data pipelines are already built. No new model training.

</domain>

<decisions>
## Implementation Decisions

### D-11 Draw betting gate
Include draw legs in parlay combos only when:
- Model-estimated draw probability produces EV > 5% vs. market draw decimal odds
- The draw probability comes from the XGBoost or Elo model layer (NOT market-implied fallback)
- Gate enforced in `SoccerSGPBuilder.build()` via `game.get('model_name')` check

### D-12 Draw annotation
Annotate draw legs with `*DRAW RISK*` in scanner output (same pattern as WC's `*ELO EDGE*`).
This makes draw legs visually distinct so user can avoid them if desired.

### D-13 Scanner routing
`soccer_scanner.py`:
- `--league epl` → `SoccerModel` (XGBoost, Phase 13 retrained)
- `--league ucl` → `UCLEloModel` (Club Elo-logistic, Phase 13)
- Routing guard: `if game.get('league') == 'ucl': model = ucl_model`
- Fallback chain preserved: EPL = XGBoost → market_implied; UCL = UCLEloModel → market_implied

### D-14 Test coverage
- Unit tests for form/H2H/rest/set piece ingestion modules (mock football-data.org + FBref)
- Unit tests for UCLEloModel (assert W/D/L sum = 1, draw decreases with Elo gap, elo_edge flag)
- Unit tests for EPL XGBoost model load (schema gate — same pattern as test_mlb_artifact_gate.py)
- Unit tests for draw leg inclusion/exclusion gate in SGP builder
- Integration test for scanner routing (EPL vs UCL paths don't cross)
- Total test count ≥ 636 (no regressions)

### Claude's Discretion
- Test fixture design (mock data shapes for new features)
- Whether to add `--draw-threshold` CLI flag or hard-code EV > 5% gate

</decisions>

<canonical_refs>
## Canonical References

- `alpha/engines/sports/soccer_sgp_builder.py` — add draw leg type; model gate for draw inclusion
- `scripts/soccer_scanner.py` — add UCL routing branch, draw annotation
- `alpha/engines/sports/wc_sgp_builder.py` — WC SGP builder as reference for draw suppression pattern
- `scripts/wc_scanner.py` — `*ELO EDGE*` annotation pattern to mirror for `*DRAW RISK*`
- `tests/unit/engines/test_mlb_artifact_gate.py` — artifact gate test pattern for EPL model
- `tests/unit/test_wc_scanner.py` — capsys scanner output test pattern for `soccer_scanner.py`

</canonical_refs>

<code_context>
## Existing Code Insights

- `SoccerSGPBuilder.build()` currently has no draw leg support — add alongside existing home/away legs
- `WCSGPBuilder` has `_knockout_gate()` that strips Draw legs in knockout rounds — mirror but for market-implied source gating
- `soccer_scanner.py` currently routes all soccer through `SoccerModel` — add UCL branch before this
- Current scanner output has `win_prob`, `loss_prob` but no `draw_prob` display — add draw column

</code_context>

<specifics>
## Specific Notes

- Draw market odds: football-data.org provides draw_odds in fixture data. Use those if available; else skip draw EV check.
- Scanner output format: add D% column alongside H% and A% in the table view
- `*DRAW RISK*` annotation: shown next to the leg odds in parlay output, not in the probability table
- Draw gate check: `if game.get('draw_prob') is not None and game.get('model_name') not in (None, 'market_implied')`

</specifics>

<deferred>
## Deferred

- validate_soccer_picks.py accuracy grader
- `--draw-threshold` CLI flag (hard-code for now)
- UCL knockout round support (group stage only for v1.4)

</deferred>
