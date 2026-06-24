# Roadmap: v1.9 — Improving World Cup Win Probability with Team and Player Features

**Milestone:** v1.9
**Phases:** 8 (Phase 25 → Phase 32)
**Requirements:** 39 total | All mapped ✓
**Phase numbering:** Continues from v1.8 (last phase: 24)

---

## Phase Summary

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|-----------------|
| 25 | Evaluation Framework | Chronological backtest infrastructure with Brier/log-loss/A-grade metrics and calibration | EVAL-01, EVAL-02, EVAL-03, EVAL-04 | 4 |
| 26 | Hybrid Baseline Ratings | Elo-like + xG attack/defense EWMA + FIFA SUM replaces pure Elo-logistic backbone | BASELINE-01, BASELINE-02, BASELINE-03, BASELINE-04, BASELINE-05 | 4 |
| 27 | Projected XI Layer | Starter probability estimation, line-score aggregation (sum not mean), absence impact | LINEUP-01, LINEUP-02, LINEUP-03, LINEUP-04, LINEUP-05 | 4 |
| 28 | Goalkeeper Module | Dedicated GK submodel: xGOT prevention, cross claims, sweeper, continuity modifier | GK-01, GK-02, GK-03, GK-04 | 4 |
| 29 | Tournament-State Logic | Qualification pressure, rotation risk, yellow-card accumulation, 2026 best-third | TOURNEY-01, TOURNEY-02, TOURNEY-03, TOURNEY-04, TOURNEY-05 | 4 |
| 30 | Position-Specific Player Features | Role features per position (CB/DM/CM/Winger/Striker) with hierarchical shrinkage | PLAYER-01, PLAYER-02, PLAYER-03, PLAYER-04, PLAYER-05, PLAYER-06, PLAYER-07 | 5 |
| 31 | Tactical Matchup + Set-Piece | PPDA/possession style, counterattack, style matchup interactions, corner xG states | TACTICAL-01, TACTICAL-02, TACTICAL-03, TACTICAL-04, TACTICAL-05 | 4 |
| 32 | Context Features + Integration | Days rest, travel, venue/heat, kick-off time; full integration and final calibration | CONTEXT-01, CONTEXT-02, CONTEXT-03, CONTEXT-04 | 4 |

---

## Phase Details

---

### Phase 25: Evaluation Framework

**Goal:** Set up the chronological backtest infrastructure — expanding-window splits, Brier/log-loss/accuracy/A-grade metrics, isotonic calibration on validation fold — so every subsequent phase can be measured against the Elo-only baseline.

**Requirements:**
- EVAL-01: Chronological expanding-window backtest with features frozen at pre-kickoff timestamp
- EVAL-02: Metrics per model version: accuracy, multiclass Brier, log loss, calibration curves, A-grade hit rate (top-class >= 0.65)
- EVAL-03: Isotonic regression calibration fitted on validation fold only
- EVAL-04: Promotion gate: player-aware model must beat Elo-only baseline on Brier + log loss

**Success criteria:**
1. `wc_eval.py` runs a chronological expanding-window backtest on historical WC matches and prints Brier score, log loss, accuracy, and A-grade hit rate for the current Elo-only model
2. Isotonic regression calibration is fitted on the validation split and applied to held-out test split; calibration curve is plotted or logged
3. Promotion gate function returns PASS/FAIL when given two model result dicts; returns FAIL for identical models (guard against trivial pass)
4. All existing tests pass; wc_scanner.py output is unchanged

---

### Phase 26: Hybrid Baseline Ratings

**Goal:** Replace the pure Elo-logistic backbone with a hybrid baseline that combines an Elo-like long-run rating, xG attack/defense EWMA states, FIFA SUM feature, host-country distinction, and confederation interaction.

**Requirements:**
- BASELINE-01: Hybrid Elo-like long-run rating updated match-by-match on all competitive internationals
- BASELINE-02: xG attack state and xG defense state as EWMA of non-penalty xG for/against, with configurable half-life
- BASELINE-03: FIFA SUM rating as a feature alongside Elo and xG states
- BASELINE-04: Host-country advantage as distinct feature; all other 2026 venues neutral-site
- BASELINE-05: Confederation interaction feature for cross-confederation neutral-site matchups

**Success criteria:**
1. `WCTeamRatings` class exposes `elo`, `xg_attack`, `xg_defense`, `fifa_sum`, `host_flag`, and `confederation_interaction` for any team/date pair
2. Elo updates are sequential (match-by-match) and verifiably leakage-free (no future match data influences past ratings)
3. xG EWMA half-life is configurable; default produces sensible decay on 2022/2018 WC historical data
4. Hybrid baseline beats or ties Elo-only on Phase 25 evaluation framework Brier score on WC held-out matches

