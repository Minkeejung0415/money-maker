# World Cup Tactical Matchups Research

## Data Source

ESPN public soccer endpoints provide team schedules across competitions and event summaries containing formations, possession, passing, long balls, crosses, shots, corners, tackles, interceptions, and clearances. Event summaries are immutable after completion and can be cached indefinitely; schedules use a short TTL.

## Architecture

1. Resolve the target teams from the ESPN WC scoreboard.
2. Fetch each team’s cross-competition schedule and select the latest five completed matches strictly before kickoff.
3. Parse both sides of each event so opponent-allowed and pressure metrics remain contextual.
4. Aggregate a `WCTacticalProfile` with sample size, freshness, formation context, and normalized behavioral metrics.
5. Compare profiles into small attack multipliers, capped independently of recent-form/Elo strength.
6. Expose the tactical explanation and baseline probability delta in scanner output.

## Guardrails

- No inferred coach intent or lineup assumptions.
- Do not call possession percentage “pressing”; use a defensive-actions-per-opponent-pass proxy and label it as such.
- Formation is descriptive because the same shape can support different behavior.
- Require at least three stat-complete recent matches and fail closed otherwise.
- Cap each attack multiplier to 0.90-1.10 and preserve probability normalization.

