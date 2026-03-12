# Features Research: NBA Prop Accuracy

**Context:** Current model hit rate = 43.5% overall, 34.2% on rebounds.
Current implementation uses weighted rolling avg (50% last-5, 30% last-10, 20% last-20)
+ opponent DEF_RTG adjustment for points only. This document identifies what actually moves the needle.

---

## Table Stakes (must-have features)

Every competitive NBA prop model includes these. Absence of any one tanks accuracy.

### 1. Player Baseline — Rolling Weighted Average
- **What it is:** Recency-weighted average of per-game stat over last 5 / 10 / 20 games.
- **Current status:** IMPLEMENTED. Weights: 50/30/20.
- **Issue:** Window is applied to all games regardless of minutes played. A 12-minute DNP-adjacent game gets the same weight as a 36-minute starter game.
- **Fix needed:** Filter to games ≥ 18 minutes AND normalize to per-36 before averaging, then re-scale to projected minutes for tonight.

### 2. Minutes Projection
- **What it is:** How many minutes will the player play tonight?
- **Current status:** NOT IMPLEMENTED. The model uses raw totals without minutes normalization.
- **Why it matters:** A player averaging 28 pts/game at 34 min/game, playing 38 min tonight = different projection than playing 28 min. This alone explains 3–5% of model error.
- **Data source:** Season avg MIN from LeagueDashPlayerStats; recent trend from last-5 game logs; starter vs bench flag from CommonPlayerInfo.

### 3. Opponent Defensive Rating (DRTG) — Position-Specific
- **What it is:** How many points per 100 possessions does the opponent allow to the player's position?
- **Current status:** PARTIALLY IMPLEMENTED. Points uses overall DRTG. Rebounds uses opponent REB/game (wrong — see Rebound section). Assists uses opponent STL/game (weak proxy).
- **Why it matters:** A team's DRTG of 108 doesn't tell you what they allow to point guards vs centers. Point guards playing against Milwaukee (excellent wing defenders, weaker PG coverage) need a different scale factor than centers.
- **Data source:** LeagueDashPlayerStats by position + opponent; or nba.com/stats "Opponent Stats by Position" endpoint.

### 4. Home/Away Split
- **What it is:** Binary indicator; player's historical performance differential at home vs away.
- **Current status:** NOT IMPLEMENTED as a feature. The model doesn't track home/away.
- **Why it matters:** On average, home players score +1.2 pts, +0.4 reb, +0.3 ast compared to road games. For some players (travel-sensitive stars, players with home crowd energy) the split is 2–4x the average.
- **Data source:** Filter game logs by MATCHUP column ("vs." = home, "@" = away). Compute separate rolling averages.

### 5. Line Quality / Market-Implied Probability
- **What it is:** The closing line from books represents sharp market consensus. Departure from it = edge or noise.
- **Current status:** IMPLEMENTED via `_american_to_implied()` and confidence gap classification.
- **Note:** This is table stakes but the implementation is correct.

### 6. Injury / Roster Context
- **What it is:** Is the player's teammate who normally takes shots/rebounds/assists out tonight?
- **Current status:** PARTIALLY IMPLEMENTED via ESPN injury fallback; no teammate-impact adjustments to the actual projection.
- **Why it matters:** When a team's primary ball-handler is out, the backup assist leader's line moves +1.5 ast on average. Books price this in within minutes; the model needs to catch it simultaneously.
- **Data source:** nba_injuries.py ESPN fallback already implemented; need to wire usage-share logic into PropModel.

---

## Differentiators (what adds the most lift)

Ranked by estimated accuracy improvement based on sport analytics research and betting model literature.

### 1. Position-Specific Opponent Allowed Stats — +4–6% accuracy lift
**The single highest-impact missing feature.**

Current: opponent REB/game used for rebound props (wrong direction — see Rebounds section).
Needed: "Opponent rebounds allowed to [C/PF/SF/PG/SG] per game" from nba.com Opponent Stats by Position.

Implementation:
- Fetch LeagueDashMatchups or OpponentPlayerStats grouped by opponent team + position
- Build lookup: `{opponent_team: {position: {reb_allowed_pg, pts_allowed_pg, ast_allowed_pg}}}`
- Scale player projection by (position_allowed / league_avg_allowed_at_position)

