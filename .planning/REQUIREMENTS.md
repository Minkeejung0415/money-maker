# Requirements: World Cup Tactical Matchups

**Milestone:** v1.6
**Defined:** 2026-06-21
**Status:** Active

## Tactical Data

- [x] **WCTAC-01**: Fetch recent completed national-team match summaries with formations and measurable tactical statistics from a free source.
- [x] **WCTAC-02**: Use only matches completed before the target fixture and retain a minimum sample-size gate.
- [x] **WCTAC-03**: Cache schedules and immutable event summaries under the isolated WC cache namespace.
- [x] **WCTAC-04**: Normalize possession, passing, long-ball, crossing, shot, corner, pressing-proxy, and low-block metrics into one team profile.
- [x] **WCTAC-05**: Missing or malformed tactical data fails closed without silently inventing a neutral profile.

## Tactical Comparison

- [ ] **WCTAC-06**: Compare both teams symmetrically across chance creation, control, press resistance, directness, width, set pieces, and defensive block.
- [ ] **WCTAC-07**: Produce bounded home/away attack multipliers and named matchup explanations.
- [ ] **WCTAC-08**: Formation information is descriptive context, not a deterministic prediction rule.
- [ ] **WCTAC-09**: Reversing the teams reverses comparison direction without changing absolute matchup strength.

## Model Integration

- [ ] **WCTAC-10**: Tactical multipliers adjust scoreline goal rates before market probabilities are calculated.
- [ ] **WCTAC-11**: Tactical adjustments are capped so they cannot overwhelm recent form or Elo.
- [ ] **WCTAC-12**: Scanner output shows each team’s profile, tactical edges, and probability change from the no-tactics baseline.
- [ ] **WCTAC-13**: Probability coherence, stage rules, and all existing SGP options remain valid.
- [ ] **WCTAC-14**: Focused tests and the complete regression suite pass, followed by a live multi-game audit.

## Out of Scope

- Manual claims about a coach’s intentions or unannounced lineup.
- Paid tracking data such as player coordinates, pressures, or possession chains.
- Treating formation alone as tactics; formations are context around measured behavior.
- Unbounded probability overrides or guaranteed-pick claims.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| WCTAC-01..05 | Phase 17 | Complete |
| WCTAC-06..09 | Phase 18 | Pending |
| WCTAC-10..14 | Phase 19 | Pending |

---
*Last updated: 2026-06-21 after milestone definition*
