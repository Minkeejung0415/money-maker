# Phase 37: MLB Series Variance and Player Database - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md - this log preserves the alternatives considered.

**Date:** 2026-06-28
**Phase:** 37-MLB Series Variance and Player Database
**Areas discussed:** Phase scope, data depth, runtime behavior, source strategy, storage, stat updates, rollout

---

## Phase Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Phase 37 | Start the next phase for MLB series variance and player database features. | yes |
| Patch only | Only fix the date/probable-pitcher bug now; defer the database phase. | |
| Discuss only | Capture decisions but do not touch code yet. | |

**User's choice:** Phase 37.
**Notes:** User wants the repeated-probability issue checked and also wants to grow MLB picks with a real player-data database.

---

## Data Depth

| Option | Description | Selected |
|--------|-------------|----------|
| Major stats first | Ingest batter, pitcher, probable starter, lineup, bullpen basics; grow later. | yes |
| Pitchers only | Focus narrowly on starters and bullpen to fix repeated series probabilities fast. | |
| Full player layer | Include lineups, injuries, batter splits, bullpen workload, handedness, and deeper features now. | |

**User's choice:** Major stats first.
**Notes:** CSV downloads from public websites are acceptable as a starting point. The model should become deeper over time after the foundation is stable.

---

## Source Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| CSV-first | Use downloaded CSVs/public exports first so schemas are inspectable and stable. | yes |
| API-first | Prefer live APIs/scrapers where possible, accepting more moving parts. | |
| Hybrid | Use CSVs for core season stats and APIs only for daily probable starters/lineups. | |

**User's choice:** CSV-first, with daily stat updates.
**Notes:** User wants raw major stats loaded locally and updated daily. Derived stats should be calculated locally where possible, such as ERA from runs/innings and batting average from hits/at-bats.

---

## Storage Format

| Option | Description | Selected |
|--------|-------------|----------|
| DuckDB/parquet | Good for growing CSV-style sports data while staying local and queryable. | yes |
| SQLite | Simple relational database, familiar and durable for normalized tables. | |
| Flat CSV only | Most inspectable, but weaker for joins, fingerprints, and growing schemas. | |

**User's choice:** DuckDB/parquet.
**Notes:** The database should remain local and inspectable while supporting joins, daily appends, formula-derived stats, and growth into deeper features.

---

## Daily Updates

| Option | Description | Selected |
|--------|-------------|----------|
| Append daily game logs | Store each day's raw player/team stat rows, then recompute cumulative and rolling stats. | yes |
| Overwrite season table | Replace the latest season totals each day from downloaded CSVs. | |
| Both snapshots | Keep raw daily logs and also save daily season-total snapshots for auditing. | |

**User's choice:** Append daily game logs.
**Notes:** Daily logs should drive season-to-date and rolling computations. This supports explainability and lets complex stats be computed from raw components.

---

## Computed Stats

| Option | Description | Selected |
|--------|-------------|----------|
| Cumulative + rolling | Compute season totals plus last 7/14/30 day form for pitchers, batters, and bullpens. | yes |
| Cumulative only | Start with season-to-date formulas such as ERA, AVG, OBP, SLG, WHIP. | |
| Rolling first | Prioritize recent form over season-long totals from the beginning. | |

**User's choice:** Cumulative + rolling.
**Notes:** Rolling recent-form windows should be part of the first design, not deferred entirely.

---

## Runtime Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Label and suppress | Show probabilities but mark low-confidence or suppress picks when starters/lineups are missing. | yes |
| Fallback allowed | Use team-only fallback but print fallback reason clearly. | |
| Always output | Always produce picks even with missing player data, with warnings only. | |

**User's choice:** Label and suppress.
**Notes:** Research probabilities are okay, but betting picks should not be trusted when the player-data layer is stale or incomplete.

---

## Lineup Policy

| Option | Description | Selected |
|--------|-------------|----------|
| Probables + suppress | Use probable starters and projected/basic lineup data, but suppress betting picks until lineup confidence is good. | yes |
| Use projections | Allow picks from projected lineups as long as starter and team stats are fresh. | |
| Wait confirmed | Do not output MLB picks until confirmed lineups are available. | |

**User's choice:** Probables + suppress.
**Notes:** Scanner may show research probabilities before confirmed lineups, but betting picks should stay suppressed when lineup confidence is weak.

---

## Model Rollout

| Option | Description | Selected |
|--------|-------------|----------|
| Fix live inference first | Fix date/starter variance and add database-fed live features before retraining. | yes |
| Retrain immediately | Build and promote a new MLB artifact in this phase once data is loaded. | |
| Two-step gate | Implement live features, then retrain only if tests show series variance improves. | |

**User's choice:** Fix live inference first.
**Notes:** Phase planning should prioritize correcting current runtime behavior and feeding richer live features before promoting a new trained artifact.

---

## the agent's Discretion

- Choose exact storage format and schema for the first player database, as long as it is simple and inspectable.
- Choose implementation approach that reuses existing MLB player-data normalization and player-aware feature builders.

## Deferred Ideas

- Full MLB player-prop line ingestion.
- Deeper algorithm expansion beyond major stats after the first player database and same-series variance fix are validated.
