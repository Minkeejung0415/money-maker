# Feature Landscape: World Cup 2026 Soccer Mode

**Domain:** International tournament soccer betting prediction (national teams, single-elimination bracket)
**Researched:** 2026-06-18
**Milestone:** v1.1 — World Cup Soccer Mode
**Existing engine baseline:** `soccer_scanner.py` / `soccer_model.py` / `soccer_prop_model.py` / `soccer_sgp_builder.py`

---

## Context: How WC Differs From EPL/UCL

The existing soccer engine was designed for club leagues with:
- Rich per-game rolling stats from Understat (EPL-only)
- A persistent team history across a 38-game season
- Known home and away designations tied to league standings
- Market-implied fallback when XGBoost lacks a model file

World Cup changes four fundamental assumptions:

| Assumption | EPL/UCL | World Cup |
|---|---|---|
| Data volume | 38 games/season per team | 3-7 games per tournament team |
| Statistical source | Understat per-game logs | None native — must use Elo + FIFA rank + historical results |
| Home advantage | Coded into features | Does not exist (neutral venues throughout) |
| Bracket structure | Round-robin league | Group stage (3 games) + single-elimination knockout |
| Player prop odds | No free source (existing gap) | The Odds API Business tier covers WC props |
| Draw meaning | Draw bets skipped (illiquid) | Draws matter in group stage for points; irrelevant in knockout |

---

## Table Stakes

Features users expect. Missing = the WC scanner feels incomplete or produces wrong output.

| Feature | Why Expected | Complexity | WC-Specific Notes | Depends On |
|---|---|---|---|---|
| **WC fixture ingestion** | Scanner cannot run without knowing today's games | Low | `football-data.org` free tier includes FIFA World Cup (competition code already used in soccer_scanner.py via `FOOTBALL_API_KEY`). Rate limit: 10 req/min — sufficient for WC cadence (3-6 games/day). Backup: `openfootball/worldcup.json` on GitHub, free, no key required. | football-data.org client already in `alpha/data/ingestion/` |
| **Win/Draw/Loss match model (neutral venue)** | Core scanner output — every match needs a W/D/L prediction | Medium | Must remove home-field advantage from `_build_game_features()`. Elo rating differential (from eloratings.net or vendored Kaggle dataset) replaces rolling `goals_for`/`xG_for` as the primary strength signal. FIFA ranking is a secondary signal but weaker predictor than Elo per academic literature. | New `wc_match_model.py` — mirrors `soccer_model.py` but substitutes Elo diff for club rolling stats |
| **Elo-based team strength signal** | National teams play too few games for rolling stats to have predictive value; Understat does not cover national teams at all | Medium | eloratings.net maintains current ratings for all 48 WC teams. A Kaggle dataset (`saifalnimri/international-football-elo-ratings`) covers 1872-2025 history and can be vendored. Elo diff alone explains approximately 65% of international match outcome variance — far stronger than FIFA ranking as a predictor. | `alpha/data/ingestion/wc_elo.py` (new file) |
| **Knockout round "To Advance" output** | Knockout games have no draw: Winner-or-penalties only. Emitting draw predictions in R16+ produces guaranteed bad picks. | Low | Detect round from football-data.org fixture metadata. When `round_type == knockout`, suppress draw probability and output only "To Advance" (winner across 90 min + ET + shootout). This is a hard behavioral difference from the existing scanner. | Round-type detection from fixture data |
| **Group stage standings display** | Bettors want to know current table context (elimination pressure, clinch scenarios) alongside each pick | Low | football-data.org provides live standings per group. Display as a header block in scanner output: "Group A — France 6pts (clinched), Senegal 3pts, Morocco 1pt, Uruguay 0pts (eliminated)". No modeling needed. | football-data.org standings endpoint |
| **WC player prop predictions** | Goals and shots props are available on every WC match and are the core prop workflow users already know from NBA/soccer scanners | High | The Odds API Business tier ($99/mo) covers WC player props. Markets confirmed live for WC 2026: `anytime_goalscorer`, `player_shots_on_target`, `player_shots`. No per-game rolling stats exist for national team players (Understat does not cover international duty). Model must use market-implied as base anchor + Elo team attack multiplier. See sparse data section below. | `wc_prop_model.py` (new) + The Odds API Business tier (cost gate — verify before building) |
| **Calibrated confidence output** | Every pick needs HIGH/MEDIUM/LOW tier so users know which legs are safe for SGP inclusion | Low | Reuse existing gap-based confidence system from `soccer_prop_model.py`. Recommend wider thresholds than EPL because WC props have higher noise: HIGH > 0.12 gap, MEDIUM 0.09-0.12, LOW < 0.09 (exclude from SGP combos). | `wc_prop_model.py` |
| **`scripts/wc_scanner.py` entry point** | Users expect the same CLI pattern as `soccer_scanner.py` and `sgp_scanner.py` | Low | Flags: `--mode props`, `--mode parlay`, `--round group` or `--round knockout`. Mirrors existing scanner pattern exactly. | All of the above |

