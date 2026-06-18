# Requirements: v1.1 — World Cup Soccer Mode

*Milestone goal: Ship a full World Cup 2026 prediction stack — match outcome model, Elo-logistic predictions, and SGP builder — running on live group-stage and knockout-round data via the existing soccer_scanner.py --league wc flag.*

---

## Data Ingestion

- [ ] **INGEST-01**: User can fetch live WC 2026 fixtures from football-data.org by adding `"wc": "WC"` to `_COMP_MAP` in `football_data_client.py` and implementing `fetch_wc_games(date_from, date_to, stage)`. Returns group stage and knockout round fixtures.
- [ ] **INGEST-02**: System loads Elo ratings for all WC 2026 nations from a Kaggle 1872-2025 CSV dataset as the primary national team strength signal. Cached to `data/wc_priors.json` to avoid repeated downloads.
- [ ] **INGEST-03**: System loads StatsBomb 2018/2022 WC event data via `statsbombpy>=1.19.0` as historical player-level context for match feature enrichment. Cached to `data/.wc_cache/`.

## Match Model

- [ ] **MODEL-01**: New `wc_model.py` produces Win/Draw/Loss probabilities using a logistic Elo model with neutral-venue correction (removes the standard +100 Elo home-field boost). Never routes through `soccer_model.py`.
- [ ] **MODEL-02**: Knockout round detection gates out the Draw probability — outputs Win-to-Advance probability for the home-side nation instead for R16, QF, SF, and Final games.
- [ ] **MODEL-03**: Tournament stage metadata (`"stage": "GROUP_STAGE" | "LAST_16" | "QUARTER_FINALS" | "SEMI_FINALS" | "FINAL"`) is extracted from football-data.org fixture response and embedded in each game dict.
- [ ] **MODEL-04**: Elo vs. market divergence flag (`"elo_edge": true/false`) marks picks where model win probability disagrees with sportsbook implied odds by more than 5 percentage points.

## SGP Builder

- [ ] **SGP-01**: WC SGP builder (`wc_sgp_builder.py`) combines match Win/Advance legs across multiple WC games using WC-calibrated correlation values. Does not include player prop legs in v1.1.
- [ ] **SGP-02**: Knockout round gate — SGP builder never combines a moneyline leg with a Draw leg for the same elimination round game (Draw is invalid post-90-min settlement in knockouts).

## Scanner

- [ ] **SCAN-01**: `soccer_scanner.py` accepts `--league wc` flag and routes to the WC data pipeline (`fetch_wc_games()`), WC match model (`wc_model.py`), and WC SGP builder.
- [ ] **SCAN-02**: `--mode parlay` with `--league wc` outputs ranked WC match picks showing Elo confidence, implied EV vs. market odds, and divergence flag (`*ELO EDGE*` annotation when model disagrees with market by >5%).

## Quality

- [ ] **TEST-01**: All new WC components (`wc_model.py`, `wc_sgp_builder.py`, `wc_stats.py`, WC routes in `soccer_scanner.py`) have unit tests. Existing 535+ tests pass with zero regressions after `statsbombpy` install.

---

## Future Requirements (v1.2)

- WC player props (goals, shots, assists) — blocked on Odds API Business tier confirmation
- The Odds API `soccer_fifa_world_cup` market discovery and player prop pipeline
- WC SGP legs combining match + player prop outcomes
- Golden Boot tracker and tournament bracket visualization

## Out of Scope (v1.1)

| Feature | Reason |
|---------|--------|
| WC player props | The Odds API Business tier ($99/mo) required for WC prop markets — deferred to v1.2 |
| XGBoost WC match model | Research confirmed XGBoost underperforms logistic regression at international football data volume (only 64-128 WC games for training) |
| Correct score / BTTS markets | 15-20% vig makes these anti-features for WC |
| EPL/UCL/NBA/MLB changes | Scope is WC only for this milestone |

---

## Traceability

| REQ-ID | Phase | Status |
|--------|-------|--------|
| INGEST-01 | Phase 5 | Pending |
| INGEST-02 | Phase 5 | Pending |
| INGEST-03 | Phase 5 | Pending |
| MODEL-01 | Phase 6 | Pending |
| MODEL-02 | Phase 6 | Pending |
| MODEL-03 | Phase 6 | Pending |
| MODEL-04 | Phase 6 | Pending |
| SGP-01 | Phase 7 | Pending |
| SGP-02 | Phase 7 | Pending |
| SCAN-01 | Phase 7 | Pending |
| SCAN-02 | Phase 7 | Pending |
| TEST-01 | Phase 7 | Pending |

*Updated by roadmapper after phase assignment.*

---
*Last updated: 2026-06-18 — Phase assignments added by roadmapper*
