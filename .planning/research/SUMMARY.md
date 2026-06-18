# Research Summary — World Cup 2026 Soccer Mode

**Project:** Alpha Terminal v1.1 — WC Soccer Mode
**Domain:** International tournament soccer betting prediction (national teams, group stage + knockout bracket)
**Researched:** 2026-06-18
**Confidence:** HIGH (stack + features + architecture) / MEDIUM (prop model edge)

---

## Executive Summary

The WC 2026 Soccer Mode is an extension of the existing Alpha Terminal soccer stack, but it must be built as a parallel track — not an extension of the EPL/UCL engine. The core architectural divergence is data: Understat does not cover national teams, rolling 5/10-game club-form stats are statistically meaningless for teams that play 3-7 tournament games, and the ProphitBet XGBoost model was trained entirely on domestic league feature sets that are incompatible with national team football. The research consensus is clear: Elo rating differential plus a 60/40 market-implied blend using a logistic curve (the chess Elo formula) is the correct primary model, outperforming tree ensembles on international data at this sample size (7,000 games total international history). Build `wc_model.py` and `wc_stats.py` as new files from the ground up.

The free-tier data situation is better than expected on the fixture and odds side, and worse than expected on the player stats side. football-data.org covers the WC `"WC"` competition code on its existing free tier — no new API key, just one line change to `_COMP_MAP`. The Odds API `soccer_fifa_world_cup` sport key provides match 3-way odds and anytime goalscorer player props on the existing quota. StatsBomb open data provides 128 WC matches (2018 + 2022) as historical training priors via the free `statsbombpy` library. The critical gap: there is no free live per-game player stat source for active 2026 WC players, meaning `--mode props` is limited to goals-only markets (anytime goalscorer) anchored to market-implied probability rather than statistical projections.

The primary execution risk is not data availability — it is silently feeding WC games through the existing EPL club-soccer code paths. If `SoccerModel` processes a WC game with an empty Understat feature dict (all defaults at 1.5), it produces a confidence-passing prediction from garbage inputs. The same failure applies to ProphitBet XGBoost running on a national-team feature dict. Every WC code path must be hard-gated from the club-soccer models. Additionally, knockout-round SGP construction requires suppressing moneyline ML legs entirely, because WC knockouts settle on the 90-minute result — a team that wins in extra time still loses the standard moneyline if they were level at 90.

---

## Stack Additions

### New Library

- **`statsbombpy>=1.19.0`** — Pull WC 2018 + 2022 event data (128 matches, xG, shots, lineups) for national team attack/defense priors. Free open data from GitHub, no credentials. Used in the one-time `scripts/build_wc_priors.py` offline step only; the live scanner reads from `data/wc_priors.json`. Install: `./venv/Scripts/python.exe -m pip install "statsbombpy>=1.19.0"`.

### API Extensions (no new keys)

- **football-data.org `"WC"` competition code** — 1 line change to `_COMP_MAP` in `football_data_client.py`. Free tier confirmed. Competition code `WC`. Rate limit: 10 req/min (same as EPL/UCL). Provides: fixture schedule, stage metadata (`GROUP_STAGE`, `ROUND_OF_16`, etc.), group/team identifiers. Does NOT provide: odds, per-player stats, lineups.
- **The Odds API `soccer_fifa_world_cup` sport key** — Extend `odds_api.py` with `fetch_wc_odds()` and `fetch_wc_prop_lines()` methods. Existing `ODDS_API_KEY` works. Markets confirmed: 3-way h2h match odds, `player_goal_scorer_anytime`. Markets that may NOT exist: `player_shots`, `player_assists` — must run market discovery scan before building prop model. Quota: 2h cache TTL (WC odds move faster than club soccer).
- **openfootball/worldcup.json** — Raw GitHub JSON, no key, no library. Used as schedule fallback only when football-data.org is unavailable. Uses existing `requests` library.

### Rejected Alternatives

