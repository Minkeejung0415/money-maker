# Architecture Research: Prop Model Upgrade

## Current Architecture Summary

### What exists

`alpha/engines/sports/prop_model.py` — `PropModel` class:
- Fetches per-player game logs via `nba_api.stats.endpoints.playergamelogs` (same-day pickle cache)
- Filters to games where player played >= 20 min
- Computes a weighted rolling average: `0.5 * avg(L5) + 0.3 * avg(L10) + 0.2 * avg(L20)`
- Applies per-market opponent adjustment (DEF_RTG for points, REB/STL/FG3M for other markets), capped at ±10–15%
- Plugs result into a Normal CDF: `P(over) = 1 - norm.cdf(line, loc=opp_adj, scale=std_dev)`
- Classifies confidence by gap vs market-implied probability (|gap| > 0.08 = HIGH, 0.04–0.08 = MEDIUM)
- Degrades HIGH → MEDIUM if player traded within last 5 games

`alpha/data/ingestion/nba_stats_cache.py` — `NBAStatsCache`:
- SQLite-backed, 6h TTL cache for all nba_api calls
- Thread-safe with 10s timeout per call, 0.5s sleep between calls
- Provides: `fetch_player_game_logs`, `fetch_league_dash_player_stats`, `fetch_league_dash_team_stats`, `fetch_player_dash_pt_shots`, `fetch_league_dash_pt_defend`, `fetch_matchup_defender`, `fetch_team_recent_form`, `fetch_head_to_head`, `fetch_player_team_game_count`, `fetch_player_team_map`

`alpha/engines/sports/nba_context.py` — `PropContextEvaluator`:
- Pipeline: position filter → shared minutes → paint deterrence → foul trouble → advanced opp stats
- Each evaluator produces a fractional adjustment to `model_prob`
- Adjustments are additive deltas on the projection percentage, then re-mapped to probability
- Wall timeout of 60s prevents runaway runs

### Measured performance

- Overall hit rate: **43.5%** (below 50% random baseline — model is directionally wrong more often than right)
- Rebounds specifically: **34.2%** (severe downward bias — model over-projects REB)
- Context evaluators run 18 min and cut 61% of legs (too aggressive, net accuracy impact unclear)
- Model is overconfident: avg predicted 82% on Mar-12 props, actual hit rate was lower

### Root causes of low accuracy (from live data)

