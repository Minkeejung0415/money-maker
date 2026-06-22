# Milestones

## v1.6 World Cup Tactical Matchups (Shipped: 2026-06-22)

**Phases completed:** 3 phases, 3 plans

**Key accomplishments:**

- Cached recent national-team tactical profiles from ESPN match summaries
- Formation, possession, passing, directness, width, pressing-proxy, set-piece, and defensive-block comparison
- Symmetric and explainable tactical attack multipliers capped to 0.90-1.10
- Tactical Elo and scoreline-rate integration with no-tactics baseline deltas
- Pacific/UTC adjacent-date team resolution and fail-closed sample gates
- Live four-game audit produced 100 coherent SGP probabilities; 777 tests passed

---

## v1.5 World Cup True SGP (Shipped: 2026-06-21)

**Phases completed:** 2 phases, 2 plans

**Key accomplishments:**

- Scoreline distribution calibrated to the existing WC Elo model's 1X2 probabilities
- Coherent over/under 2.5 and BTTS probabilities with exact correlated joint evaluation
- Normalized real-price contract for 1X2, totals, and BTTS without default odds
- Stage-safe 2-3 leg same-match builder with knockout 1X2 protection
- `wc_scanner.py --mode sgp` added while classic parlay behavior remains intact
- 753-test full regression suite passed

---

## v1.4 Soccer Mode Upgrade (Shipped: 2026-06-21)

**Phases completed:** 3 phases, 6 plans, 10 tasks

**Key accomplishments:**

- Football-data.org team history now produces cached form, H2H, rest, and numeric team-ID features for EPL/UCL models
- Daily Club Elo ratings and cached FBref set-piece features now feed EPL/UCL model development without touching WC data
- Draw leg support added to SoccerSGPBuilder via D-11 EV gate: qualifies draw legs from real models only (EV > 5%) and pools them into classic parlay combos with same-game win+draw conflict guard
- Soccer scanner now routes EPL and UCL games to their independent models, displays H/D/A probabilities, and marks draw legs visibly

---
