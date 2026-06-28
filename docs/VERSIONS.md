# Version Index

This file is the GitHub-facing guide to the repo's version labels. The detailed implementation notes live in `.planning/`, while this page gives each version a readable name, status, shipped date, and short purpose.

## Version Labels

| Version | Git tag | Shipped | Status | Label |
| --- | --- | --- | --- | --- |
| v1.9 | `v1.9` | 2026-06-24 | Complete | World Cup player-aware win probability |
| v1.8 | `v1.8` | 2026-06-24 | Complete | Player-aware MLB moneyline |
| v1.7 | `v1.7` | 2026-06-22 | Complete | Tactical calibration and validation |
| v1.6 | `v1.6` | 2026-06-22 | Complete | World Cup tactical matchups |
| v1.5 | `v1.5` | 2026-06-21 | Complete | World Cup true SGP |
| v1.4 | `v1.4` | 2026-06-21 | Complete | Soccer mode upgrade |
| v1.3 | not tagged | 2026-06-19 | Complete | MLB win probability model |
| v1.2 | not tagged | 2026-06-19 | Complete | World Cup dynamic draw algorithm |
| v1.1 | not tagged | 2026-06-19 | Complete | World Cup soccer mode |
| v1.0 | not tagged | 2026-03-12 | Complete | NBA prop model algorithm upgrade |

Older versions v1.0 through v1.3 predate the consistent release-tag pattern used from v1.4 onward. They are documented here, but left untagged unless a historical release point is explicitly chosen.

## v1.9 - World Cup Player-Aware Win Probability

Shipped: 2026-06-24

Purpose: improve World Cup WDL accuracy and high-confidence hit rate beyond the Elo-only baseline.

Runtime trust note: v1.9 delivers the hybrid/player-aware modules and evaluation gates. The scanner default remains `--model elo`; use `scripts/wc_scanner.py --model hybrid` for the v1.9 hybrid baseline path. Modules such as context, projected XI, goalkeeper, tournament state, and tactical features should be read as delivered feature/evaluation layers unless the selected scanner model consumes them explicitly.

Highlights:

- Chronological evaluation framework with Brier score, log loss, A-grade hit rate, and isotonic calibration.
- Hybrid baseline ratings combining Elo-like strength, xG attack/defense states, FIFA SUM, host, and confederation adjustments.
- Projected XI layer with starter probabilities, position line scores, replacement impact, uncertainty, and continuity.
- Dedicated goalkeeper module separate from generic team defense.
- Tournament-state, position-specific player, tactical matchup, set-piece, and context feature modules.
- Promotion gate passed in Phase 26: Brier 0.5181 to 0.4889 and log loss 0.8805 to 0.8439.
- Optional scanner model selection with output labels: `--model elo` or `--model hybrid`.

Primary docs:

