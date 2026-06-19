# Phase 6: Match Model - Context

**Gathered:** 2026-06-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 6 delivers `alpha/engines/sports/wc_model.py` — a standalone Elo-logistic match model
for WC 2026 that reads from the Phase 5 data layer (wc_elo.py + wc_stats.py) and produces
calibrated W/D/L probabilities (or Win-to-Advance in knockouts) with a market divergence flag.
WC games NEVER route through SoccerModel. All 4 MODEL requirements are satisfied here.

</domain>

<decisions>
## Implementation Decisions

### WCMatchModel Class Design
- New file: `alpha/engines/sports/wc_model.py` — imports NOTHING from `soccer_model.py`
- Class: `WCMatchModel(min_edge=0.04)` mirroring SoccerModel constructor signature
- `__init__`: loads Elo ratings via `load_wc_elo_ratings()` (raises FileNotFoundError if json missing); loads team stats via `get_wc_team_stats()` (graceful catch — logs warning, uses empty dict on FileNotFoundError so model works without StatsBomb)
- `predict(game: dict) -> dict`: validates `game.get("league") == "wc"` — raises `ValueError("WC model only accepts WC game dicts (league='wc')")` otherwise. Returns input dict **plus** model fields merged in (does not create new dict — appends keys to existing game dict)
- `evaluate_bet(game: dict) -> dict | None`: returns game dict if `win_prob` has EV > min_edge vs market odds, else None

### SoccerModel Guard
- `wc_model.py` must never import from `soccer_model.py` (enforced by grep check in tests)
- `predict()` guards on `league == "wc"` — raises ValueError for non-WC games
- No routing path from soccer_scanner.py through SoccerModel for WC games

### Elo-Logistic Formula (Neutral Venue)
- Elo diff: `elo_diff = elo_home - elo_away` — **no +100 home-field boost** (all WC matches neutral venue)
- StatsBomb modifier (optional): `if both teams in wc_stats: xg_diff = home_avg_xG - away_avg_xG; elo_adj = elo_diff + xg_diff * 35.0` capped at `elo_adj = max(-200, min(200, elo_adj))`; else `elo_adj = elo_diff`
- 2-way win prob: `p_home_2way = 1 / (1 + 10 ** (-elo_adj / 400.0))`
- Draw rate constant: `_WC_DRAW_RATE: float = 0.25` (group stage historical WC draw frequency)

### 3-Outcome Group Stage Probabilities
- `p_draw = _WC_DRAW_RATE`
- `p_home = p_home_2way * (1 - p_draw)`
- `p_away = (1 - p_home_2way) * (1 - p_draw)`
- Sum = 1.0 guaranteed

### Knockout Stage Gate (MODEL-02)
- `KNOCKOUT_STAGES = {"LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "THIRD_PLACE", "FINAL"}`
- Detection: `stage = game.get("stage", "GROUP_STAGE"); knockout = stage in KNOCKOUT_STAGES`
- If knockout: `p_draw = 0.0; p_home = p_home_2way; p_away = 1 - p_home_2way`
- Output: `win_prob = p_home, draw_prob = 0.0, loss_prob = p_away` (Draw suppressed entirely)

### Output Fields Added to Game Dict (MODEL-01, MODEL-03, MODEL-04)
```
"win_prob":   float  — home team W probability (or Win-to-Advance in knockout)
"draw_prob":  float  — 0.0 in knockout rounds
"loss_prob":  float  — away team W probability
"elo_edge":   bool   — |win_prob - market_implied| > 0.05
"knockout":   bool   — True if stage in KNOCKOUT_STAGES
"model_name": str    — "wc_elo_logistic"
"elo_diff":   float  — raw elo_adj used (useful for debug/Phase 7)
```

### Market Divergence Flag (MODEL-04)
- Market implied: use `EVCalculator.american_to_decimal(home_odds)` → `1/decimal`
- Default home_odds=-110 → implied ≈ 0.524
- Edge threshold: `abs(win_prob - market_implied) > 0.05`
- `elo_edge = True` when model diverges by >5pp (marks picks in scanner output as `*ELO EDGE*`)
- Use existing `EVCalculator` from `alpha/engines/sports/ev_calculator.py`

### Claude's Discretion
- xG scale factor (35.0 Elo points per 1 xG difference) — validated against WC data ranges
- Exact StatsBomb fallback behaviour (log warning, continue with Elo-only)
- Whether to also store `"home_elo"` and `"away_elo"` in output dict (useful for debugging)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `alpha/engines/sports/soccer_model.py` — class shape, EVCalculator usage, `evaluate_bet()` pattern to mirror
- `alpha/engines/sports/ev_calculator.py` — `EVCalculator.american_to_decimal()`, `implied_prob()` already implemented; import directly
- `alpha/data/ingestion/wc_elo.py` — `load_wc_elo_ratings() -> dict[str, int]`, `get_elo_rating(team, ratings) -> int`
- `alpha/data/ingestion/wc_stats.py` — `get_wc_team_stats() -> dict[str, dict]`
- `alpha/config/settings.py` — no new settings needed; `football_api_key` already exists

### Established Patterns
- Model class constructor: loads data at init, stores as instance attributes
- Logger: `logger = logging.getLogger(__name__)`
- Defensive loading: try/except FileNotFoundError with logger.warning → empty fallback
- Test mock pattern: `monkeypatch.setattr("alpha.engines.sports.wc_model.load_wc_elo_ratings", ...)`

### Integration Points
- Phase 7 (wc_sgp_builder.py) reads: `win_prob`, `draw_prob`, `knockout`, `elo_edge` from predict() output
- Phase 7 (wc_scanner.py or soccer_scanner.py --league wc) calls `WCMatchModel().predict(game)` per fixture
- Downstream NEVER passes WC game dicts to `SoccerModel`

</code_context>

<specifics>
## Specific Ideas

- Elo formula derivation: Bradley-Terry model → `p = 1/(1+10^(-d/400))` where d = Elo difference; no home boost
- Draw model: simple multiplicative decomposition. `p_home + p_draw + p_away = 1.0` always holds.
- xG-to-Elo scale: `1 xG/game ≈ 35 Elo points` → a team with 1.5 xG/game vs 0.5 xG/game (1.0 xG diff) gets +35 Elo adjustment. Capped at ±200 to prevent extreme upsets being erased.
- EVCalculator is already imported in soccer_model.py with the same `min_edge=0.04` default
- StatsBomb team stats use `avg_xG` (xG for) and `defense_score` (xG against per game) for strength modifier
- `"elo_diff"` field in output is the adjusted Elo diff (post-StatsBomb modifier), not raw Elo diff

</specifics>

<deferred>
## Deferred Ideas

- WC player props and player-level StatsBomb stats — deferred to v1.2
- Recency-weighted Elo update during tournament (update Elo after each group game) — v1.2
- WC correct score / BTTS markets — too much vig, not planned
- Cross-calibration against Odds API WC h2h market — deferred until credits confirmed

</deferred>