Why it lifts: Overall DRTG is a blunt instrument. A team with DRTG 108 could be elite at stopping wings but terrible at containing centers. Position-level opponent stats separate that signal. Rebounds especially: opponent rebounding rate by CENTER position vs. PF position differs by 15–20% across the league.

### 2. Minutes-Normalized Projections with Tonight's Minutes Estimate — +3–4% accuracy
Current model uses raw totals. A player who plays 24 mpg averaging 12 pts/game has the same raw number as a player who plays 36 mpg averaging 12 pts/game — but the first player's per-36 rate is 18 and would spike if his minutes increase.

Approach:
- Compute per-36 rolling average instead of raw average
- Multiply by projected minutes tonight (season avg MPG ± back-to-back adjustment)
- This correctly handles: rest-day starters getting extra minutes, blow-out scenarios where stars sit, injury-driven lineup changes

### 3. Back-to-Back Game Flag — +2–3% accuracy
The NBA-Machine-Learning-Sports-Betting cloned repo already uses `Days_Rest_Home` and `Days_Rest_Away` — proof this signal is real for game-level prediction. For props:

- 0 days rest (back-to-back): apply -5% to -8% on counting stats (fatigue effect)
- 1 day rest: baseline
- 2+ days rest: apply +2% (fresh legs) — especially for big men who play heavy minutes
- Stars are MORE affected than role players (minutes load is higher)
- Data source: compute from game log dates — already feasible with existing MATCHUP + GAME_DATE columns

### 4. Pace Adjustment (Possessions per Game) — +2–3% accuracy
Current status: IMPLEMENTED in nba_context.py via `AdvancedOpponentStats.get_pace_adjustment()`.
Gap: it's computed but the adjustment magnitude is small (pace_factor - 1.0 applied linearly to model_prob, not to the underlying stat projection).

Better approach: Apply pace factor to the stat projection BEFORE deriving probability:
```
proj_stat_adjusted = proj_stat_per_poss * expected_possessions_tonight
expected_poss = (player_team_pace + opponent_pace) / 2
```
This is what Cleaning the Glass and Second Spectrum-backed models use.

### 5. Recent Form Trend — +1.5–2% accuracy
Current: 50/30/20 weighted average is static recency weighting.
Better: Add a momentum signal that captures whether recent games are trending UP or DOWN.

- Compute: slope of last-7 games linear regression on the stat
- Positive slope (trending up): boost projection by slope * 0.5
- Negative slope (declining): discount by slope magnitude * 0.5
- Cap adjustment at ±10% of base projection
- Especially important for: players returning from injury, players entering hot streaks, rookies adjusting to NBA speed

### 6. Opponent Recent Form (Last 5 Games Defensive Performance) — +1.5–2% accuracy
Current: Season-average DRTG used as opponent quality signal.
Problem: DRTG from October doesn't reflect that the team's best defender got injured in February.

- Fetch opponent team's last-5 game defensive stats (points allowed, REB allowed, etc.)
- Blend: 60% season DRTG + 40% last-5 game defensive performance
- Data source: TeamGameLog for opponent — already implemented in `nba_stats_cache.fetch_team_recent_form()`; just needs to be wired into PropModel's opponent adjustment

### 7. Usage Rate in Current Lineup Configuration — +1–2% accuracy
- When a teammate is out, does the player's usage rate increase?
- USG% from LeagueDashPlayerStats; cross-reference with injured players tonight
- If player's top 2 usage teammates are out, scale up the player's projection by (team_usg% redistributed to him)

### 8. Vs. Specific Opponent Historical Performance — +1% accuracy (with caveats)
- Player's career stats against THIS opponent team (last 3 seasons)
- Only reliable if 6+ games exist against that opponent
- Significant matchup-specific patterns exist (some players always go off vs. certain teams)
- Data source: PlayerGameLogs filtered by MATCHUP column for opponent abbreviation
- CAVEAT: Overfits with small samples; weight down if < 8 career games vs. opponent

---

## Rebound Model Features

The 34.2% rebound hit rate is the worst performing market. Root causes and fixes:

### Root Cause 1: Wrong Opponent Metric (Primary Bug)
**Current implementation:**
```python
# market == "player_rebounds"
league_avg = _LEAGUE_AVGS["reb_pg"]   # 43.5 (team total)
opp_val = opp.get("reb_pg", league_avg)
scale = max(lo, min(hi, league_avg / opp_val))  # HIGH opp REB → scale DOWN
```