---

### Phase 27: Projected XI Layer

**Goal:** Estimate starter probabilities per player and aggregate position-specific player features into line scores using sum (not mean), with replacement-adjusted absence impact and lineup uncertainty bands.

**Requirements:**
- LINEUP-01: Starter probability per player per match from national-team history, injury/suspension, fitness
- LINEUP-02: Player features aggregated by line (GK/Back/Midfield/Front) using sum not mean
- LINEUP-03: Replacement-adjusted absence impact = player_value_in_role − replacement_value_in_same_role
- LINEUP-04: Lineup uncertainty variance term widens WDL confidence when starter probs are low
- LINEUP-05: Back-line and midfield-triangle continuity modifiers on line scores

**Success criteria:**
1. `LineupProjector` produces a start probability for each squad member; probabilities sum to ~11 per role group
2. Line scores computed by summing position scores; a team with 10 players in a line scores lower than 11 (verifiable by removing one player)
3. Absence impact correctly computes negative delta when a key player is replaced by a lower-rated substitute
4. A match with high starter uncertainty (many players at p_start ~0.5) produces a wider WDL confidence interval than a match with confirmed lineups

---

### Phase 28: Goalkeeper Module

**Goal:** Build a dedicated goalkeeper submodel with goals prevented vs xGOT, save subtype distribution, cross claims, sweeper actions, and GK-CB continuity modifier — stored separately from generic team defense.

**Requirements:**
- GK-01: GK strength score includes goals prevented vs xGOT and save subtype distribution
- GK-02: Cross claims, crosses-not-claimed, and sweeper action counts as distinct GK features
- GK-03: GK-CB continuity modifier applied when starting GK-CB pairing differs from last match
- GK-04: GK stored and evaluated as dedicated submodel, separate from generic team defense rating

**Success criteria:**
1. `GoalkeeperModule` returns a feature dict separate from `xg_defense` state; they can be added or removed independently from the model
2. A GK with positive goals-prevented (saves above xGOT) produces a higher GK score than one with neutral performance on the same xG
3. GK-CB continuity modifier fires correctly: no modifier when last-match pairing matches, negative modifier when GK or CB1/CB2 is different
4. Removing GK module from feature set and rerunning Phase 25 eval shows measurable Brier degradation (GK adds information)

---

### Phase 29: Tournament-State Logic

**Goal:** Compute qualification pressure state, rotation risk flag, yellow-card accumulation/suspension risk, and 2026 best-third-place ranking scenarios as deterministic features from match context.

**Requirements:**
- TOURNEY-01: Qualification pressure state per team: must-win / draw-enough / likely-through / already-through / already-out
- TOURNEY-02: Rotation risk flag when team's group qualification is already secured
- TOURNEY-03: Yellow-card accumulation per player; suspension risk flag for 1-caution players; cards wiped post-group-stage and post-QF
- TOURNEY-04: Best-third-place ranking scenarios for 2026 12-group format in final group matches
- TOURNEY-05: Fair-play score and FIFA ranking as tiebreak features for borderline group-stage matches

**Success criteria:**
1. `TournamentState` correctly classifies each team's pressure state for a given group standings input; verified with 3 test cases (must-win, draw-enough, already-through)
2. Rotation risk flag is True for all already-through teams in simulated final group match data
3. Yellow-card suspension logic correctly flags a player on 1 caution; correctly clears all cards at the group stage / QF boundary
4. Best-third-place ranking calculator correctly identifies which third-placed teams would qualify under 2026 regulations given a sample group standings input

---

### Phase 30: Position-Specific Player Features

**Goal:** Build per-position role features for CB, DM, CM, Winger, and Striker using club and national-team data, with hierarchical shrinkage pooling sparse national-team samples toward club-based role priors.

**Requirements:**
- PLAYER-01: CB features: aerial duel win rate, interceptions/90, errors-to-shot/90
- PLAYER-02: DM features: ball recoveries/90, interceptions/90, press resistance proxy, foul/card rate
- PLAYER-03: CM features: possession value added, progressive pass/carry counts, chances created/90
- PLAYER-04: Winger features: np-xG/90, xA/90, key passes, box entries, cutbacks
- PLAYER-05: Striker features: np-xG/90, shot volume/locations, finishing delta shrunk toward positional mean
- PLAYER-06: Hierarchical shrinkage: sparse national-team samples pool toward club-based role priors; finishing and shot-stopping shrunk toward positional averages
- PLAYER-07: Club data ~70-80%, national-team ~20-30%; weighting configurable and tunable by backtest