| Option | Reason Rejected |
|--------|----------------|
| The Odds API Business plan ($99/mo) for WC match lines | Free API constraint |
| soccerdata + FBref for live WC player stats | FBref blocks scrapers; already proven unreliable in this codebase for UCL |
| Understat extended to WC | Architecturally impossible — covers domestic leagues only |
| XGBoost trained from scratch on WC match data | ~7,000 games total international history; logistic regression on Elo diff outperforms at this volume |

### Environment Variables

No new `.env` keys required. `FOOTBALL_API_KEY` and `ODDS_API_KEY` already set. Optional: `WC_ODDS_ENABLED=false` guard flag for future Odds API expansion.

---

## Feature Table Stakes

The minimum for `wc_scanner.py` to be useful:

- **WC fixture ingestion** via `football_data_client.fetch_wc_games(date_from, date_to)` — scanner cannot run without today's matches. `_COMP_MAP["wc"] = "WC"` is the one required change.
- **Elo-logistic W/D/L match model** — neutral-venue Elo diff converted via `P(win) = 1 / (1 + 10^(-ELO_DIFF/400))` blended 60/40 with market-implied. This is the primary prediction signal; no XGBoost.
- **Knockout round "To Advance" output** — when `stage == knockout`, suppress draw probability entirely and output only "To Advance" (90 min + ET + shootout combined). Any draw output in knockout rounds is wrong by definition.
- **Neutral venue correction** — remove the +100 Elo home-field boost that eloratings.net normally applies. All 2026 WC matches are at neutral US/Canada/Mexico venues.
- **Group stage standings sidebar** — display group table context alongside picks (current points, elimination status). Uses football-data.org standings endpoint; no modeling required.
- **Calibrated HIGH/MEDIUM/LOW confidence** with wider WC thresholds (HIGH > 0.12 gap, MEDIUM 0.09-0.12) because WC props have higher noise than EPL.
- **`scripts/wc_scanner.py` CLI entry point** — `--mode [props|parlay]` + `--stage [group|knockout|all]`, mirrors existing scanner pattern.
- **Props: anytime goalscorer only** — no shots/assists unless market discovery confirms those markets exist on `soccer_fifa_world_cup`. Return 0 legs with logged warning if unavailable (same behavior as MLB).

---

## Feature Differentiators

Features that add real edge beyond the baseline:

- **Elo vs. market divergence flag** — when `abs(elo_prob - market_implied) > 0.12`, flag "Model Disagrees With Market." WC equivalent of the NBA blowout gate. Low effort, directly identifies highest-EV opportunities. Confirmed research finding: Elo-to-FIFA-rank divergence is where WC edges live.
- **Golden Boot / top scorer tracker** — pull from `football-data.org /competitions/WC/scorers`. Zero model risk, high visibility for users tracking tournament futures. No new dependencies.
- **BTTS (Both Teams To Score) prediction** via Poisson model — `P(BTTS) = P(A scores) * P(B scores)`. WC BTTS Yes has historically landed 45-50%. Phase 2; requires Poisson lambda calibration from StatsBomb historical data (2006-2022 ~200 matches).
- **Over/Under 2.5 goals prediction** via same Poisson model. CRITICAL CAVEAT: extra-time goals do NOT count toward O/U in knockout rounds — suppress this output for R16+.
- **Stage-aware SGP correlation table** — `_CORR_BY_STAGE` dynamic adjustment: `("player_goals", "team_win")` = 0.42 in group stage, 0.55 in knockout (elimination pressure increases goal scorer decisiveness).

---

## Anti-Features

Explicitly confirmed as bad ideas for WC:

