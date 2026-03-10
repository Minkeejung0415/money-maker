# SGP Generator — Coding Agent Prompt

## Your Mission

Build a production-quality NBA Same-Game Parlay (SGP) generator for an existing trading terminal.
The system must find **positive expected-value parlay combinations** by:

1. Modeling individual player props with accuracy validation built in
2. Applying an empirical correlation matrix so correlated legs are priced correctly
3. Supporting four distinct parlay modes
4. Backtesting predictions against historical outcomes so results are trustworthy, not assumed

This is not a toy — every component needs tests and the prop model must be validated before its
output is trusted.

---

## Codebase Context

**Repo root:** `C:\Users\justi\Documents\money-maker\`
**Working directory when running scripts:** repo root
**Venv:** `.\venv\` — always run Python as `.\venv\Scripts\python.exe` or prefix with `VIRTUAL_ENV=./venv`
**Package manager:** `uv` — install deps with `VIRTUAL_ENV=./venv uv pip install <pkg>`

### Existing files you will use (read these before writing anything):

| File | Purpose |
|---|---|
| `alpha/data/ingestion/odds_api.py` | `OddsAPIClient` — fetches moneyline odds, returns list of game dicts |
| `alpha/engines/sports/ev_calculator.py` | `EVCalculator` — `american_to_decimal`, `implied_prob`, `expected_value`, `has_edge` |
| `alpha/engines/sports/kelly.py` | `KellySizer` — `bet_size(win_prob, decimal_odds, bankroll)` |
| `alpha/engines/sports/nba_model.py` | `NBAModel` — XGBoost game-level win probability predictor |
| `alpha/engines/sports/engine.py` | `SportsEngine` — orchestrates NBAModel |
| `alpha/data/ingestion/nba_injuries.py` | `get_team_injury_impact()` — returns injury dict per team |
| `scripts/bet_scanner.py` | Existing game-level scanner — read to understand output style |

### Existing game dict schema (from OddsAPIClient):
```python
{
    "home_team": str,   # e.g. "Los Angeles Lakers"
    "away_team": str,
    "home_odds": int,   # American odds e.g. -150
    "away_odds": int,
    "league": "nba",
    "event_id": str,
    "commence_time": str,
}
```

### Key conventions:
- All new alpha/ modules use `from __future__ import annotations`
- Logging via `logger = logging.getLogger(__name__)` — never print() inside library code
- Graceful degradation: return `[]` or `None` on any API failure, never raise to the caller
- Tests go in `tests/unit/` — run with `VIRTUAL_ENV=./venv python -m pytest tests/unit/<file> -v`
- TDD: write the failing test first, then implement, then confirm green

---

## What To Build

### New files (in order):

```
alpha/data/ingestion/player_props.py       ← Task 1
alpha/engines/sports/prop_model.py         ← Task 2
alpha/engines/sports/prop_backtester.py    ← Task 3
alpha/engines/sports/correlation.py        ← Task 4
alpha/engines/sports/sgp_builder.py        ← Task 5
scripts/sgp_scanner.py                     ← Task 6
```

---

## Task 1 — PlayerPropsClient (`alpha/data/ingestion/player_props.py`)

**What it does:** Fetches live NBA player prop lines from The Odds API v4 — same API key as
moneyline odds (`ODDS_API_KEY` env var). Returns one canonical dict per player per market per game.

**Odds API markets to support:** `player_points`, `player_rebounds`, `player_assists`, `player_threes`

**Odds API response shape** (each outcome inside a market):
```json
{"name": "LeBron James", "description": "Over", "price": -115, "point": 27.5}
```

**Canonical output dict:**
```python
{
    "event_id":   str,    # Odds API game ID
    "home_team":  str,
    "away_team":  str,
    "player":     str,    # e.g. "LeBron James"
    "market":     str,    # e.g. "player_points"
    "line":       float,  # e.g. 27.5
    "over_odds":  int,    # American odds e.g. -115
    "under_odds": int,
    "bookmaker":  str,    # which book had best over odds
}
```

**Deduplication rule:** when multiple bookmakers offer the same player/market, keep the one with
the highest (most favorable) over odds.

**Tests to write (`tests/unit/test_player_props.py`):**
1. `test_parse_props_returns_canonical_dicts` — FAKE_RESPONSE with two players → 2 dicts, verify all fields
2. `test_no_api_key_returns_empty` — empty api_key → `[]`
3. `test_http_error_returns_empty` — mock requests.get to raise → `[]`
4. `test_markets_filtered_to_supported` — response with unsupported market key → excluded from output
5. `test_deduplication_keeps_best_over_odds` — two bookmakers same player → keep the one with higher over_odds

---

## Task 2 — PropModel (`alpha/engines/sports/prop_model.py`)

**What it does:** For a given player + stat line, predicts P(player hits over the line). Uses
nba_api game logs with a weighted rolling average and a normal distribution fit.

**Algorithm:**
```
proj_stat  = 0.5 * avg(last 5g) + 0.3 * avg(last 10g) + 0.2 * avg(last 20g)
             (only use games where player played ≥ 20 minutes)
