# Phase 27: Projected XI Layer - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — discuss skipped)

<domain>
## Phase Boundary

Estimate starter probabilities per player, aggregate position-specific features into line scores (GK/Back/Midfield/Front) using SUM not mean, compute replacement-adjusted absence impact, and add lineup uncertainty variance bands. All output feeds Phase 32 full integration.

Deliverables:
- `alpha/engines/sports/wc_lineup.py` — `LineupProjector` class
- Integration with `WCTeamRatings` (Phase 26) or standalone feature dict
- Tests covering all 4 LINEUP requirements

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices at Claude's discretion — infrastructure phase.

Key constraints:
- LINEUP-01: Starter probability per player from national-team history, injury/suspension, fitness. No live data available — use mock/static squad data with configurable probabilities.
- LINEUP-02: Aggregate by line (GK/Back/Midfield/Front) using SUM (not mean). 11-player line scores higher than 10-player.
- LINEUP-03: Absence impact = player_value_in_role − replacement_value_in_same_role (negative delta for key player absent).
- LINEUP-04: Lineup uncertainty variance widens WDL confidence when starter probs are low.
- LINEUP-05: Back-line and midfield-triangle continuity modifiers.

Data: No live player data available mid-tournament (StatsBomb 2026 not available). Use mock squad data structure with configurable player values. The `LineupProjector` API must be clean enough for Phase 30 (Position-Specific Player Features) to plug real data in.

Design: `LineupProjector` takes a squad dict `{player_name: {role, p_start, value, replacement_value}}` and a team name. Returns `LineupFeatures` dataclass with line scores, absence impacts, uncertainty band.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `alpha/engines/sports/wc_ratings.py` — WCTeamRatings (Phase 26), get_features() pattern
- `alpha/engines/sports/wc_hybrid_model.py` — injection pattern for features
- `alpha/engines/sports/wc_calibration.py` — evaluate_model(), promotion_gate()

### Established Patterns
- Standalone class, no base class, constructor takes config params
- Static/embedded data for testing (see wc_historical_matches.py pattern)
- Tests use simple fixture dicts, not mocks

### Integration Points
- Phase 30 will populate real player values into the same squad dict structure
- Phase 32 will wire LineupProjector output into the full stacked model
- wc_scanner.py remains unchanged

</code_context>

<specifics>
## Specific Ideas

- Roles: "GK", "CB", "LB", "RB", "DM", "CM", "LW", "RW", "ST", "SS"
- Lines: GK=[GK], Back=[CB,LB,RB], Midfield=[DM,CM], Front=[LW,RW,ST,SS]
- Line score = sum of (player_value * p_start) for all players in line
- Absence impact for player X = max(0, player_value - replacement_value) — the positive loss when X is absent
- Uncertainty: std dev of p_start values across squad; high std = more certain XI
- Continuity: if 2+ CB/GK changes from reference lineup, apply -0.05 modifier

</specifics>

<deferred>
## Deferred Ideas

- Live injury API integration (no free source for international)
- Real FBref player values (Phase 30)
- Full 23-player squad data per team (Phase 30)

</deferred>