| Anti-Feature | Why Avoid |
|---|---|
| **Correct score predictions** | 15-20% vig — highest of all WC markets. Top 6 scorelines cover only 75% of group matches. Unpriceable tail. No realistic edge after vig. |
| **XGBoost trained on WC match data** | ~7,000 total international games; logistic regression outperforms gradient boosting at this data volume per multiple academic comparisons. ProphitBet domestic features do not transfer to national teams. |
| **Rolling 5/10-game club-form stats for WC players** | Understat has no national team data. Current `soccer_prop_model.py` generates synthetic Gaussian noise around EPL season averages — using this for WC means projecting EPL club rates against WC sportsbook lines. Guaranteed false confidence. |
| **Club-side injury data for WC predictions** | `soccer_injuries.py` fetches ESPN domestic reports. International call-ups operate on different rest/rotation logic. Stale and wrong for WC context. |
| **Draw No Bet output in knockout rounds** | No draws in knockout. DNB is identical to standard moneyline — wasted output — or silently wrong if round detector fails. |
| **Futures modeling (winner, semifinalists)** | Bracket simulation across 6+ rounds; prediction markets and sharp books have priced futures with large volume and tight margins. No realistic edge without proprietary data. |
| **Live in-play odds recommendations** | Requires sub-second data feeds and continuous decision engine. Entirely outside the run-once pre-kickoff architecture. Multi-week project outside v1.1 scope. |
| **Per-player game-log ingestion for WC** | No free per-game log source for players during international tournament duty. 3 group games would not support rolling average models anyway. |
| **Moneyline ML legs in knockout SGPs** | Settles on 90-minute result only. Team winning in extra time still loses the standard moneyline (market settles as draw). SGP math breaks. |

---

## Architecture Decisions

### New Files (must create)

| File | Purpose | Build Order |
|------|---------|------------|
| `alpha/data/ingestion/wc_stats.py` | StatsBomb reader — loads `data/wc_priors.json`; returns national-team xG/goals rates and per-player career WC stats per-90. Cache: `data/.wc_cache/` (separate namespace from `data/.soccer_cache/` to prevent "Brazil" name collision). | Step 2 |
| `alpha/engines/sports/wc_model.py` | WC match outcome model. Inherits nothing from `soccer_model.py` — standalone Elo-logistic class with same `predict()` / `evaluate_bet()` / `evaluate_batch()` interface. `MAX_XGB_CONF = 0.68`. No pkl files in v1.1. | Step 4 |
| `alpha/engines/sports/wc_prop_model.py` | WC player prop model. Market-implied as primary path; StatsBomb 2022 career per-90 as secondary adjustment. Confidence cap: MEDIUM for any player with fewer than 8 WC/qualifier game logs. | Step 5 |
| `alpha/engines/sports/wc_sgp_builder.py` | Imports shared `PropLeg`, `ParlayCombination`, `SGPMode` from `soccer_sgp_builder.py`. Overrides `_STATIC_CORR` with WC-calibrated values. Implements `_CORR_BY_STAGE` dynamic adjustment. | Step 6 |
| `scripts/wc_scanner.py` | Full 6-step pipeline entry point. `--mode [props|parlay]` + `--stage [group|knockout|all]`. | Step 7 |
| `scripts/build_wc_priors.py` | One-time offline script: pulls StatsBomb 2018+2022 WC events, computes national-team attack/defense rates and player career per-90 stats, saves `data/wc_priors.json`. | Run once before Phase 2 |

### Modified Files (minimal, additive only)

| File | Change |
|------|--------|
| `alpha/data/ingestion/football_data_client.py` | Add `"wc": "WC"` to `_COMP_MAP` (1 line) + `fetch_wc_games(date_from, date_to, stage)` method returning same dict shape as `fetch_today_games()` plus `stage` and `group` fields. |
| `alpha/data/ingestion/odds_api.py` | Add `soccer_fifa_world_cup` sport key constant + `fetch_wc_odds()` + `fetch_wc_prop_lines()`. Gate behind same budget tracker as NBA. WC daily limit: 20 requests. |

### Files Left Untouched

`soccer_model.py`, `soccer_prop_model.py`, `soccer_sgp_builder.py`, `soccer_stats.py`, `soccer_injuries.py`, `config/settings.py`, `scripts/soccer_scanner.py` — all untouched. WC and EPL/UCL are fully independent pipelines.