std_stat   = stddev(last 20g values, min_std=1.0)
opp_adj    = proj_stat * (league_avg_def_rtg / opp_def_rtg)   # only for player_points
p_over     = 1 - norm.cdf(line, loc=opp_adj, scale=std_stat)
p_over     = clip(p_over, 0.01, 0.99)
```

**Market → column mapping:**
```python
{
    "player_points":   "PTS",
    "player_rebounds": "REB",
    "player_assists":  "AST",
    "player_threes":   "FG3M",
}
```

**nba_api calls:**
- `nba_api.stats.endpoints.playergamelogs.PlayerGameLogs` — player's recent game log
- `nba_api.stats.endpoints.leaguedashteamstats.LeagueDashTeamStats` — team defensive ratings
- Sleep 0.6s between calls (rate limit)

**Public method:**
```python
def predict_prop(self, player_name: str, market: str, line: float, opponent_team: str) -> dict | None:
    # Returns:
    # {
    #   "player": str, "market": str, "line": float,
    #   "proj_stat": float, "std_stat": float,
    #   "model_prob": float,  # P(over)
    #   "games_used": int,    # how many games fed into model
    #   "source": "nba_api"
    # }
    # Returns None if < 5 games available
```

**Model confidence tiers (add to output):**
```python
"confidence": "HIGH"    # model_prob vs market_implied gap > 8%
"confidence": "MEDIUM"  # gap 4-8%
"confidence": "LOW"     # gap < 4% — model uncertain, skip in SGP builder
```

To compute confidence, predict_prop needs the market implied prob passed in or the over_odds.
Add `over_odds: int = -110` as a parameter.

**Tests to write (`tests/unit/test_prop_model.py`):**
1. `test_high_avg_beats_low_line` — mock logs returning 30 pts avg, line=25 → model_prob > 0.7
2. `test_low_avg_misses_high_line` — mock logs returning 20 pts avg, line=25 → model_prob < 0.3
3. `test_returns_none_on_empty_logs` — mock returns empty df → None
4. `test_filters_low_minute_games` — mock logs with some MIN=15 rows → those excluded
5. `test_weighted_avg_favors_recent` — last 5g avg=35, last 20g avg=15 → proj > simple avg
6. `test_market_col_mapping` — _market_col("player_points") == "PTS", etc.
7. `test_confidence_high_when_large_gap` — model 65%, market 52% → HIGH
8. `test_confidence_low_when_small_gap` — model 54%, market 52% → LOW

---

## Task 3 — PropBacktester (`alpha/engines/sports/prop_backtester.py`)

**Why this exists:** We don't trust the normal distribution model until we've validated it against
real historical outcomes. This module uses nba_api historical game logs to check:
given a player's stats up to game N, how often does the model's prediction match what
actually happened in game N+1?

**This is the accuracy check.** Output tells us whether to trust the model.

**Algorithm:**
```
For each player in player_names:
  logs = fetch last 60 game logs from nba_api
  For each game i from 20 to len(logs)-1:       # need 20 games of history
    training_logs = logs[i:]                     # games before game i (newer = lower index)
    actual_value  = logs[i-1][col]               # the game we're predicting
    proj = weighted_avg(training_logs[:20])
    std  = stddev(training_logs[:20])
    p_over = 1 - norm.cdf(actual_value - 0.5, proj, std)  # use actual as the "line"
    Record: predicted_prob, actual_hit (1 or 0), confidence_tier
```

**Wait — that's not quite right.** We don't have historical prop lines. So instead we use the
player's own rolling average as a synthetic line:
```
synthetic_line = rolling_avg(games before i)
predicted_prob = p_over = 0.5 + (proj - synthetic_line) / (std * sqrt(2*pi)) * something
```

Actually simpler: just check **calibration** — for all predictions where model says 60-65%,
do they hit 60-65% of the time? If yes, model is calibrated and trustworthy.

**Use this approach:**
```
For each game i (using game i-1 as the outcome to predict):
  line = rolling avg of last 10 games (games i to i+9)    # synthetic line = their own average
  actual = logs[i-1][col]
  pred_prob = model's P(actual > line)         # should be ~0.5 since line ≈ avg
  actual_hit = 1 if actual > line else 0
  bucket pred_prob into deciles
