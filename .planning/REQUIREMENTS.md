# Requirements: World Cup True SGP

**Milestone:** v1.5
**Defined:** 2026-06-21
**Status:** Active

## Goal-Market Model

- [ ] **WCSGP-01**: Produce coherent probabilities for match result, over/under 2.5 goals, and both-teams-to-score yes/no.
- [ ] **WCSGP-02**: Use cached World Cup team priors with documented neutral fallbacks and bounded goal rates.
- [ ] **WCSGP-03**: Preserve the existing WC Elo model's 1X2 probabilities as scoreline-distribution marginals.
- [ ] **WCSGP-04**: Calculate multi-leg joint probabilities from one calibrated scoreline distribution, not by multiplying correlated marginals.
- [ ] **WCSGP-05**: Reject invalid, contradictory, or stage-incompatible leg combinations.

## Market Prices and Construction

- [ ] **WCSGP-06**: Normalize 1X2, total-goals, and BTTS decimal prices while remaining backward compatible with existing moneyline overrides.
- [ ] **WCSGP-07**: Keep missing market prices unavailable; never invent default odds.
- [ ] **WCSGP-08**: Build same-match 2-3 leg combinations and report joint probability, fair odds, sportsbook odds, edge, and EV in deterministic rank order.
- [ ] **WCSGP-09**: Use 90-minute 1X2 only in group play; knockout combinations exclude 1X2 unless an explicit compatible market exists.

## Scanner and Quality

- [ ] **WCSGP-10**: `scripts/wc_scanner.py --mode sgp` prints true same-game candidates and explains missing-price or compatibility failures.
- [ ] **WCSGP-11**: Existing `--mode parlay` behavior remains available without regression.
- [ ] **WCSGP-12**: Tests cover probability coherence, joint calculations, compatibility, odds parsing, ranking, scanner routing, and the full suite.

## Out of Scope

- Player props: no dependable free World Cup player-prop odds source is available.
- Synthetic or assumed sportsbook prices.
- Cross-match combinations, which remain in classic parlay mode.
- Any claim of guaranteed profitability.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| WCSGP-01 | Phase 15 | Pending |
| WCSGP-02 | Phase 15 | Pending |
| WCSGP-03 | Phase 15 | Pending |
| WCSGP-04 | Phase 15 | Pending |
| WCSGP-05 | Phase 15 | Pending |
| WCSGP-06 | Phase 16 | Pending |
| WCSGP-07 | Phase 16 | Pending |
| WCSGP-08 | Phase 16 | Pending |
| WCSGP-09 | Phase 16 | Pending |
| WCSGP-10 | Phase 16 | Pending |
| WCSGP-11 | Phase 16 | Pending |
| WCSGP-12 | Phases 15-16 | Pending |

**Coverage:** 12/12 requirements mapped.

---
*Last updated: 2026-06-21 after milestone definition*
