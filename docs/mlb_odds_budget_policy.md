# MLB Odds API Budget Policy

Applies to `alpha/data/ingestion/mlb_odds_api.py` (sport key
`baseball_mlb`). Complements the NBA policy in
`docs/odds_api_budget_policy.md`; the same free tier (500 credits/month)
is shared across sports.

## Free vs paid endpoints

| Endpoint | Cost | Use |
|---|---|---|
| `GET /v4/sports/baseball_mlb/events/` | **FREE** | Slate discovery — always call first |
| `GET /v4/sports/baseball_mlb/odds/` (h2h, us) | **PAID** (~1 credit) | Full-slate moneyline, once/day |
| `GET /v4/sports/baseball_mlb/events/{id}/odds/` | **PAID** (~1 credit) | Manual single-event refresh |
| MLB StatsAPI (schedule, probables, finals) | **FREE** | Unlimited refresh, separate cache |
| pybaseball / Baseball Savant | **FREE** | Starter + offense features |

Credit cost of a paid call scales with `regions × markets`. Defaults are
pinned to `regions=["us"]`, `markets=["h2h"]` — adding either multiplies
the cost and must be a deliberate code change.

## Daily budget

- `max_paid_fetches_per_day = 1` (default). The first scan of the day
  pays; every later scan reads `data/cache/mlb/odds/h2h_<date>.json` at
  zero cost.
- **Expected steady-state usage: ~1 credit/day, ~30/month** for the MLB
  vertical.
- `--force-refresh-odds` spends one extra full-slate credit. Manual,
  operator-initiated only.
- `--selected-event-id` spends ~1 credit per event refreshed and merges
  into the daily cache without consuming the full-slate budget slot.
  Use it when a probable-pitcher change makes one game's line stale.

## Hard rules

1. **No automatic polling.** Nothing in this codebase loops, schedules,
   or retries paid odds calls. Refresh is always an explicit human action.
2. **Never spend credits to discover games.** The free events endpoint
   and free StatsAPI schedule do discovery.
3. **Fail closed.** Missing key, HTTP error, rate limit, or zero
   bookmaker pairs ⇒ no odds, never fabricated prices (no -110
   placeholder for MLB), and the paper gate refuses with
   `real_odds_missing`.
4. **Quota visibility.** `x-requests-remaining` / `x-requests-used` /
   `x-requests-last` headers are recorded on every paid response and
   persisted in cache metadata; the scanner prints remaining credits.

## Cache layout

```
data/cache/mlb/
  schedule/      FREE StatsAPI schedule+probables (15-min TTL)
  odds/          PAID h2h snapshots, one file per day, with quota meta
  starters/raw/      FREE raw pybaseball pulls (daily)
  starters/features/ derived starter features (daily)
  team_offense/      team offense baseline (daily)
```

Free and paid caches are deliberately separate: clearing or hammering
free caches can never trigger a paid call.