Report: calibration table, hit rate by bucket, Brier score, confidence-tier accuracy
```

**Output:**
```python
{
    "player": str,
    "market": str,
    "n_predictions": int,
    "overall_hit_rate": float,        # should be ~0.50 (since line = rolling avg)
    "brier_score": float,             # lower = better calibrated (0.25 = random)
    "calibration": {                  # bucket → {"predicted": float, "actual": float, "n": int}
        "0.40-0.50": {...},
        "0.50-0.60": {...},
        "0.60-0.70": {...},
        ...
    },
    "high_conf_hit_rate": float,      # hit rate when model confidence is HIGH (>8% gap)
    "recommendation": str,            # "RELIABLE" / "MARGINAL" / "UNRELIABLE"
}
```

**Reliability thresholds:**
- `RELIABLE`: Brier score < 0.22, high_conf_hit_rate > 0.60
- `MARGINAL`: Brier score < 0.25
- `UNRELIABLE`: Brier score ≥ 0.25 (model is no better than random)

**Public interface:**
```python
def backtest(self, player_names: list[str], markets: list[str], season: str = "2024-25") -> list[dict]
def print_report(self, results: list[dict]) -> None
```

**CLI usage (add to sgp_scanner.py later):**
```bash
python scripts/sgp_scanner.py --validate          # runs backtest on today's players before scanning
```

**Tests to write (`tests/unit/test_prop_backtester.py`):**
1. `test_brier_score_perfect_predictions` — all pred=1.0 and all hit=1 → brier=0.0
2. `test_brier_score_random_predictions` — all pred=0.5 → brier=0.25
3. `test_calibration_buckets_correct_keys` — result has expected decile keys
4. `test_recommendation_reliable_when_low_brier` — brier=0.18, hc_hit=0.65 → RELIABLE
5. `test_recommendation_unreliable_when_high_brier` — brier=0.28 → UNRELIABLE
6. `test_skips_players_with_insufficient_data` — < 25 games → player excluded from results

---

## Task 4 — CorrelationEngine (`alpha/engines/sports/correlation.py`)

**What it does:** Builds an empirical correlation matrix. For each pair of (playerA_stat, playerB_stat),
computes Pearson r between their binary "did they exceed their rolling average?" vectors across
shared games. Also computes player_stat vs team_win correlation.

**Key concept — why correlation matters for SGPs:**
- Book prices SGP legs as independent (multiplies implied probs)
- Positive correlation (r > 0.25): true joint prob is HIGHER than naive product
  → book's SGP price is actually FAIR or UNDERPRICED for the bettor, but also reduces your edge calculation
- Negative correlation (r < -0.25): true joint prob is LOWER than naive product
  → book OVERPRICES the joint, so naive market_implied is too high
  → ONLY worth playing if your individual model edges are strong enough to overcome this

**The real SGP edge:** Find legs where:
1. Each individual leg has HIGH model confidence (>8% gap from market)
2. Legs are near-neutral correlated (−0.25 to +0.25)
3. Combined model prob beats combined market implied by >5%

**Correlation adjustment formula (bivariate normal copula approximation):**
```python
def adjust_joint_prob(p_a, p_b, r):
    correction = r * sqrt(p_a * (1 - p_a) * p_b * (1 - p_b))
    return clip(p_a * p_b + correction, 0.001, 0.999)
```

For N legs, apply pairwise from left to right, using average r against all previous legs.

**Cache:** Pickle to `data/.corr_cache.pkl` with 24-hour TTL. Rebuild is slow (nba_api calls).

**Public interface:**
```python
def build(self, player_names: list[str], season: str, force_rebuild: bool = False) -> None
def get_correlation(self, player_a: str, market_a: str, player_b: str, market_b: str) -> float
def adjust_joint_prob(self, p_a: float, p_b: float, r: float) -> float
def adjust_multi_leg_prob(self, legs: list[tuple[float, str, str]]) -> float
    # legs = [(model_prob, player_name, market), ...]