---

## The Sparse Data Problem — Required Methodology

This is the most critical research finding for the WC match model. Standard club-league approaches fail hard.

**Do NOT use rolling 5/10-game logs** — national teams play 6-15 games per year total, and only 3 group stage WC games exist before knockout. The existing `_weighted_avg()` from `soccer_prop_model.py` (last 5 + last 10 games) produces near-random outputs at this data volume.

**Validated approaches, in order of effectiveness:**

1. **Elo rating differential** — Single strongest predictor. Convert Elo diff to win probability using the logistic curve: `P(win) = 1 / (1 + 10^(-ELO_DIFF/400))`. This is the chess formula adapted for soccer and is the basis of eloratings.net's published system. For WC specifically, apply a neutral-venue correction: remove the built-in +100 Elo home-field boost that eloratings.net normally applies.

2. **Market-implied probability blend** — The bookmaker line for WC is extremely informative because sharp books have priced in squad depth, injuries, preparation camp results, and tournament form that no public model can fully replicate. Blend: 60% Elo-derived probability + 40% market-implied as the base estimate. This mirrors the existing `MARKET_BLEND` constant in `soccer_model.py`, just with inverted weights.

3. **FIFA ranking as secondary signal** — Weaker than Elo but captures recent competitive context (qualifying campaigns). Use as a tiebreaker when Elo diff is small (< 50 points, near-equal teams). Do not use as primary signal.

4. **Poisson goal model** — Optional enhancement for Phase 2. Fit lambda_attack and lambda_defense from historical WC results (2006-2022, approximately 200 matches). Mean WC goals/game is 2.5 (range 2.27-2.71 across recent tournaments). Use team Elo to scale attack and defense strength. Enables Over/Under and BTTS market predictions. Mark as Phase 2.

**Do NOT train XGBoost from scratch** — Total international match history is approximately 7,000 games, which is below the threshold for reliable XGBoost with meaningful features. Multiple academic studies confirm that logistic regression on Elo diff outperforms gradient boosting on international football data at this sample size. The existing ProphitBet XGBoost model was trained on domestic league data and is not transferable to national teams.

---

## Differentiators

Features that add meaningful value beyond the baseline W/D/L + prop scanner.

