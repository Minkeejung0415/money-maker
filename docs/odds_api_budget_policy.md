# The Odds API — Budget Policy (NBA vertical)

The Odds API key has a hard monthly credit budget (free tier: 500
credits/month). This document is the contract for how the NBA pipeline
spends those credits. **The default behavior is one paid fetch cycle per
day; there is no automatic polling, ever.**

## Estimated credit cost per call

Costs follow The Odds API v4 billing model: one credit per
`market x region` combination per request (per event for the
event-odds endpoint).

| Endpoint | Used by | Cost |
|---|---|---|
| `GET /v4/sports/basketball_nba/events` | `OddsAPIClient.fetch_events()` | **0 credits (free)** |
| `GET /v4/sports/basketball_nba/odds` (h2h, regions=`us`) | `OddsAPIClient.fetch_nba_games()` | 1 credit per call |
| `GET /v4/sports/basketball_nba/events/{id}/odds` (3 prop markets, regions=`us`) | `PlayerPropsClient.fetch_game_props_raw()` | ~3 credits **per event** |

Worked example for a typical 10-game slate with default settings:

```
moneyline:       1 credit
player props:    10 events x 3 markets x 1 region = 30 credits
daily total:     ~31 credits  ->  ~930/month on a full schedule
```

Every extra region **multiplies** these costs (`us,eu,uk` triples them
— that's why the default is now `regions=["us"]`), and every extra prop
market adds one credit per event per region (`player_threes` is off by
default partly for this reason).

## Why the date-based cache is the default

Each client writes the day's response to
`data/cache/odds/{games,props}_<date>.json`. Every re-run within the same
day reads from that file and costs **zero** credits. NBA lines move all
day, but the model's edge calculations are not fast enough to chase steam;
a once-per-day snapshot plus an optional pregame refresh of selected games
is the deliberate trade: correctness improvements must come from modeling,
not from burning credits on fresher prices.

Cache files store metadata so spend is auditable:

```json
"meta": {
  "fetched_at_utc": "...",
  "refresh_mode": "daily | force_full | force_selected",
  "paid_fetch_count": 1,
  "credits_last": 31.0,
  "credits_used": 88.0,
  "credits_remaining": 412.0,
  "markets": ["player_points", "player_rebounds", "player_assists"]
}
```

## How to force refresh manually

```python
from alpha.data.ingestion.odds_api import OddsAPIClient
from alpha.data.ingestion.player_props import PlayerPropsClient

games = OddsAPIClient().fetch_nba_games(force_refresh=True)        # paid
props = PlayerPropsClient().fetch_all_game_props(
    games, force_refresh=True)                                     # paid, all events
```

`force_refresh` is always an explicit, manual decision — nothing in the
codebase calls it on a schedule, and adding a paid polling loop is
forbidden by this policy.

## How to refresh selected games only

Refresh only the events you are about to bet (e.g. tonight's two target
games) and merge them into today's cache, leaving every other event's
cached lines untouched:

```python
props = PlayerPropsClient().fetch_all_game_props(
    games,
    force_refresh=True,
    selected_event_ids=["abc123", "def456"],   # ~3 credits per event
)
```

## How to inspect quota usage

Every paid response's `x-requests-remaining` / `x-requests-used` /
`x-requests-last` headers are recorded:

```python
client = OddsAPIClient()
client.fetch_nba_games()
print(client.last_quota)
# {'credits_last': 1.0, 'credits_used': 89.0, 'credits_remaining': 411.0}
```

or read the `meta` block of today's cache file under `data/cache/odds/`.

## Recommended low-credit workflow

1. **Morning:** `fetch_events()` (free) to see the slate. No paid calls
   just to check whether games exist.
2. **Once per day:** the scheduled scanner run triggers the daily paid
   fetch (moneyline + props for the slate) and caches it.
3. **All day:** re-run scanners/models freely — everything reads cache.
4. **Pregame (optional):** `force_refresh=True, selected_event_ids=[...]`
   for only the games that survived the model's filters.
5. **Settlement:** grade paper bets from results; closing lines can be
   captured by the same selected-event refresh just before tipoff.

## Freshness vs cost trade-offs

| Strategy | Approx. monthly cost | Freshness |
|---|---|---|
| Daily snapshot only (default) | ~900 credits (full slate) | morning lines |
| + selected-event pregame refresh (2 games/night) | +~180 | near-closing for bet games |
| Full-slate refresh 2x/day | ~1,900 | better, rarely worth it |
| 5–10 min polling | tens of thousands | **forbidden by policy** |

Stale lines mostly cost us *accuracy of the market benchmark*, not model
quality — projections come from nba_api (free). When in doubt, spend
modeling effort, not credits.