def classify(self, r: float) -> CorrelationType  # POSITIVE / NEUTRAL / NEGATIVE
```

**Tests to write (`tests/unit/test_correlation.py`):**
1. `test_perfect_positive_correlation` — identical binary vectors → r ≈ 1.0
2. `test_perfect_negative_correlation` — opposite vectors → r ≈ -1.0
3. `test_adjust_joint_positive_r_increases_above_product` — p_a=0.6, p_b=0.55, r=0.4 → result > 0.6*0.55
4. `test_adjust_joint_negative_r_decreases_below_product` — r=-0.4 → result < 0.6*0.55
5. `test_classify_thresholds` — r=0.4→POSITIVE, r=0.1→NEUTRAL, r=-0.3→NEGATIVE
6. `test_unknown_pair_returns_zero` — pair not in matrix → 0.0
7. `test_multi_leg_single_leg_returns_prob` — one leg → returns that leg's prob unchanged

---

## Task 5 — SGPBuilder (`alpha/engines/sports/sgp_builder.py`)

**What it does:** Takes scored prop legs (from PropModel), generates all valid combinations for
the chosen mode, applies correlation-adjusted probability, computes EV vs market, filters to
positive edge, ranks by EV, returns top N with Kelly stake.

**IMPORTANT: Only use HIGH or MEDIUM confidence legs in SGP combinations.** LOW confidence legs
(model gap < 4%) must be excluded — they add noise not edge.

**Four modes:**

| Mode | Legs | Description |
|---|---|---|
| `PROPS_ONLY` | 2–4 props, same game | Pure player prop parlay |
| `MONEYLINE_SGP` | ML + 1–3 props, same game | ML combined with player props |
| `MIXED_SGP` | 2–5 any combo, same game | ML and/or props, maximally flexible |
| `CLASSIC_PARLAY` | 2–4 ML bets, different games | Traditional multi-game parlay (independent legs) |

**Dataclasses:**
```python
@dataclass
class PropLeg:
    player: str
    market: str
    line: float
    model_prob: float
    over_odds: int
    event_id: str
    home_team: str
    away_team: str
    confidence: str    # "HIGH" / "MEDIUM" / "LOW"
    direction: str = "over"

@dataclass
class ParlayCombination:
    legs: list          # PropLeg or dict (for ML legs)
    mode: SGPMode
    combined_model_prob: float
    combined_market_prob: float
    combined_decimal_odds: float
    ev: float
    edge: float
    correlation_note: str = ""
    stake: float = 0.0
    confidence_summary: str = ""  # "2x HIGH, 1x MEDIUM" etc.
```

**EV formula:**
```python
combined_model_prob  = corr.adjust_multi_leg_prob(legs)       # correlation-adjusted
combined_market_prob = product of implied_prob(leg.over_odds) # book's naive assumption
combined_decimal_odds = product of american_to_decimal(leg.over_odds)
ev   = combined_model_prob * (combined_decimal_odds - 1) - (1 - combined_model_prob)
edge = combined_model_prob - combined_market_prob
```

**MONEYLINE_SGP correlation warning:** If the ML team is the same team as a player prop, flag
it in correlation_note: "⚠ ML+player same team: positively correlated, book may price correctly."
This is not an automatic disqualifier but should be shown to the user.

**Classic parlay:** Independent games → simple probability multiplication, no correlation engine needed.

**Tests to write (`tests/unit/test_sgp_builder.py`):**
1. `test_props_only_requires_2_legs_minimum` — 1 leg → returns []
2. `test_low_confidence_legs_excluded` — only LOW confidence legs → returns []
3. `test_props_only_2_legs_ev_calculation` — mock corr engine, verify EV formula correct
4. `test_ev_positive_when_model_beats_market` — model_joint=0.50, market_joint=0.275 → EV > 0
5. `test_results_sorted_ev_descending` — 3 combos with different EVs → sorted correctly
6. `test_classic_parlay_uses_product_not_corr` — 2 independent games → combined_prob = p1 * p2
7. `test_moneyline_same_team_prop_flags_warning` — ML Lakers + LeBron points → corr note contains "⚠"
8. `test_kelly_stake_attached_to_results` — all returned combos have stake > 0

---

## Task 6 — SGP Scanner CLI (`scripts/sgp_scanner.py`)

**Entry point.** Orchestrates the full pipeline end to end.

**CLI arguments:**
```
--mode        props | ml_sgp | mixed | parlay     (default: props)
--bankroll    float                                (default: 10000)
--min-edge    float                                (default: 0.05)
--max-legs    int                                  (default: 4)
--markets     comma-separated market keys          (default: player_points,player_rebounds,player_assists)
--top         int                                  (default: 5)
--no-corr     flag: skip correlation matrix build  (faster, less accurate)
--validate    flag: run PropBacktester first and show calibration report
--confidence  HIGH | MEDIUM | ALL                  (default: MEDIUM — include HIGH and MEDIUM only)
```

**Pipeline steps (print progress for each):**

```
[1/6] Fetching today's NBA games...
[2/6] Fetching player prop lines...
[3/6] Running prop model (nba_api)...        ← shows player count, warns on slow
[4/6] Building correlation matrix...          ← shows "loaded from cache" or "building..."
[5/6] Running backtest validation...          ← only if --validate flag
[6/6] Building SGP combinations...
```

**Output format per combination:**
```
#1  EV: 12.3%  |  Edge: 8.1%  |  Odds: 4.20x  |  Stake: $42.00
    Model Prob: 31.2%  vs  Market Implied: 23.8%
    Confidence: 2x HIGH, 1x MEDIUM
    Correlation: LeBron vs AD: r=-0.18 (neutral); LeBron vs Tatum: r=0.08 (neutral)
    Legs:
      • LeBron James: OVER 27.5 pts  (-115)  model: 63.4%  [HIGH]
      • Anthony Davis: OVER 12.5 reb  (-110)  model: 61.2%  [HIGH]
      • Jayson Tatum: OVER 29.5 pts  (-110)  model: 57.8%  [MEDIUM]