| Feature | Value Proposition | Complexity | WC-Specific Notes | Depends On |
|---|---|---|---|---|
| **Elo vs. market divergence flag** | Identifies matches where the model disagrees significantly with book odds — highest-EV opportunities | Low | Research confirms that Elo-to-FIFA-rank divergence is where WC edges live (e.g., a team ranked Elo #19 but FIFA #28). If `abs(elo_prob - market_implied) > 0.12`, flag as "Model Disagrees With Market" in output. WC equivalent of the NBA blowout gate. | Elo ingestion + market odds from Odds API or football-data.org |
| **BTTS (Both Teams To Score) prediction** | High-liquidity WC market, more predictable than correct score, available on every match | Medium | Poisson model: `P(BTTS Yes) = P(team_A scores >= 1) * P(team_B scores >= 1)`. Uses Elo-adjusted attack/defense lambdas. WC BTTS Yes has historically landed around 45-50%. The model has edge here when both teams have high Elo attack ratings. Phase 2 (requires Poisson calibration first). | Poisson goal model |
| **Over/Under 2.5 goals prediction** | Very high liquidity, available on every WC match, matches the 2.5 mean | Medium | Same Poisson model: `P(total >= 3)`. Structural edge when both teams have offensive Elo strength above league mean AND neither team is playing for a draw (early group games, not late qualification games). Critical caveat: extra-time goals do NOT count toward O/U in knockout rounds — must suppress this output for R16+. Phase 2. | Poisson goal model |
| **Golden Boot / top scorer tracker** | Tournament-wide futures market with very high public interest; low engineering cost | Low | Display current top scorer standings alongside today's games. No modeling needed — pull from football-data.org `/competitions/WC/scorers` endpoint. Present as a sidebar to scanner results. Zero model risk. | football-data.org scorers endpoint |
| **Group advancement probability** | "What are France's odds of advancing from Group D?" — strategic context for futures bets | Medium | Monte Carlo simulation: 10,000 iterations of remaining group fixtures using W/D/L probabilities. Output advancement probability per team per group. Useful late in group stage when some teams have played 2 of 3 games. Phase 2. | WC match model + remaining fixture schedule |
| **Asian Handicap recommendation** | When moneyline favorite is very short (e.g., Brazil -400), AH -0.5 or -1 provides better EV | Low | When `model_prob > 0.70`, compute AH EV alongside moneyline EV and recommend whichever has better implied edge. However: football-data.org does not carry AH odds. Requires The Odds API (h2h covers moneyline, not AH) or SportsGameOdds API. Flag as conditional on odds source. | AH-capable odds source (not currently in stack) |

---

## Anti-Features

Features to explicitly NOT build. These have specific failure modes in the WC context.

| Anti-Feature | Why Avoid | What To Do Instead |
|---|---|---|
| **Correct score prediction** | Correct score book carries 15-20% vig — highest of all WC markets. Top 6 scorelines (1-0, 2-1, 2-0, 3-0, 1-1, 0-0) cover only 75% of group matches; the tail is enormous and unpriceable. A Poisson model will produce output but has no realistic edge after vig. Chasing exotic scorelines is the single most cited bettor mistake. | Use Over/Under 2.5 and BTTS instead — same underlying model, much higher liquidity, lower vig |
| **XGBoost trained on WC match data** | Total international match history is ~7,000 games. XGBoost with standard features will overfit badly. Academic papers directly comparing approaches at this data volume show logistic regression outperforms tree ensembles. The existing `_load_xgb_models()` in `soccer_model.py` looks for ProphitBet domestic league models — those feature sets do not generalize to national teams. | Elo-logistic model. No XGBoost. |
| **Rolling 5/10-game club-form stats for WC** | Understat covers domestic leagues only — it has no national team data. The current `soccer_prop_model.py` synthesizes fake gaussian noise around a season average (lines 191-195) to pad the rolling window. For WC that would mean generating fake data around a player's EPL per-90 average and using it to predict international performance — these are different playing contexts, different formation, different teammates. | Use market-implied as the base anchor for WC player props; apply team Elo attack multiplier as the only adjustment |
| **Club-side injury impact on WC predictions** | `soccer_injuries.py` fetches ESPN domestic injury reports. International call-ups mean players may rest, be rested by the coach, or play limited minutes regardless of club fitness status. A player "healthy" for Arsenal but selected to play 60 minutes for England introduces a different injury/rest signal entirely. The existing `get_team_injury_impact()` data will be stale and wrong. | Apply a pre-game lineup flag when confirmed lineups are released via football-data.org. Do not use club injury data for national team props. |
| **Draw No Bet output in knockout rounds** | No draws exist in knockout (R16 onward). DNB becomes a regular moneyline in knockout rounds, so any "Draw No Bet" recommendation is either identical to the standard moneyline (wasted output) or quietly wrong if the round detector fails. | Hard gate: if `round_type == knockout`, output only "To Advance" predictions. No DNB. Document this in scanner help text. |
| **Futures modeling (winner, semifinalists)** | Tournament-level futures require bracket simulation across 6+ rounds. High computation, very high variance. Prediction markets (Polymarket) and sharp sportsbooks have already priced futures with large trading volume and tight margins — there is no realistic edge against them without proprietary information. | Display existing market odds as context only. Do not generate model-based futures odds. |
| **Live in-play odds recommendations** | In-play WC markets require sub-second data feeds and a decision engine that runs continuously. The Odds API (even Business tier) adds latency. The existing run-once-before-kickoff architecture is not suited to in-play. Any attempt to retrofit this is a multi-week project outside the v1.1 scope. | Pre-game only. State this explicitly in scanner help text and README. |
| **Per-player game-log ingestion for WC** | There is no free per-game log source covering players during international tournament duty. FBRef and Understat are domestic. Building a scraper for WC player game logs is significant engineering work and the data volume (3 group games) would not support the weighted rolling average model anyway. | Market-implied anchor + team Elo attack multiplier is the correct WC prop approach. |

---

## Feature Dependencies

```
WC fixture ingestion (football-data.org — free tier, key already in .env)
    |
    +-- WC match model (Win/Draw/Loss or To Advance)
    |       |
    |       +-- Elo ingestion — wc_elo.py [NEW FILE]
    |       |       Source: eloratings.net scrape or vendored Kaggle dataset
    |       |
    |       +-- Knockout round detection (from fixture round metadata)
    |       |
    |       +-- Elo vs. market divergence flag [differentiator]
    |       |
    |       +-- Group stage standings sidebar
    |               |
    |               +-- Group advancement probability [Phase 2 differentiator]
    |
    +-- WC player prop model
    |       |
    |       +-- The Odds API Business tier (COST GATE — verify before building)
    |       |       Markets: anytime_goalscorer, player_shots_on_target, player_shots
    |       |
    |       +-- Market-implied base + Elo team attack multiplier
    |
    +-- WC SGP builder
            |
            +-- Match leg + player prop leg correlation table
            +-- Reuse soccer_sgp_builder.py correlation logic

Poisson goal model [Phase 2]
    +-- BTTS prediction
    +-- Over/Under 2.5 prediction

Golden Boot tracker [standalone, no model dependency]
    +-- football-data.org /competitions/WC/scorers endpoint
```

---

## MVP Recommendation

Build in this exact order. Phase 2 only if Phase 1 validates above 50% match prediction accuracy.

**Phase 1 — Match model (no external cost beyond existing .env keys)**
1. WC fixture ingestion via football-data.org (free, `FOOTBALL_API_KEY` already in .env)
2. Elo data ingestion from Kaggle dataset or eloratings.net (free — vendor the dataset)
3. `wc_match_model.py`: Elo-logistic W/D/L + 60/40 market blend + neutral venue correction
4. Knockout round detection: suppress draw output, emit "To Advance"
5. Group stage standings sidebar in scanner output
6. `scripts/wc_scanner.py --mode parlay`

**Phase 2 — Player props (requires Odds API Business tier)**
1. Confirm The Odds API Business tier is active and WC sport key is available
2. `wc_prop_model.py`: market-implied base + Elo attack multiplier per team
3. Markets: `anytime_goalscorer`, `player_shots_on_target`
4. WC SGP builder combining match leg + player prop leg
5. `scripts/wc_scanner.py --mode props`

**Phase 3 — Differentiators (if time and accuracy warrant)**
1. Elo vs. market divergence flag (low effort, high value)
2. Golden Boot tracker (low effort, high visibility)
3. BTTS and Over/Under 2.5 via Poisson model (medium effort, requires historical calibration)

**Defer entirely:**
- Correct score predictions
- Asian Handicap (requires new odds source)
- Group advancement Monte Carlo
- In-play recommendations

---

## Sources

- [The Odds API — Business tier covers WC 2026 props](https://the-odds-api.com/)
- [football-data.org — Free tier confirmed to include FIFA World Cup](https://www.football-data.org/)
- [openfootball/worldcup.json — Free fixture data, no key, covers WC 2026](https://github.com/openfootball/worldcup.json)
- [World Football Elo Ratings — eloratings.net](https://eloratings.net/2026_World_Cup)
- [International Football Elo Ratings 1872-2025 — Kaggle dataset](https://www.kaggle.com/datasets/saifalnimri/international-football-elo-ratings)
- [2026 FIFA World Cup Historical Elo Ratings — Kaggle](https://www.kaggle.com/datasets/afonsofernandescruz/2026-fifa-world-cup-historical-elo-ratings)
- [I Built 11 Models to Predict the 2026 World Cup — Towards Data Science](https://towardsdatascience.com/i-built-11-models-to-predict-the-2026-world-cup-they-crown-four-different-champions/)
- [Footlab Elo Rankings WC 2026 — Footlab Data](https://footlab-data.com/en/world-cup/article/footlab-elo-rankings-48-teams-world-cup-2026-en)
- [World Cup 2026 Prop Bets for Every Match — Dimers](https://www.dimers.com/best-props/swc)
- [World Cup 2026 Props: Player and Team Markets Explained — Oddspedia](https://oddspedia.com/insights/football/world-cup-2026-prop-markets)
- [World Cup Player Props Explained: Goals, Assists & Cards Guide — MyBookie](https://www.mybookie.ag/sports-betting-guide/world-cup-player-props-explained/)
- [2026 FIFA World Cup Betting Strategies — CBS Sports](https://www.cbssports.com/betting/news/2026-fifa-world-cup-betting-strategies/)
- [World Cup Correct Score Betting Tips and Strategy — FreeBets](https://www.freebets.com/guides/world-cup-correct-score-betting-tips-strategy/)
- [World Cup Best Props for Tuesday June 16 2026 — Lineups](https://www.lineups.com/betting/world-cup-best-player-prop-picks-odds-predictions-for-tuesday-june-16-2026/)
- [Best World Cup 2026 APIs for Fixtures, Scores, Stats and Odds — TheStatsAPI](https://www.thestatsapi.com/blog/best-world-cup-2026-apis)
- [Prediction of FIFA World Cup Match Outcomes Based on Random Forests — ACM DL](https://dl.acm.org/doi/fullHtml/10.1145/3696500.3696512)

---

## Confidence Assessment

| Area | Confidence | Reason |
|---|---|---|
| WC player prop markets available (goals, shots) | HIGH | Tournament is live as of research date. Markets confirmed active on DraftKings, FanDuel, Bet365, Dimers for WC 2026 per-match. |
| Elo as primary national team strength signal | HIGH | Consistent finding across 5+ academic papers and practitioner sources. Elo diff is the standard in international football prediction. |
| football-data.org WC fixture coverage (free tier) | HIGH | Free tier confirmed to include FIFA World Cup competition. Used by existing soccer scanner for football-data.org client. |
| The Odds API Business tier WC prop coverage | MEDIUM | Business tier described as covering WC, but exact WC sport key and prop market endpoint names need verification before building. Do not start prop model until this is confirmed. |
| XGBoost anti-feature | HIGH | Multiple academic comparisons at international football data volume confirm logistic/Poisson outperforms tree ensembles. Not a close call. |
| Correct score anti-feature | HIGH | Multiple practitioner sources unanimously flag high vig and low accuracy. BTTS and O/U are better alternatives in every analysis reviewed. |
| BTTS / O/U Poisson model edge | MEDIUM | Methodology is validated but calibration from historical WC data (2006-2022) is required before the model has demonstrated edge over market. |
