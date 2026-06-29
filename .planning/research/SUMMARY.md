# Research Summary: v2.3 Automated MLB Player Data and Accuracy Upgrade

**Date:** 2026-06-28

## Stack Additions

- Keep MLB StatsAPI as the runtime identity source for schedules, game ids, and probable pitchers where available.
- Treat pybaseball/Fangraphs as optional enrichment only. The scanner must remain usable if Fangraphs returns 403.
- Use local CSV/API imports and cached database snapshots as the runtime player-stat source.
- Emit event-id keyed feature JSON files so scanner inference is deterministic for a requested date.

## Feature Table Stakes

- One-command daily/date-range update for local MLB player data.
- Deterministic schemas for batter, starter, bullpen, lineup, and absence rows.
- Rolling feature interpretation, not raw stat dumping: starter quality/rest/workload, lineup strength/coverage, bullpen fatigue/availability, absence impact, and uncertainty.
- Walk-forward ablations that prove which feature groups improve Brier score, log loss, selective win rate, and coverage.
- Runtime source/freshness/confidence labels for every game.

## Watch Outs

- Live web scrapes are fragile and should not be required by scanner runtime.
- Same-day data can leak target-game outcomes into training unless feature builders enforce pregame availability.
- Richer features can improve explanations without improving probabilities unless the model artifact is retrained and promoted with those fields.
- Missing or stale player data must suppress betting picks, not silently fall back to confident recommendations.

## Planning Implication

The milestone should proceed in this order:

1. Make MLB runtime resilient to blocked sources.
2. Automate local player database updates.
3. Build an interpretation layer that turns raw stats into event-level features.
4. Retrain/evaluate/promote only if probability metrics improve.
5. Auto-load the resulting feature files in scanner runtime with truthful labels.