**Why this is wrong:** A team that grabs lots of rebounds on offense is NOT the same as a team that gives up rebounds. This logic penalizes players facing good offensive rebounding teams, but what actually matters is: how many defensive rebounds does the opponent surrender? More opposing team defensive rebounds = fewer for our player.

**Fix:** Use opponent-allowed defensive rebound rate:
- `opp_dreb_allowed_pg` = how many DREBs per game does this opponent surrender to opponents?
- High value = loose rebounding team = more boards available for our player
- Low value = tight rebounding team = boards locked up

### Root Cause 2: Position Not Weighting the Projection
**Current:** PositionFilter suppresses props for guards/SFs with avg_reb < 5.0.
**Missing:** There's no scaling of the opponent adjustment by position. A center facing a big-man-heavy opponent gets the same scale factor as a point guard facing that opponent. The factor needs to be position-specific.

Position-specific opponent rebound surrender rates:
- Opponents surrender DREBs to C/PF at a very different rate than to guards
- Some teams are weak at crashing the boards against big men but lock up guard rebounders
- Data source: nba.com Opponent Stats by Position; or estimate from LeagueDashMatchups

### Root Cause 3: Contested Rebound Rate Ignored
**Missing feature:** How many of the available rebounds in this game are likely to be contested vs. uncontested?
- Teams that play uptempo (high pace, lots of possessions) generate more rebound opportunities
- Teams that run zone defense generate different rebound distributions than man-to-man
- Proxy: (opp_DREB_pct) — opponent's defensive rebound percentage. High DREB_pct opponent = leaves fewer for us.

**Implementation:**
```
opp_dreb_pct = opp_DREB / (opp_DREB + opp_OREB_allowed)  # from team stats
scale = league_avg_dreb_pct / opp_dreb_pct
```

### Root Cause 4: Team Pace Not Applied to Rebounds
**Current:** Pace adjustment is computed but only applied to points market. Rebounds are a counting stat that scales with possessions too — a pace of 110 vs 98 generates ~12% more possessions and therefore ~12% more rebound opportunities.

### Root Cause 5: Minutes Volatility for Big Men
Big men (primary rebounders) have the highest minutes variance due to: foul trouble, lineup matchups, blow-out garbage time. The std_stat floor of 1.0 rebounds is too low for guards (fine) but too loose for centers who can swing from 4 rebounds in 20 minutes to 11 rebounds in 38 minutes.

**Fix:** Apply position-specific std_stat floor:
- Guards: floor = 0.8
- Forwards: floor = 1.2
- Centers: floor = 1.5

### Rebound Feature Priority List (implement in this order):

1. Replace `opp_reb_pg` with `opp_dreb_pct` (defensive rebound percentage) — 1 hour
2. Add `opp_dreb_allowed_to_position` lookup — 4 hours
3. Add pace scaling to rebound projection — 1 hour
4. Apply position-specific std floor — 30 minutes
5. Add home/away rebound split (big men especially) — 2 hours

---

## Anti-Features (things that hurt)

### 1. Overall DRTG for Non-Points Markets
Currently: DRTG (defensive rating) is used to scale rebounds and assists via proxy stats.
Problem: DRTG measures points allowed per 100 possessions — it's a points metric. Using it to adjust assists or rebounds is statistically invalid. A team with great DRTG might achieve it through paint defense (affects scoring) but be average at limiting assists.

**Verdict:** Remove DRTG from non-points markets. Use market-specific metrics only.

### 2. Raw Opponent STL/game for Assists
Current: `stl_pg` used as proxy for "how well does the opponent disrupt passing?"
Problem: Team steals correlate weakly (r ≈ 0.3) with assists allowed. Teams like Boston steal very little (good position defense) but allow very few assists. Teams that gamble for steals (Memphis style) have high STL but opponents still rack up assists because of all the open driving lanes after a gamble.

**Better:** Use `opp_ast_pg` — how many assists per game does the opponent ALLOW? This is the direct metric.

### 3. Opponent REB/game for Rebound Props (Confirmed Bug)
Already covered above. Using team offensive rebounding as a proxy for "how hard will it be to rebound against this team" is directionally wrong half the time.

### 4. Season-Long Averages Without Recency Weighting for Opponent Defense
Using season-average opponent DRTG from October through March treats a team's February defensive performance the same as its October performance. Teams change lineups, develop chemistry, and rotate players differently. A 10-game rolling opponent defensive metric is more predictive than season average.