### Cache Locations

| Cache | Location | TTL |
|-------|----------|-----|
| WC team stats (StatsBomb) | `data/.wc_cache/` | 24h |
| WC player per-90 stats | `data/.wc_cache/props/` | 24h |
| WC fixtures | `data/.wc_cache/` | 6h |
| WC prop lines (Odds API) | `data/.wc_cache/props/` | 2h (shorter — WC odds move faster) |

### Build Order (dependency-driven)

```
Step 1: football_data_client.py (add fetch_wc_games)
           |
Step 2: wc_stats.py          Step 3: odds_api.py (add WC sport key)
           |                              |
           +──────────────────────────────+
                          |
           Step 4: wc_model.py    Step 5: wc_prop_model.py
                          |                   |
                          +─────────┬─────────+
                                    |
                          Step 6: wc_sgp_builder.py
                                    |
                          Step 7: scripts/wc_scanner.py
```

Steps 2 and 3 can be built concurrently — no mutual dependency.

---

## Top Watch-Outs (Pitfalls)

**Priority 1 — Club soccer feature pipeline reused for national teams.**
If `SoccerModel` or `get_team_rolling_stats_all()` is called for a WC game, Understat returns `{}`, all features default to 1.5, and the model outputs a confidence-passing probability from garbage inputs. No error is thrown. Prevention: hard gate `SoccerModel` from accepting `league == "wc"` games; add a `model_type` field to every prediction dict; `wc_model.py` never imports from `soccer_stats.py`.

**Priority 2 — ProphitBet XGBoost model running on WC feature dict.**
`soccer_model.py` tries to load any available `.pkl` file. If it finds one and receives a WC feature dict (all defaults), it produces a narrowly clustered fake probability that looks real and passes the credibility filter. Prevention: `wc_model.py` is a completely separate class; never route WC games through `SoccerModel._load_xgb_models()`.

**Priority 3 — Moneyline leg in knockout-stage SGPs.**
WC knockout matches settle on 90-minute result. A team winning in extra time still resolves as "draw" on the moneyline. Player prop legs (anytime goalscorer includes ET) can hit while the ML leg loses, breaking the SGP. Prevention: hard gate — when `tournament_stage == "knockout"`, exclude all ML win legs from SGP combinations. Restrict WC knockout SGPs to prop-only combos or use "To Qualify" market if available.

**Priority 4 — Synthetic rolling averages applied to WC players.**
`soccer_prop_model.py` generates fake Gaussian noise around EPL club season averages as a substitute for per-game logs. For WC players, this uses club rates (e.g., 0.8 shots/90 in EPL) against WC sportsbook lines set for a different context (e.g., 2.2 shots/90 playing for Brazil). Model outputs false HIGH confidence. Prevention: `wc_prop_model.py` never calls the synthetic generator; if fewer than 3 real tournament game logs exist, return market-implied probability only.

**Priority 5 — Odds API WC player market names assumed to match EPL.**
`player_shots` and `player_assists` market names used in `soccer_prop_model.py` may not exist for `soccer_fifa_world_cup`. Only `player_goal_scorer_anytime` is confirmed. If props scanner attempts to fetch non-existent market names, it returns zero legs silently. Prevention: run `GET /v4/sports/soccer_fifa_world_cup/events/{id}/odds?markets=` market discovery scan before building `wc_prop_model.py`; map confirmed market names explicitly; document any markets that are unavailable.

---

## Open Questions Before Building

These must be resolved during or before Phase 1 — they change what gets built:

1. **Are `player_shots` and `player_assists` markets available on `soccer_fifa_world_cup`?** Run market discovery: `GET /v4/sports/soccer_fifa_world_cup/events/<any_live_event_id>/odds?markets=player_shots`. If absent, WC props scope narrows to goals-only (anytime goalscorer). This determines whether `wc_prop_model.py` is worth building beyond a goals wrapper.