```

**If --validate flag:** Run PropBacktester on today's players, print report first:
```
=== PROP MODEL VALIDATION ===
LeBron James / player_points:  RELIABLE  (Brier: 0.21, HC hit rate: 64.2%)
Anthony Davis / player_rebounds: MARGINAL (Brier: 0.24, HC hit rate: 58.1%)
Jayson Tatum / player_points:  RELIABLE  (Brier: 0.20, HC hit rate: 66.3%)

⚠ UNRELIABLE players excluded from SGP: [...]
```

Then exclude UNRELIABLE players from the SGP build entirely.

**Tests to write (`tests/unit/test_sgp_scanner.py`):**
1. `test_cli_help_exits_cleanly` — `--help` → exit code 0, "mode" in stdout
2. `test_cli_no_api_key_exits_gracefully` — no ODDS_API_KEY → no traceback

---

## Accuracy Honesty Rules — Bake These Into The Code

These must be enforced in the code, not just documentation:

1. **PropModel.predict_prop() must attach confidence tier.** LOW confidence props must NOT be
   passed to SGPBuilder. Filter them out in the scanner before building combos.

2. **SGPBuilder must reject LOW confidence legs.** Even if the scanner passes them, SGPBuilder
   has a guard: `if leg.confidence == "LOW": skip this leg`.

3. **Correlation adjustment is an approximation.** Add a docstring warning to
   `adjust_multi_leg_prob`: "This is a first-order bivariate copula approximation. Accuracy
   degrades for N > 3 legs. For 4+ legs, treat combined_model_prob as a lower bound."

4. **PropBacktester result is shown in scanner output.** Even without `--validate`, the scanner
   should note: "Prop model not validated — run with --validate to check calibration."

5. **Minimum games guard.** PropModel returns None if < 5 qualifying games (≥20 min played).
   SGPBuilder skips any prop with model_prob = None. Scanner reports how many props were
   excluded for insufficient data.

---

## Dependencies to Install

```bash
VIRTUAL_ENV=./venv uv pip install scipy nba_api
```

Check if already installed first:
```bash
VIRTUAL_ENV=./venv python -c "import scipy, nba_api; print('ok')"
```

---

## Definition of Done

- [ ] All 6 files created
- [ ] All 36+ unit tests passing: `VIRTUAL_ENV=./venv python -m pytest tests/unit/ -v`
- [ ] Full test suite still green: `VIRTUAL_ENV=./venv python -m pytest tests/ -v`
- [ ] `python scripts/sgp_scanner.py --help` exits cleanly
- [ ] `python scripts/sgp_scanner.py --mode parlay` runs end-to-end (parlay mode needs no prop API calls)
- [ ] Props mode runs with `--no-corr` flag (avoids slow nba_api correlation build)
- [ ] Commits: one per task (6 commits total)

## Run Order for Manual Testing

```bash
# 1. Fastest check — classic parlay (no props API needed)
.\venv\Scripts\python.exe .\scripts\sgp_scanner.py --mode parlay

# 2. Props with no correlation (fast)
.\venv\Scripts\python.exe .\scripts\sgp_scanner.py --mode props --no-corr --min-edge 0.03

# 3. Full props with correlation (slow — 2-5 min due to nba_api rate limits)
.\venv\Scripts\python.exe .\scripts\sgp_scanner.py --mode props

# 4. Validate model calibration (slow — runs backtest)
.\venv\Scripts\python.exe .\scripts\sgp_scanner.py --mode props --validate
```
