# Requirements: Alpha Terminal — World Cup Win Probability Upgrade

**Defined:** 2026-06-24
**Milestone:** v1.9 — Improving World Cup Win Probability with Team and Player Features
**Core Value:** Every prop line the scanner outputs must have a >55% historical hit rate — if the model can't beat a coin flip, it's not worth betting.

## v1.9 Requirements

**Runtime note:** These requirements track delivered v1.9 modules and evaluation contracts. The live scanner default remains the conservative Elo path unless `scripts/wc_scanner.py --model hybrid` is selected. Context, player, goalkeeper, tournament, and tactical modules should be treated as feature/evaluation layers unless the selected scanner model explicitly consumes them.

### BASELINE — Hybrid Team Ratings

- [x] **BASELINE-01**: WC model uses a hybrid Elo-like long-run team rating updated match-by-match on all competitive internationals
- [x] **BASELINE-02**: xG attack state and xG defense state computed as EWMA of non-penalty xG for/against, stored per team with configurable half-life
- [x] **BASELINE-03**: FIFA SUM rating included as a feature alongside Elo and xG states (not as sole baseline)
- [x] **BASELINE-04**: Host-country advantage treated as a distinct feature; all other 2026 WC venues treated as neutral-site
- [x] **BASELINE-05**: Confederation interaction feature included for cross-confederation neutral-site matchups

### LINEUP — Projected XI Layer

- [x] **LINEUP-01**: Starter probability estimated per player per match from recent national-team history, injury/suspension status, and fitness signals
- [x] **LINEUP-02**: Player features aggregated into line scores by position group (GK / Back line / Midfield / Front line) using sum not mean
- [x] **LINEUP-03**: Replacement-adjusted absence impact computed as: player_value_in_role − expected_replacement_value_in_same_role
- [x] **LINEUP-04**: Lineup uncertainty variance term widens WDL confidence intervals when starter probabilities are low or uncertain
- [x] **LINEUP-05**: Back-line and midfield-triangle continuity modifiers applied to line scores when starting pairing differs from recent matches

### GK — Goalkeeper Module

- [x] **GK-01**: Goalkeeper strength score includes goals prevented vs xGOT and save subtype distribution
- [x] **GK-02**: Cross claims, crosses-not-claimed, and sweeper action counts tracked per GK as distinct features
- [x] **GK-03**: GK-CB continuity modifier applied when the starting GK-CB pairing differs from the most recent match
- [x] **GK-04**: Goalkeeper stored and evaluated as a dedicated submodel, not merged into generic team defense rating

### PLAYER — Position-Specific Player Features

- [x] **PLAYER-01**: CB role features: aerial duel win rate, interceptions per 90, errors leading to shot or goal per 90
- [x] **PLAYER-02**: DM role features: ball recoveries per 90, interceptions per 90, press resistance proxy, foul/card rate
- [x] **PLAYER-03**: CM role features: possession value added, progressive pass and carry counts, chances created per 90
- [x] **PLAYER-04**: Winger role features: non-penalty xG per 90, xA per 90, key passes, box entries, cutbacks/pull-backs
- [x] **PLAYER-05**: Striker role features: non-penalty xG per 90, shot volume and location distribution, finishing delta (xGOT − xG) shrunk hard toward positional mean
- [x] **PLAYER-06**: Hierarchical shrinkage applied at player level: sparse national-team samples pool toward club-based role priors; finishing and shot-stopping estimates shrunk toward positional averages
- [x] **PLAYER-07**: Club data weighted ~70–80% and national-team data ~20–30% for repeatable actions; weighting is configurable and tunable by backtest

### TOURNEY — Tournament-State Logic

- [x] **TOURNEY-01**: Qualification pressure state computed per team per match: must-win / draw-enough / likely-through / already-through / already-out
- [x] **TOURNEY-02**: Rotation risk flag set when a team's group-stage qualification is already secured before the match
- [x] **TOURNEY-03**: Yellow-card accumulation tracked per player; suspension risk flag raised for players entering a match on 1 caution; cards wiped after group stage and after quarter-finals per 2026 FIFA regulations
- [x] **TOURNEY-04**: Best-third-place ranking scenarios modeled for 2026's 12-group format in final group matches: affects goal-difference incentives and rotation decisions
- [x] **TOURNEY-05**: Fair-play score and FIFA ranking included as tiebreak features for borderline group-stage matches

### TACTICAL — Tactical Matchup + Set-Piece

- [x] **TACTICAL-01**: Team pressing effectiveness (PPDA proxy) and possession style index computed from rolling match data per team
- [x] **TACTICAL-02**: Counterattack frequency and rest-defense stability included as distinct team style features
- [x] **TACTICAL-03**: Style matchup interactions computed: press-vs-build, width-vs-centrality, possession-vs-transition between the two teams
- [x] **TACTICAL-04**: Set-piece attack and defense states stored as separate EWMA components, independent of open-play xG states
- [x] **TACTICAL-05**: Corner xG for/against and aerial duel edge included as set-piece strength features