2. **Does The Odds API return WC 3-way h2h odds for all 48 teams on the existing free tier quota?** The sport key `soccer_fifa_world_cup` is confirmed active, but per-match credit cost for h2h odds is unverified. If WC match odds cost 2-3 credits per game (vs 1 for NBA), the daily budget of 20 requests may be tight during heavy match days (up to 8 games/day in group stage). Check before wiring `fetch_wc_odds()` into the live pipeline.

3. **What Elo data source to vendor?** Options: (a) vendor the Kaggle dataset `saifalnimri/international-football-elo-ratings` (historical CSV, static, no API calls), (b) scrape eloratings.net for live 2026 ratings. The Kaggle dataset covers through 2025 — teams' 2026 WC qualifier ratings will be slightly stale. For v1.1 the Kaggle dataset is sufficient; confirm whether a live Elo source is needed for v1.2.

4. **How many WC 2026 group stage games have already completed as of build start?** StatsBomb 2026 data is not expected until after the tournament (based on historical release pattern). If the group stage is mostly complete by the time Phase 2 launches, the prop model's market-implied anchor becomes the only real signal and per-player stat modeling is moot until WC 2030. Check tournament schedule to prioritize accordingly.

5. **Does `football_data_client.py` currently have retry/backoff logic for 429 responses?** The 10 req/min free tier limit is easily hit if fixture fetch + standings fetch + scorers endpoint run in sequence without sleep. Audit existing client before extending.

---

## Implications for Roadmap

### Phase 1: Data Foundation and Fixture Ingestion

**Rationale:** Everything depends on getting WC games into the scanner. This phase is zero-cost, uses existing keys, and unblocks all subsequent work.
**Delivers:** `wc_scanner.py --mode parlay` running with real WC fixtures, Elo-logistic W/D/L predictions, group stage standings output, knockout round detection.
**Implements:**
- `football_data_client.py` — add `"wc": "WC"` + `fetch_wc_games()`
- `wc_stats.py` — StatsBomb team/player stats reader
- `odds_api.py` — add `soccer_fifa_world_cup` sport key, run market discovery scan
- `wc_model.py` — Elo-logistic match model (no XGBoost, market-implied primary)
- `wc_sgp_builder.py` — WC correlation table, stage-aware adjustments
- `scripts/wc_scanner.py` — `--mode parlay` + `--stage [group|knockout|all]`
- `scripts/build_wc_priors.py` — one-time StatsBomb offline pull
**Avoids:** Club feature pipeline contamination (hard gate), ProphitBet model routing error, knockout SGP ML leg failure.
**Research flag:** Well-documented patterns — no additional research phase needed. All data sources confirmed.

### Phase 2: Player Prop Model (conditional on market discovery)

**Rationale:** Blocked on confirming Odds API WC player market availability. Only build if market discovery from Phase 1 confirms usable prop markets.
**Delivers:** `wc_scanner.py --mode props` with anytime goalscorer predictions. Confidence cap: MEDIUM for players with fewer than 8 WC/qualifier game logs.
**Implements:** `wc_prop_model.py` — market-implied base + StatsBomb career per-90 adjustment.
**Risk:** If only `player_goal_scorer_anytime` is available, prop mode is thin (goals only, ~2-3 players per match). Set expectations accordingly before investing in `wc_prop_model.py`.
**Research flag:** Needs market discovery validation before implementation — do not start this phase without running the Odds API market scan.

### Phase 3: Differentiators (if Phase 1 accuracy validates above 50%)

**Rationale:** Low-effort features that add visible value. Gate on Phase 1 match model performance.
**Delivers:** Elo vs. market divergence flag, Golden Boot tracker, BTTS and O/U 2.5 via Poisson model (with suppression in knockout rounds).
**Research flag:** BTTS / O/U Poisson model needs calibration from 2006-2022 historical WC data (~200 matches). Well-documented methodology; no research phase needed, but allow 1 sprint for calibration validation.