1. **Rolling average window is equal-weighted within each bucket** — a player's game 5 days ago counts the same as yesterday's game within the L5 window
2. **Opponent adjustment is season-average only** — does not account for opponent's *recent* defensive form or matchup-specific position data (e.g., opponent's center vs. center, not team-wide DEF_RTG)
3. **Standard deviation uses full-season samples** — does not tighten when player is in a hot/cold streak; variance is overestimated for consistent players, underestimated for streaky ones
4. **No home/away split** — players systematically differ at home vs. away (avg 8–12% swing in scoring)
5. **No rest/fatigue factor** — B2B game, 4th game in 5 nights — high correlation with under performance
6. **No minutes projection** — model projects stats but doesn't know if player will play 28 or 38 min tonight
7. **Rebound model ignores team rebounding rate** — guards on high-REB teams still get over-projected
8. **Normal distribution assumption is wrong** — NBA counting stats are right-skewed (can't score -3 pts), especially assists and blocks

---

## Recommended Upgrade Path

Ordered by ROI (accuracy improvement per engineering hour, non-breaking changes first).

### Phase 1 — Fix the rolling average (highest ROI, zero new API calls)

**Change:** Replace equal-weighted buckets with exponential decay weighting across individual games.

Current: `0.5 * avg(L5) + 0.3 * avg(L10) + 0.2 * avg(L20)` — treats each of last 5 games equally

Better: Exponential decay across all 20 games: `weight[i] = lambda^i` where `lambda ≈ 0.85`

Formula: `proj = sum(values[i] * 0.85^i for i in range(N)) / sum(0.85^i for i in range(N))`

This means game-1 (yesterday) gets 1.0 weight, game-5 gets 0.44, game-10 gets 0.20, game-20 gets 0.04. Naturally emphasizes recency without brittle bucket boundaries.

**Impact:** Estimated +3–5pp on hit rate. Players in hot/cold streaks get corrected faster. Requires changing only `_weighted_avg()` in `prop_model.py` — no new data sources.

**Validation:** Run `validate_picks.py` before and after. Should see avg_diff vs proj shrink.

### Phase 2 — Home/away split (high ROI, no new API calls)

**Change:** Track home/away separately when fetching game logs. Filter qualifying games to match today's game location.

`PlayerGameLogs` rows already contain a `MATCHUP` column (e.g., `BOS vs. MIA` or `BOS @ MIA`). The `@` means away game.

Implementation: in `_fetch_game_logs()`, tag each row with `is_home: bool`. In `predict_prop()`, accept `is_home: bool` parameter and filter qualifying games to the matching home/away split. If fewer than `_MIN_GAMES` remain in the split, fall back to all games but apply a home/away multiplier derived from the split averages.

**Impact:** Estimated +3–4pp on hit rate for points/assists props. Guards especially show large home/away splits.

**Validation:** Check `avg_diff` by home/away bucket in the validate script.

### Phase 3 — Opponent allowed stats by position (high ROI, one new API endpoint)

**Change:** Replace team-wide DEF_RTG with position-level opponent allowed stats.

nba_api endpoint: `LeagueDashMatchups` already in `NBAStatsCache.fetch_matchup_defender()`. Separately, `LeagueDashPlayerStats` with `opponent_team_id` filter can give position-level opponent allowed stats.

Better approach: Use `nba_api.stats.endpoints.leaguedashplayerbiostats` (or `leaguedashptdefend` already fetched) to get per-position opponent allowed PTS, REB, AST.

The specific endpoint is `nba_api.stats.endpoints.leaguedashlineups` or more precisely `nba_api.stats.endpoints.LeagueDashOpponentPtShot` — however the simplest available source is `LeagueDashPlayerStats` with `per_mode="PerGame"` filtered by opponent team + position group.

**Simpler implementation:** Add a new `NBAStatsCache` method `fetch_opp_allowed_by_position(team_name, position_group, season)` that:
1. Calls `LeagueDashTeamStats` with `per_mode=PerGame` (already cached)
2. Filters to games where the team was the defense
3. Groups by offensive player position

This data comes from `nba_api.stats.endpoints.leaguedashptdefend` (already fetched in `PaintDeterrenceEvaluator`). Map the defensive player's position to the matching opponent position group.

**Impact:** Estimated +4–6pp on rebounds specifically (34.2% → 40%+ target). Guards facing team with poor PF/C rebounding should be penalized less.

### Phase 4 — Poisson/Negative Binomial distribution (medium ROI, no new data)

**Change:** Replace Normal CDF with Poisson CDF for low-count stats (assists, blocks, steals, threes) and Negative Binomial for points/rebounds.

NBA counting stats are discrete and right-skewed. `P(assists > 6.5)` via Normal CDF is wrong when a player averages 5.2 — it over-estimates the tail.

```python
from scipy.stats import poisson, nbinom

# For assists, blocks, steals, threes:
p_over = 1 - poisson.cdf(int(line), mu=proj)

# For points, rebounds (higher variance, overdispersed):
# Fit r,p from mean and variance: r = mean^2/(var - mean), p = mean/var
r = proj**2 / max(0.01, std**2 - proj)
p_param = proj / max(0.01, std**2)
p_over = 1 - nbinom.cdf(int(line), r, p_param)
```

This is a drop-in replacement inside `predict_prop()`. No new data. Changes two lines.

**Impact:** Estimated +2–3pp on assists/blocks props specifically. Reduces overconfidence on high lines.

### Phase 5 — Rest and schedule fatigue (medium ROI, no new API calls)

**Change:** Add days-rest penalty/boost to the projection.

Game log rows already contain `GAME_DATE`. Compute days since last game for each player's log. For today's game, the scanner already knows the game date. Compute days rest = today - last game date from the player's log.

```
rest_factor = 1.0
if days_rest == 0:   rest_factor = 0.94   # B2B — significant under-performance
if days_rest == 1:   rest_factor = 0.97   # 1 day rest — minor
if days_rest >= 3:   rest_factor = 1.02   # well-rested boost
```

Apply `opp_adj *= rest_factor` before the CDF calculation.

The `NBA-Machine-Learning-Sports-Betting` library already has `Add_Days_Rest.py` in its pipeline — the pattern is proven.

**Impact:** Estimated +2pp overall, +4pp on B2B situations specifically.

### Phase 6 — Ensemble blending with XGBoost confidence (medium ROI)

**Change:** Use the existing `NBAModel` XGBoost win probability (already running for ML picks) to gate prop confidence.

When the XGBoost model predicts a team win probability < 35%, props for players on that team should have their HIGH confidence downgraded to MEDIUM. Players on a team projected to lose by 10+ are less likely to hit volume stats (especially assists — spread out over fewer possessions in a blowout).

Implementation: `sgp_scanner.py` already has both `prop_results` and `ml_games` in scope simultaneously. Pass `ml_games` context into prop scoring and apply a blowout flag.

```python
# In sgp_scanner.py, after prop scoring:
blowout_teams = {g["away_team"] for g in ml_games if g.get("away_model_prob", 0.5) < 0.30}
blowout_teams |= {g["home_team"] for g in ml_games if g.get("home_model_prob", 0.5) < 0.30}
for prop in prop_legs:
    if prop.player_team in blowout_teams and prop.confidence == "HIGH":
        prop.confidence = "MEDIUM"
```

**Impact:** Estimated +1–2pp by eliminating assists/pts props on heavy underdogs.

---

## Component Design

### New: `ExponentialWeightedProjector` (replaces `_weighted_avg`)

Location: stays inside `PropModel` as a private method — rename `_weighted_avg` to `_exp_weighted_avg`.

```python
def _exp_weighted_avg(self, values: list[float], decay: float = 0.85) -> float:
    if not values:
        return 0.0
    weights = [decay ** i for i in range(len(values))]
    return sum(v * w for v, w in zip(values, weights)) / sum(weights)
```

Single method swap. Zero new dependencies.

### New: `HomeAwaySplit` logic inside `predict_prop`

Add `is_home: bool = True` parameter to `predict_prop()`. Propagate from `sgp_scanner.py` which already knows home/away from game data. Internal filtering:

```python
if is_home is not None:
    split = [g for g in qualifying if g.get("is_home") == is_home]
    if len(split) >= _MIN_GAMES:
        qualifying = split
    # else: fall back to all games (current behavior)
```

Tag each game log row with `is_home` in `_fetch_game_logs()` by parsing the MATCHUP column: `"@" in matchup → away game (is_home=False)`.

### New: `PositionAllowedStats` in `NBAStatsCache`

New method: `fetch_position_allowed_stats(team_name, season) -> dict[str, dict]`

Returns position-group averages allowed by `team_name` defense:
```
{"Guard": {"PTS": 22.1, "AST": 5.3, "REB": 3.8}, "Forward": {...}, "Center": {...}}
```

Data source: cross-reference `fetch_league_dash_player_stats(per_mode="PerGame")` filtered by each player's team and position. This approximates what opposing players at each position scored *against* that team.

More accurate source: `nba_api.stats.endpoints.leaguedashlineups` but that requires lineup construction. The simpler approximation (opponents' per-game stats by position) is sufficient for Phase 3.

### Modified: `_apply_opp_adjustment_for_market`

Accept an optional `player_position: str` parameter. When position is known:
- For rebounds: use position-specific REB allowed instead of team-average REB/game
- For points: blend team DEF_RTG (70%) with position-allowed PTS (30%)
- For assists: use position-specific AST allowed

When position is unknown: fall back to current team-average logic (no regression).

### Modified: `PropModel.predict_prop` signature

```python
def predict_prop(
    self,
    player_name: str,
    market: str,
    line: float,
    opponent_team: str,
    over_odds: int = -110,
    is_home: bool | None = None,      # NEW
    player_position: str | None = None,  # NEW
    days_rest: int | None = None,     # NEW
) -> dict | None:
```

All new parameters are optional with `None` defaults. Existing call sites work unchanged.

---

## Data Flow

```
[1] sgp_scanner.py
    - fetch_nba_games() → game dict (has home_team, away_team, event_id)
    - fetch_player_props() → prop lines (has player, market, line, odds)
    - for each player: resolve position from NBAStatsCache.fetch_player_info()
    - for each player: compute days_rest from last game log date
    - for each player: derive is_home from event matchup

[2] PropModel.predict_prop(player, market, line, opponent, odds,
                            is_home=True/False,
                            player_position="Guard",
                            days_rest=2)
    |
    ├── _fetch_game_logs(player) → raw logs (pickle-cached, same-day)
    |   └── tag each row: is_home = "@" not in MATCHUP
    |
    ├── filter qualifying games:
    |   - all games >= 20 min (existing)
    |   - optionally filter to matching home/away split (Phase 2)
    |
    ├── _exp_weighted_avg(values, decay=0.85) → proj_stat (Phase 1)
    |
    ├── _apply_opp_adjustment_for_market(proj, opponent, market,
    |                                     player_position=position)
    |   ├── team DEF_RTG (existing)
    |   ├── position-allowed stats by market (Phase 3)
    |   └── days_rest multiplier (Phase 5)
    |
    ├── _prob_from_distribution(line, proj, std, market) (Phase 4)
    |   ├── Poisson CDF for low-count markets (ast, blk, stl, 3pm)
    |   └── Negative Binomial CDF for pts, reb
    |
    └── return dict with model_prob, proj_stat, games_used, confidence

[3] PropContextEvaluator (existing, unchanged)
    - runs position filter, paint deterrence, foul trouble, pace adj
    - outputs adjusted_prob

[4] SGPBuilder (existing, unchanged)
    - correlation engine + EV scoring + Kelly sizing

[5] sgp_scanner.py blowout gate (Phase 6)
    - cross-check prop player_team vs ml_games model probs
    - downgrade HIGH → MEDIUM for heavy underdog team props
```

---

## Build Order

### Step 1 — Exponential decay rolling average (Day 1, 2h)

File: `alpha/engines/sports/prop_model.py`
Change: Replace `_weighted_avg` with `_exp_weighted_avg(values, decay=0.85)`
Test: Existing `tests/unit/` tests pass unchanged. Add one unit test verifying decay ordering.
Validate: Run `validate_picks.py --date 2026-03-11` before and after — avg_diff should shrink.

This is the minimum change for maximum accuracy lift. All other improvements build on top.

### Step 2 — Home/away split (Day 1, 3h)

Files:
- `alpha/engines/sports/prop_model.py` — add `is_home` param, tag logs, filter split
- `alpha/data/ingestion/nba_stats_cache.py` — no change needed (MATCHUP already in logs)
- `scripts/sgp_scanner.py` — pass `is_home` when calling `predict_prop`

Test: Unit test that home-filtered games differ from away-filtered games for a mock player.
Validate: Compare hit rates by home/away in validate script.

### Step 3 — Poisson/NB distribution (Day 2, 2h)

File: `alpha/engines/sports/prop_model.py`
Change: Add `_prob_from_distribution(line, proj, std, market)` method. Call it instead of `1 - norm.cdf(...)`.
Test: Verify Poisson gives lower probability than Normal for assists line above mean.
Validate: Should see fewer overconfident HIGH flags on assist props.

### Step 4 — Position-level opponent stats (Day 2–3, 4h)

Files:
- `alpha/data/ingestion/nba_stats_cache.py` — add `fetch_position_allowed_stats(team, season)`
- `alpha/engines/sports/prop_model.py` — add `player_position` param, use in opp adjustment
- `scripts/sgp_scanner.py` — resolve position per player before calling `predict_prop`

Test: Mock the cache method, verify position-aware adjustment differs from team-average adjustment.
Validate: Rebounds hit rate should improve most (34.2% → target 40%+).

### Step 5 — Rest/fatigue factor (Day 3, 2h)

Files:
- `alpha/engines/sports/prop_model.py` — add `days_rest` param, apply multiplier
- `scripts/sgp_scanner.py` — compute days_rest from last game log date

Test: Verify B2B games get 0.94 multiplier.
Validate: Check if B2B props historically underperform — expect yes.

### Step 6 — Blowout gate (Day 3, 1h)

File: `scripts/sgp_scanner.py`
Change: Post-prop-scoring loop that downgrades HIGH → MEDIUM for heavy underdog team props.
Test: Mock ml_games with one heavy underdog; verify confidence downgrade fires.

### Step 7 — Validate and calibrate thresholds (Day 4, all-day)

Run full validate against March 11 and March 12 data. Measure per-phase improvement. Tune:
- Exponential decay lambda (try 0.80, 0.85, 0.90)
- Home/away fallback threshold (5 games vs 3 games)
- Poisson vs NB boundary (which markets)
- Position-allowed stats blend ratio (70/30 vs 60/40)

Use `validate_picks.py` per-stat output to confirm each phase improves its target stat.

---

## Integration Points

### PropModel — add parameters, keep backward compat

All new params (`is_home`, `player_position`, `days_rest`) default to `None`. When `None`, behavior is identical to today. Call sites that don't pass them (tests, soccer/MLB mirrors) continue to work.

Pattern:
```python
if days_rest is not None:
    rest_factor = {0: 0.94, 1: 0.97}.get(days_rest, 1.02 if days_rest >= 3 else 1.0)
    opp_adj *= rest_factor
```

### NBAStatsCache — additive methods only

New method `fetch_position_allowed_stats` is purely additive. Existing methods unchanged. Method must route through `get_or_fetch()` for 6h TTL caching.

### sgp_scanner.py — thin orchestration changes

Scanner already has all game context (home/away, event_id, game date). Only needs to:
1. Pass `is_home` to `predict_prop`
2. Resolve `player_position` via `NBAStatsCache.fetch_player_info(player_id)["position"]`
3. Compute `days_rest` from `max(log["GAME_DATE"] for log in player_logs)`
4. Apply blowout gate post-scoring

### validate_picks.py — extend, don't break

Current script validates hits/misses from cached data. To validate phases:
- Add `--split home|away` flag to filter cache validation by game type
- Add per-phase contribution tracking if desired

Minimum: run existing script before and after each phase and compare per-stat numbers.

### Tests — one new test per phase

Each phase should add exactly one focused unit test to `tests/unit/test_prop_model.py` (create if needed) or `tests/unit/test_nba_scanner_features.py`. Tests should:
- Mock nba_api calls (no live API in tests)
- Assert the specific behavior change (decay ordering, home split, Poisson vs Normal, etc.)
- Not change any existing test

Target: 482 tests passing → 482 + 6 = 488 tests passing after all phases.

---

## Risk Assessment

| Phase | Risk | Mitigation |
|-------|------|------------|
| Exponential decay | May hurt recent-cold players (false signal) | Tune lambda; add fallback to old method behind `--legacy-avg` flag |
| Home/away split | Too few qualifying games in one split | Graceful fallback to all-games (already in design) |
| Poisson distribution | Integer rounding on lines like 6.5 | Use `floor(line)` as the CDF argument for discrete distributions |
| Position stats | Stale position data mid-season after trades | Position comes from `CommonPlayerInfo` which reflects current team; re-cached every 6h |
| Rest factor | Hardcoded constants may be wrong | Start conservative (0.94, 0.97, 1.02); validate before locking in |
| Blowout gate | May filter genuine value in garbage time props | Only apply to HIGH→MEDIUM, not remove legs entirely; let SGP min_edge handle the rest |

---

## What NOT to Build (for now)

- **New XGBoost prop model trained on historical prop lines**: Requires labeled historical prop data (line + result) for 2+ seasons. Not available without paid data source. No-build until data acquired.
- **Neural network ensemble**: Over-engineering before basic stat corrections are in place. Build after phases 1–6 are validated.
- **Contextual evaluator rewrite**: The 18-min runtime and 61% filter rate are problems, but the existing evaluators are architecturally sound. Fix the wall timeout (already 60s) and tune thresholds before redesigning.
- **Real-time lineup scraping**: High maintenance, fragile scraping. Existing injury pipeline already covers the most impactful cases.