- `.planning/STATE.md`
- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`

## v1.8 - Player-Aware MLB Moneyline

Shipped: 2026-06-24

Purpose: upgrade MLB moneyline modeling from team-only v1.3 features toward validated player-aware runtime behavior.

Highlights:

- Canonical MLB game and player-slot data foundation.
- Leakage-safe starter, lineup, bullpen, and absence feature rows.
- Walk-forward ablation comparison against the v1.3 baseline.
- Runtime artifact gates for validated v1.8 artifacts.
- Visible fallback labels for v1.8, v1.3 baseline fallback, and market-implied output.

Primary docs:

- `.planning/v1.8-MILESTONE-AUDIT.md`
- `.planning/MILESTONES.md`

## v1.7 - Tactical Calibration and Validation

Shipped: 2026-06-22

Purpose: replace hand-set World Cup tactical weights with leakage-safe, regularized estimates that deploy only when out-of-sample evidence improves probability quality.

Highlights:

- Historical tactical rows built only from pre-kickoff information.
- Regularized residual outcome and goal models.
- Independent gates for 1X2, totals, and BTTS markets.
- Versioned artifacts with baseline fallback.
- Real coverage audit blocked tactical promotion because only 16 eligible rows were available.

Primary docs:

- `.planning/milestones/v1.7-MILESTONE-AUDIT.md`
- `.planning/milestones/v1.7-ROADMAP.md`
- `.planning/milestones/v1.7-REQUIREMENTS.md`

## v1.6 - World Cup Tactical Matchups

Shipped: 2026-06-22

Purpose: add explainable tactical matchup signals to World Cup scoreline and scanner output.

Highlights:

- Cached recent national-team tactical profiles.
- Formation, possession, directness, width, pressing proxy, set-piece, and defensive-block comparisons.
- Bounded tactical attack multipliers.
- Tactical Elo and scoreline-rate integration.
- Pacific/UTC adjacent-date team resolution and fail-closed gates.

Primary docs:

- `.planning/milestones/v1.6-MILESTONE-AUDIT.md`
- `.planning/milestones/v1.6-ROADMAP.md`
- `.planning/milestones/v1.6-REQUIREMENTS.md`

## v1.5 - World Cup True SGP

Shipped: 2026-06-21

Purpose: build coherent World Cup same-game combinations from a single calibrated scoreline distribution.

Highlights:

- Scoreline distribution calibrated to WDL probabilities.
- Coherent over/under 2.5 and BTTS probabilities.
- Normalized 1X2, totals, and BTTS market-price contract.
- Stage-safe 2-3 leg same-match builder.
- `wc_scanner.py --mode sgp`.

Primary docs:

- `.planning/milestones/v1.5-MILESTONE-AUDIT.md`
- `.planning/milestones/v1.5-ROADMAP.md`
- `.planning/milestones/v1.5-REQUIREMENTS.md`

## v1.4 - Soccer Mode Upgrade

Shipped: 2026-06-21

Purpose: expand soccer modeling beyond World Cup-only flows into EPL/UCL feature and scanner support.

Highlights:

- Football-data.org team history for form, H2H, rest, and team IDs.
- Daily Club Elo ratings.
- Cached FBref set-piece features.
- EPL/UCL cache isolation.
- Draw-leg support in soccer SGP construction.

Primary docs:

- `.planning/milestones/v1.4-MILESTONE-AUDIT.md`
- `.planning/milestones/v1.4-ROADMAP.md`
- `.planning/milestones/v1.4-REQUIREMENTS.md`

## v1.3 - MLB Win Probability Model

Shipped: 2026-06-19

Purpose: replace flat MLB 50/50 fallback with independently trained, historically validated home/away win probabilities.

Highlights:

- Leakage-free historical MLB game dataset.
- Calibrated pregame model with team, pitcher, rest, and home-field features.
- Chronological validation against simple and market baselines.
- Daily scanner output with win percentages and fair odds.
- Optional manual sportsbook odds for edge comparison.

Primary docs:

- `.planning/v1.3-MILESTONE-AUDIT.md`
- `.planning/PROJECT.md`

## v1.2 - World Cup Dynamic Draw Algorithm

Shipped: 2026-06-19

Purpose: replace a flat draw prior with a match-strength-dependent draw probability.

Highlights:

- Draw probability decreases as Elo difference grows.
- Calibrated to historical World Cup group-stage draw rates by Elo band.
- Integrated into `wc_model.py`.

Primary docs:

- `.planning/PROJECT.md`
- `.planning/phases/08-dynamic-draw-algorithm/08-01-SUMMARY.md`

## v1.1 - World Cup Soccer Mode

Shipped: 2026-06-19

Purpose: add a dedicated World Cup scanner path independent of the general soccer models.

Highlights:

- World Cup fixture ingestion through football-data.org.
- Elo-logistic WDL model with neutral venue handling.
- World Cup SGP builder.
- `scripts/wc_scanner.py --mode parlay`.

Primary docs:

- `.planning/PROJECT.md`
- `.planning/phases/05-data-foundation/`
- `.planning/phases/06-match-model/`
- `.planning/phases/07-sgp-builder/`

## v1.0 - NBA Prop Model Algorithm Upgrade

Shipped: 2026-03-12

Purpose: improve NBA prop projections beyond the original near-random baseline.

Highlights:

- Exponential-decay rolling averages.
- Poisson and negative-binomial distribution estimates.
- Position-level opponent adjustments.
- Blowout gate and 60% SGP confidence floor.
- Final documented accuracy: 48.6% overall, up from 43.5%.

Primary docs:

- `.planning/PROJECT.md`
- `docs/plans/`