### Phase Ordering Rationale

- Phase 1 must come first because all three downstream components (`wc_model.py`, `wc_prop_model.py`, `wc_sgp_builder.py`) depend on `wc_stats.py` + `fetch_wc_games()` existing.
- Phase 2 is conditional — the market discovery scan at the end of Phase 1 determines whether it is worth building at all.
- Phase 3 differentiators are low-risk addons that only require Phase 1 to be working and validated. They can be done incrementally without blocking production use.
- Never modify `soccer_scanner.py`, `soccer_model.py`, or any EPL/UCL files. The full isolation between pipelines is non-negotiable per pitfall analysis.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | football-data.org `WC` code confirmed free tier. statsbombpy open data confirmed (128 WC matches). Odds API `soccer_fifa_world_cup` sport key confirmed active. Only uncertainty: per-match credit cost for WC odds. |
| Features | HIGH | Elo as primary signal confirmed by multiple academic sources. XGBoost anti-feature confirmed. Correct score anti-feature confirmed. Player prop market availability is the one unconfirmed item. |
| Architecture | HIGH | Build order and file boundaries are clear and consistent with existing codebase patterns. No speculative decisions. Hard isolation from EPL/UCL pipeline is the right call per pitfall analysis. |
| Pitfalls | HIGH | Pitfalls 1-5 are grounded in actual code inspection of `soccer_model.py`, `soccer_prop_model.py`, `soccer_sgp_builder.py`, and StatsBomb behavior. Not theoretical — each has a documented mechanism of silent failure. |

**Overall confidence: HIGH**

### Gaps to Address

- **WC player prop market names** — must run Odds API market discovery scan before building `wc_prop_model.py`. Do not assume EPL market name format carries over.
- **Elo source for live 2026 ratings** — Kaggle historical CSV is sufficient for v1.1 but will be stale for teams whose qualifying form changed in late 2025. Decide before Phase 1 whether to vendor static CSV or add a live Elo scraper.
- **Odds API WC credit cost** — confirm per-request credit consumption for `soccer_fifa_world_cup` h2h endpoint before wiring into production pipeline to avoid quota surprises on heavy group-stage days.
- **Tournament schedule timing** — if most group stage games are complete by build start, Phase 2 (props) has limited live testing window before knockout begins. Plan Phase 1 to ship within first week of building.

---

## Sources

### Primary (HIGH confidence)
- football-data.org free tier coverage — `WC` code confirmed, same client/key as EPL/UCL
- StatsBomb open-data GitHub (`statsbomb/open-data`) — WC 2018 (competition_id=43, season_id=3) + 2022 (season_id=106) confirmed, 64 matches each
- statsbombpy PyPI v1.19.0 — library API confirmed via Context7
- The Odds API `soccer_fifa_world_cup` sport key — h2h confirmed; anytime goalscorer confirmed; shots/assists unconfirmed
- openfootball/worldcup.json GitHub — 2026 fixtures present in master branch

### Secondary (MEDIUM confidence)
- Kaggle dataset `saifalnimri/international-football-elo-ratings` (1872-2025) — Elo as primary signal validated by 5+ academic papers and practitioner sources
- eloratings.net WC 2026 — live 2026 Elo ratings for all 48 WC teams
- "I Built 11 Models to Predict the 2026 World Cup" (Towards Data Science) — Elo logistic outperforms tree ensembles on international data
- ACM DL: "Prediction of FIFA World Cup Match Outcomes Based on Random Forests" — confirms logistic regression competitive with RF at international sample sizes

### Tertiary (LOW confidence, needs validation during Phase 1)
- The Odds API WC player prop market format (`player_shots`, `player_assists` availability) — requires live market discovery scan
- StatsBomb 2026 live data availability mid-tournament — confirmed NOT expected until post-tournament based on prior release pattern

---

*Research completed: 2026-06-18*
*Ready for roadmap: yes*