### CONTEXT — Context Features (heavily regularized)

- [x] **CONTEXT-01**: Days rest since last match and expected-starter minutes in prior 7 and 14 days included as regularized context features
- [x] **CONTEXT-02**: Intercontinental travel distance, time zones crossed, and travel direction (east/west) included as context features
- [x] **CONTEXT-03**: Venue context for 2026 host cities: altitude, roof/open-air status, and kick-off local time included as features
- [x] **CONTEXT-04**: All context features regularized more heavily than team/player features; their influence targets availability and confidence band, not core strength coefficients

### EVAL — Evaluation Framework

- [x] **EVAL-01**: Chronological expanding-window backtest with all features frozen at pre-kickoff timestamp (no time leakage) — 2018 train/2022 test split in wc_eval.py
- [x] **EVAL-02**: Metrics tracked per model version: accuracy, multiclass Brier score, log loss, calibration reliability curves, A-grade hit rate (top-class probability >= 0.65) — wc_calibration.py
- [x] **EVAL-03**: Isotonic regression calibration fitted on validation fold only; never post-hoc on full dataset — WCIsotonicCalibrator fit on 2018 only
- [x] **EVAL-04**: Player-aware model must improve over Elo-only WC baseline on both Brier score and log loss in chronological holdout before promotion to production — promotion_gate() implemented

## v2.0 Requirements (deferred)

### Chemistry / Continuity

- **CHEM-01**: Full chemistry/continuity graph: shared club minutes network across lines
- **CHEM-02**: Club-pair synergy adjustments for frequently co-playing national-team partners

### Game-Plan Distribution

- **PLAN-01**: Early-sub and game-plan distribution modeling for favorites managing advantage
- **PLAN-02**: In-game state model that adjusts WDL based on scoreline, minute, and momentum proxies

## Out of Scope

| Feature | Reason |
|---------|--------|
| Commercial data sources (Opta, StatsBomb commercial) | Free data only constraint |
| WC player props | No dependable free player-prop odds source exists |
| WC parlay optimization beyond SGP | Deferred until individual match probabilities are validated |
| MLB player props | Requires dependable prop-odds source — separate scope |
| Invented SGP prices | Recommendations require actual supplied prices |
| Early-sub / game-plan distribution | Medium priority — deferred to v2.0 |
| Full chemistry/continuity graph | Medium priority — deferred to v2.0 |
| Biomechanical injury prediction | Evidence base too weak for direct performance coefficients |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| BASELINE-01 | Phase 26 | Complete |
| BASELINE-02 | Phase 26 | Complete |
| BASELINE-03 | Phase 26 | Complete |
| BASELINE-04 | Phase 26 | Complete |
| BASELINE-05 | Phase 26 | Complete |
| LINEUP-01 | Phase 27 | Complete |
| LINEUP-02 | Phase 27 | Complete |
| LINEUP-03 | Phase 27 | Complete |
| LINEUP-04 | Phase 27 | Complete |
| LINEUP-05 | Phase 27 | Complete |
| GK-01 | Phase 28 | Complete |
| GK-02 | Phase 28 | Complete |
| GK-03 | Phase 28 | Complete |
| GK-04 | Phase 28 | Complete |
| PLAYER-01 | Phase 30 | Complete |
| PLAYER-02 | Phase 30 | Complete |
| PLAYER-03 | Phase 30 | Complete |
| PLAYER-04 | Phase 30 | Complete |
| PLAYER-05 | Phase 30 | Complete |
| PLAYER-06 | Phase 30 | Complete |
| PLAYER-07 | Phase 30 | Complete |
| TOURNEY-01 | Phase 29 | Complete |
| TOURNEY-02 | Phase 29 | Complete |
| TOURNEY-03 | Phase 29 | Complete |
| TOURNEY-04 | Phase 29 | Complete |
| TOURNEY-05 | Phase 29 | Complete |
| TACTICAL-01 | Phase 31 | Complete |
| TACTICAL-02 | Phase 31 | Complete |
| TACTICAL-03 | Phase 31 | Complete |
| TACTICAL-04 | Phase 31 | Complete |
| TACTICAL-05 | Phase 31 | Complete |
| CONTEXT-01 | Phase 32 | Complete |
| CONTEXT-02 | Phase 32 | Complete |
| CONTEXT-03 | Phase 32 | Complete |
| CONTEXT-04 | Phase 32 | Complete |
| EVAL-01 | Phase 25 | Complete (25-01) |
| EVAL-02 | Phase 25 | Complete (25-01) |
| EVAL-03 | Phase 25 | Complete (25-01) |
| EVAL-04 | Phase 25 | Complete (25-01) |

**Coverage:**
- v1.9 requirements: 39 total
- Mapped to phases: 39
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-24*
*Last updated: 2026-06-27 - v1.9 implementation statuses reconciled with completed phases; scanner default remains Elo unless `--model hybrid` is selected*