### 5. Overconfident Probability Outputs from Gaussian Model
The Gaussian (normal distribution) model underestimates the fat tails of player stat distributions. NBA players frequently have outlier games (double their average, or zero). The model's 97% confidence on Cameron Johnson 8.5 pts is likely overfit to the normal distribution — true probability is lower because of injury/blowout/foul trouble tail risk.

**Fix already partially in place:** `MAX_XGB_CONF = 0.73` caps overconfident XGBoost picks. Same philosophy should cap PropModel raw outputs at 0.88 max (not 0.99).

### 6. Using Binary Position Classification (Guard vs. Not-Guard)
Current: PositionFilter uses string matching on position labels to gate rebound props.
Problem: The position label from CommonPlayerInfo can be stale (player listed as "G-F" but plays 80% of minutes as a full small forward now). Using role (usage, position on court via tracking data) is more accurate than label.

---

## Feature Dependencies

### Data Already Available (nba_api, existing cache)

| Feature | Source | Endpoint / Method |
|---|---|---|
| Rolling avg (5/10/20) | nba_api | `PlayerGameLogs` |
| Opponent DRTG | nba_api | `LeagueDashTeamStats(measure_type=Defense)` |
| Opponent REB/game | nba_api | `LeagueDashTeamStats(measure_type=Base)` |
| Player position | nba_api | `CommonPlayerInfo` |
| Team pace | nba_api | `LeagueDashTeamStats(measure_type=Advanced)` |
| Player avg minutes | nba_api | `LeagueDashPlayerStats` |
| Days rest | Computed | GAME_DATE diff from PlayerGameLogs |
| Home/Away flag | Computed | MATCHUP column in PlayerGameLogs |
| Recent team form | nba_api | `TeamGameLog` — already in NBAStatsCache |
| Player vs. specific opponent | Computed | Filter PlayerGameLogs by MATCHUP |

### Data Requiring New Fetches (medium effort)

| Feature | Source | Effort |
|---|---|---|
| Opponent DREB% (defensive rebound pct) | `LeagueDashTeamStats` Advanced | LOW — same endpoint, new column |
| Opponent stats allowed by position | nba.com `LeagueSeasonMatchups` | MEDIUM — new endpoint, needs position join |
| Opponent AST allowed per game | `LeagueDashTeamStats` Base | LOW — same endpoint, OPP_AST column |
| Player per-36 stats | `LeagueDashPlayerStats(per_mode=Per36)` | LOW — already fetched in NBAStatsCache |
| USG% impact of teammate absences | `LeagueDashPlayerStats` + injury list | MEDIUM — logic to redistribute usage |
| Stat trend slope (linear regression) | Computed | LOW — numpy polyfit on PlayerGameLogs |

### Data Requiring External Sources (high effort or paid)

| Feature | Source | Effort |
|---|---|---|
| Tracking data (speed, distance) | NBA Second Spectrum | HIGH — requires partnership/license |
| True shot quality | Synergy Sports | HIGH — paid data |
| Matchup-specific tracking | nba.com/stats tracking (limited) | MEDIUM — some tracking endpoints in nba_api |
| Lineup-on/off splits | nba_api `TeamPlayerOnOffSummary` | MEDIUM — new endpoint |

---

## Implementation Priority Order

Given the 34.2% rebound rate and 43.5% overall rate, here is the recommended fix sequence:

**Phase 1 — Fix the bugs (immediate, 1–2 days):**
1. Replace `opp_reb_pg` with `opp_dreb_pct` in rebound adjustment
2. Replace `opp_stl_pg` with `opp_ast_allowed_pg` in assists adjustment
3. Add home/away split to player rolling average (separate home/away windows)
4. Cap max model_prob at 0.88 instead of 0.99

**Phase 2 — Add position-specific opponent stats (2–3 days):**
5. Implement position-specific opponent stat lookup via LeagueDashMatchups
6. Add pace scaling to rebound projection (not just points)
7. Add per-36 normalization with minutes projection

**Phase 3 — Add differentiating features (3–5 days):**
8. Back-to-back game flag with fatigue discount
9. Recent form slope (linear trend over last-7 games)
10. Opponent recent 5-game defensive performance (blended with season avg)
11. Usage rate adjustment when teammate is out (injury context)