**Success criteria:**
1. `PlayerFeatureStore` returns a complete feature dict for any player-role pair from available FBref/Understat/StatsBomb free data
2. A player with 0 national-team caps produces a feature vector identical to the club-weighted positional prior (full shrinkage)
3. A player with 50 national-team caps produces a feature vector closer to their observed stats than to the prior (partial shrinkage)
4. Finishing delta for a striker is visibly shrunk: a striker with xGOT-xG delta of +0.3 over 5 games gets a shrunk estimate closer to 0.05 than to 0.3
5. Phase 25 eval framework shows measurable Brier improvement over Phase 26 baseline after adding player features

---

### Phase 31: Tactical Matchup + Set-Piece

**Goal:** Compute PPDA/possession style per team, counterattack frequency, style matchup interactions between teams, and separate set-piece attack/defense EWMA states including corner xG.

**Requirements:**
- TACTICAL-01: PPDA proxy and possession style index from rolling match data per team
- TACTICAL-02: Counterattack frequency and rest-defense stability as team style features
- TACTICAL-03: Style matchup interactions: press-vs-build, width-vs-centrality, possession-vs-transition
- TACTICAL-04: Set-piece attack/defense EWMA states, separate from open-play xG states
- TACTICAL-05: Corner xG for/against and aerial duel edge as set-piece features

**Success criteria:**
1. `TacticalProfile` returns PPDA, possession index, counterattack frequency, rest-defense, and set-piece attack/defense for each team from historical match summaries
2. Style matchup interaction features are computed as team_A_feature × opponent_B_vulnerability (symmetric interactions)
3. Set-piece xG states are updated separately from open-play xG states; removing open-play xG does not affect set-piece features
4. Phase 25 eval with tactical features shows measurable change (positive or negative) vs Phase 26 baseline — used to decide regularization strength

---

### Phase 32: Context Features + Full Integration

**Goal:** Add regularized context features (days rest, travel, venue altitude/heat, kick-off time), integrate all layers into the stacked WC model, run final calibration, and confirm the player-aware model passes the Elo-only baseline promotion gate.

**Requirements:**
- CONTEXT-01: Days rest and expected-starter minutes in prior 7 and 14 days as regularized context features
- CONTEXT-02: Intercontinental travel distance, time zones, east/west direction as context features
- CONTEXT-03: Venue context: host city altitude, roof/open-air, kick-off local time for 2026 venues
- CONTEXT-04: Context features regularized more heavily than team/player features

**Success criteria:**
1. `MatchContext` computes days rest, travel distance, and venue features from match schedule and host city data; all 2026 host cities supported
2. Context feature coefficients in the final model are visibly smaller than team-rating coefficients (regularization confirmed)
3. Full stacked model (BASELINE + LINEUP + GK + PLAYER + TOURNEY + TACTICAL + CONTEXT) runs end-to-end via `wc_scanner.py --mode parlay` without errors
4. Phase 25 promotion gate returns PASS: stacked model beats Elo-only baseline on both Brier score and log loss on chronological holdout

---

## Coverage Audit

| Category | Requirements | Phase |
|----------|-------------|-------|
| BASELINE | BASELINE-01 through BASELINE-05 (5) | Phase 26 |
| LINEUP | LINEUP-01 through LINEUP-05 (5) | Phase 27 |
| GK | GK-01 through GK-04 (4) | Phase 28 |
| PLAYER | PLAYER-01 through PLAYER-07 (7) | Phase 30 |
| TOURNEY | TOURNEY-01 through TOURNEY-05 (5) | Phase 29 |
| TACTICAL | TACTICAL-01 through TACTICAL-05 (5) | Phase 31 |
| CONTEXT | CONTEXT-01 through CONTEXT-04 (4) | Phase 32 |
| EVAL | EVAL-01 through EVAL-04 (4) | Phase 25 |

**Total: 39 / 39 requirements mapped ✓**

---

## Risk Register

| Risk | Mitigation |
|------|-----------|
| Free data sources (FBref, Understat) lack WC player coverage | Fall back to club-season data only; use positional priors for players with no data |
| xG data not available for pre-2018 WC matches | Long-run Elo backbone requires goals only; xG states built from available data (2018+) |
| Starter probabilities are noisy pre-tournament | Uncertainty band (LINEUP-04) widens WDL intervals appropriately; model stays calibrated |
| Context features hurt calibration if over-weighted | CONTEXT-04 mandates stronger regularization; Phase 25 eval catches any degradation |
| wc_scanner.py regression during incremental builds | Each phase success criterion requires scanner to run cleanly before completion |

---

*Roadmap created: 2026-06-24*
*Milestone: v1.9 | Phases 25–32 | 39 requirements | 8 phases*
