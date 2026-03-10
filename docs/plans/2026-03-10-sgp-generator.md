# SGP Generator Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-mode Same-Game Parlay generator that finds positive-EV bet combinations by modeling player props with opponent adjustments and applying an empirical correlation matrix to correctly price correlated legs.

**Architecture:** Five-layer pipeline — (1) props ingestion from The Odds API, (2) player prop prediction via nba_api rolling stats + opponent defensive adjustment, (3) empirical correlation matrix from historical game logs, (4) SGP builder that combines legs with correlation-adjusted probability and computes EV vs market, (5) CLI scanner that orchestrates all four modes (PROPS_ONLY, MONEYLINE_SGP, MIXED_SGP, CLASSIC_PARLAY).

**Tech Stack:** Python 3.13, nba_api, scipy.stats (normal distribution), numpy (Pearson correlation), requests (Odds API), existing EVCalculator + KellySizer from `alpha/engines/sports/`

---

## Chunk 1: Props Ingestion + Prop Model

### Task 1: PlayerPropsClient

**Files:**
- Create: `alpha/data/ingestion/player_props.py`
- Test: `tests/unit/test_player_props.py`

**What it does:** Fetches NBA player prop lines from The Odds API (same key as moneyline). Each prop has a player name, stat category (points/rebounds/assists/threes), line value, and over/under American odds. Returns a list of canonical dicts, one per player per market per game.

**The Odds API prop market keys:** `player_points`, `player_rebounds`, `player_assists`, `player_threes`
**Response shape per outcome:** `{"name": "LeBron James", "description": "Over", "price": -115, "point": 27.5}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_player_props.py
import pytest
from unittest.mock import patch, Mock
from alpha.data.ingestion.player_props import PlayerPropsClient


FAKE_RESPONSE = [
    {
        "id": "evt1",
        "home_team": "Los Angeles Lakers",
        "away_team": "Boston Celtics",
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {"name": "LeBron James", "description": "Over", "price": -115, "point": 27.5},
                            {"name": "LeBron James", "description": "Under", "price": -105, "point": 27.5},
                            {"name": "Jayson Tatum", "description": "Over", "price": -110, "point": 29.5},
                            {"name": "Jayson Tatum", "description": "Under", "price": -110, "point": 29.5},
                        ],
                    }
                ],
            }
        ],
    }
]


def test_parse_props_returns_canonical_dicts():
    client = PlayerPropsClient(api_key="fake")
    props = client._parse_props(FAKE_RESPONSE)
    assert len(props) == 2  # LeBron + Tatum (one entry per player per market)
    lebron = next(p for p in props if p["player"] == "LeBron James")
    assert lebron["market"] == "player_points"
    assert lebron["line"] == 27.5
    assert lebron["over_odds"] == -115
    assert lebron["under_odds"] == -105
    assert lebron["event_id"] == "evt1"
    assert lebron["home_team"] == "Los Angeles Lakers"


def test_no_api_key_returns_empty():
    client = PlayerPropsClient(api_key="")
    result = client.fetch_nba_props()
    assert result == []


def test_http_error_returns_empty():
    client = PlayerPropsClient(api_key="key")
    with patch("requests.get") as mock_get:
        mock_get.return_value.raise_for_status.side_effect = Exception("429")
        result = client.fetch_nba_props()
    assert result == []


def test_markets_filtered_to_supported():
    client = PlayerPropsClient(api_key="fake")
    response = [
        {
            "id": "evt1",
            "home_team": "Team A",
            "away_team": "Team B",
            "bookmakers": [
                {
                    "key": "bk",
                    "markets": [
                        {"key": "player_points", "outcomes": [
                            {"name": "Player A", "description": "Over", "price": -110, "point": 20.5},
                            {"name": "Player A", "description": "Under", "price": -110, "point": 20.5},
                        ]},
                        {"key": "player_rush_yards", "outcomes": []},  # football — should be ignored
                    ],
                }
            ],
        }
    ]
    props = client._parse_props(response)
    assert all(p["market"] in PlayerPropsClient.SUPPORTED_MARKETS for p in props)
```

- [ ] **Step 2: Run tests to confirm they fail**

```
VIRTUAL_ENV=./venv python -m pytest tests/unit/test_player_props.py -v
```
Expected: ImportError (module doesn't exist yet)

- [ ] **Step 3: Implement PlayerPropsClient**

```python
# alpha/data/ingestion/player_props.py
"""
PlayerPropsClient — fetches NBA player prop lines from The-Odds-API (v4).

Each returned dict represents one player's over/under for one stat market
in one game. Multiple bookmakers are deduplicated — best available over
odds and best available under odds are kept.

Canonical output schema:
    {
        "event_id":   str,
        "home_team":  str,
        "away_team":  str,
        "player":     str,   # e.g. "LeBron James"
        "market":     str,   # e.g. "player_points"
        "line":       float, # e.g. 27.5
        "over_odds":  int,   # American odds
        "under_odds": int,
        "bookmaker":  str,
    }
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"


class PlayerPropsClient:
    SUPPORTED_MARKETS = [
        "player_points",
        "player_rebounds",
        "player_assists",
        "player_threes",
    ]

    def __init__(self, api_key: str | None = None):
        self.api_key: str = api_key or os.environ.get("ODDS_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch_nba_props(
        self,
        markets: list[str] | None = None,
        event_ids: list[str] | None = None,
    ) -> list[dict]:
        """
        Fetch player prop lines for today's NBA games.

        Args:
            markets: Subset of SUPPORTED_MARKETS to fetch. Defaults to all.
            event_ids: Optional list of Odds API event IDs to filter to.

        Returns [] on any failure.
        """
        if not self.is_configured():
            logger.warning("ODDS_API_KEY not set — player props fetch skipped")
            return []

        markets = markets or self.SUPPORTED_MARKETS

        try:
            resp = requests.get(
                _BASE_URL,
                params={
                    "apiKey": self.api_key,
                    "regions": "us",
                    "markets": ",".join(markets),
                    "oddsFormat": "american",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data: list[dict[str, Any]] = resp.json()

            if event_ids:
                data = [e for e in data if e.get("id") in event_ids]

            return self._parse_props(data)
        except Exception as exc:
            logger.warning("PlayerPropsClient error: %s — returning []", exc)
            return []

    def _parse_props(self, data: list[dict]) -> list[dict]:
        """Parse raw Odds API response into canonical prop dicts."""
        # player -> market -> {line, best_over, best_under, bookmaker}
        results: list[dict] = []

        for event in data:
            event_id = event.get("id", "")
            home_team = event.get("home_team", "")
            away_team = event.get("away_team", "")

            # Collect best odds across bookmakers per player per market
            # key: (player, market) -> {line, over_odds, under_odds, bookmaker}
            best: dict[tuple, dict] = {}

            for bookmaker in event.get("bookmakers", []):
                bk_key = bookmaker.get("key", "")
                for market in bookmaker.get("markets", []):
                    mkt = market.get("key", "")
                    if mkt not in self.SUPPORTED_MARKETS:
                        continue

                    # Group outcomes by player
                    player_data: dict[str, dict] = {}
                    for outcome in market.get("outcomes", []):
                        player = outcome.get("name", "")
                        direction = outcome.get("description", "")
                        price = outcome.get("price", -110)
                        line = outcome.get("point", 0.0)

                        if player not in player_data:
                            player_data[player] = {"line": line, "over": None, "under": None}

                        if direction == "Over":
                            player_data[player]["over"] = int(price)
                        elif direction == "Under":
                            player_data[player]["under"] = int(price)

                    for player, pd in player_data.items():
                        if pd["over"] is None or pd["under"] is None:
                            continue
                        key = (player, mkt)
                        if key not in best:
                            best[key] = {
                                "line": pd["line"],
                                "over_odds": pd["over"],
                                "under_odds": pd["under"],
                                "bookmaker": bk_key,
                            }
                        else:
                            # Prefer the over line with better (higher) odds
                            if pd["over"] > best[key]["over_odds"]:
                                best[key] = {
                                    "line": pd["line"],
                                    "over_odds": pd["over"],
                                    "under_odds": pd["under"],
                                    "bookmaker": bk_key,
                                }

            for (player, mkt), info in best.items():
                results.append({
                    "event_id": event_id,
                    "home_team": home_team,
                    "away_team": away_team,
                    "player": player,
                    "market": mkt,
                    "line": info["line"],
                    "over_odds": info["over_odds"],
                    "under_odds": info["under_odds"],
                    "bookmaker": info["bookmaker"],
                })

        return results
```

- [ ] **Step 4: Run tests to confirm they pass**

```
VIRTUAL_ENV=./venv python -m pytest tests/unit/test_player_props.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add alpha/data/ingestion/player_props.py tests/unit/test_player_props.py
git commit -m "feat: add PlayerPropsClient (The Odds API player prop ingestion)"
```

---

### Task 2: PropModel (player stat prediction engine)

**Files:**
- Create: `alpha/engines/sports/prop_model.py`
- Test: `tests/unit/test_prop_model.py`

**What it does:** Given a player and a prop line (e.g., "LeBron James over 27.5 pts"), predicts the probability of hitting. Uses nba_api for the last 20 game logs, computes a weighted rolling average (5/10/20 game windows), adjusts for opponent defensive rating, fits a normal distribution, and returns P(over line).

**Key formula:**
```
proj_stat = 0.5 * avg_5g + 0.3 * avg_10g + 0.2 * avg_20g
opp_adj   = proj_stat * (league_avg_def_rtg / opp_def_rtg)   # if opp_def_rtg known
std_stat  = stddev of last 20 games
p_over    = 1 - norm.cdf(line, loc=opp_adj, scale=std_stat)
```

**nba_api calls used:**
- `nba_api.stats.endpoints.playergamelogs.PlayerGameLogs` — recent game log for a player
- `nba_api.stats.endpoints.leaguedashteamstats.LeagueDashTeamStats` — team defensive ratings

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_prop_model.py
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from alpha.engines.sports.prop_model import PropModel


def _fake_gamelogs(pts_values: list[float]) -> MagicMock:
    """Return a mock that mimics nba_api PlayerGameLogs response."""
    df = pd.DataFrame({"PTS": pts_values, "REB": [5.0] * len(pts_values), "AST": [6.0] * len(pts_values), "FG3M": [2.0] * len(pts_values)})
    mock = MagicMock()
    mock.get_data_frames.return_value = [df]
    return mock


def test_normal_distribution_p_over_above_50_when_proj_exceeds_line():
    model = PropModel()
    # If avg is 30 and line is 25, P(over) should be well above 0.5
    pts = [30.0] * 20
    with patch.object(model, "_get_game_logs", return_value=pd.DataFrame({
        "PTS": pts, "REB": [0]*20, "AST": [0]*20, "FG3M": [0]*20
    })):
        with patch.object(model, "_get_opp_def_rating", return_value=None):
            result = model.predict_prop("LeBron James", "player_points", 25.0, "")
    assert result["model_prob"] > 0.7


def test_normal_distribution_p_over_below_50_when_line_exceeds_proj():
    model = PropModel()
    pts = [20.0] * 20
    with patch.object(model, "_get_game_logs", return_value=pd.DataFrame({
        "PTS": pts, "REB": [0]*20, "AST": [0]*20, "FG3M": [0]*20
    })):
        with patch.object(model, "_get_opp_def_rating", return_value=None):
            result = model.predict_prop("LeBron James", "player_points", 25.0, "")
    assert result["model_prob"] < 0.3


def test_returns_none_on_empty_gamelogs():
    model = PropModel()
    with patch.object(model, "_get_game_logs", return_value=pd.DataFrame()):
        result = model.predict_prop("Unknown Player", "player_points", 20.0, "")
    assert result is None


def test_weighted_avg_weights_recent_games_more():
    model = PropModel()
    # Last 5 games: 35 pts, games 6-10: 20 pts, games 11-20: 10 pts
    pts = [35.0] * 5 + [20.0] * 5 + [10.0] * 10
    with patch.object(model, "_get_game_logs", return_value=pd.DataFrame({
        "PTS": pts, "REB": [0]*20, "AST": [0]*20, "FG3M": [0]*20
    })):
        with patch.object(model, "_get_opp_def_rating", return_value=None):
            result = model.predict_prop("Player A", "player_points", 20.0, "")
    # Weighted avg should be higher than simple avg (35 recent > 10 old)
    simple_avg = np.mean(pts)  # ~21.25
    assert result["proj_stat"] > simple_avg


def test_market_col_mapping():
    model = PropModel()
    assert model._market_col("player_points") == "PTS"
    assert model._market_col("player_rebounds") == "REB"
    assert model._market_col("player_assists") == "AST"
    assert model._market_col("player_threes") == "FG3M"
```

- [ ] **Step 2: Run tests to confirm they fail**

```
VIRTUAL_ENV=./venv python -m pytest tests/unit/test_prop_model.py -v
```
Expected: ImportError

- [ ] **Step 3: Implement PropModel**

```python
# alpha/engines/sports/prop_model.py
"""
PropModel — predicts NBA player prop probabilities.

For a given player + stat line, estimates P(player hits over the line)
using a normal distribution fit on recent game log data.

Workflow:
  1. Fetch last N game logs from nba_api
  2. Compute weighted rolling average (5/10/20 game windows)
  3. Optionally adjust for opponent defensive rating
  4. Fit normal(mu=proj_stat, sigma=std_of_recent) distribution
  5. Return P(over line) and P(under line)
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

logger = logging.getLogger(__name__)

# Weight for rolling windows: 50% last 5 games, 30% last 10, 20% last 20
_WINDOW_WEIGHTS = [(5, 0.5), (10, 0.3), (20, 0.2)]
_MIN_GAMES = 5  # Need at least this many games to make a prediction
_API_DELAY = 0.6  # seconds between nba_api calls (rate limit)

# Map Odds API market keys -> nba_api game log column names
_MARKET_COL_MAP = {
    "player_points": "PTS",
    "player_rebounds": "REB",
    "player_assists": "AST",
    "player_threes": "FG3M",
    "player_blocks": "BLK",
    "player_steals": "STL",
}

# League average defensive rating (approximate 2024-25 season baseline)
_LEAGUE_AVG_DEF_RTG = 113.5


class PropModel:
    def __init__(self):
        self._player_id_cache: dict[str, int] = {}
        self._def_rating_cache: dict[str, float] | None = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def predict_prop(
        self,
        player_name: str,
        market: str,
        line: float,
        opponent_team: str,
    ) -> dict | None:
        """
        Predict P(player exceeds line) for a given stat market.

        Returns:
            {
                "player": str,
                "market": str,
                "line": float,
                "proj_stat": float,   # model's projected stat value
                "std_stat": float,    # standard deviation (uncertainty)
                "model_prob": float,  # P(over line)
                "source": str,        # "nba_api" or "unavailable"
            }
        or None if prediction is not possible.
        """
        col = self._market_col(market)
        if col is None:
            return None

        logs = self._get_game_logs(player_name, n_games=20)
        if logs is None or len(logs) < _MIN_GAMES:
            logger.debug("Insufficient game logs for %s (%s games)", player_name, len(logs) if logs is not None else 0)
            return None

        values = logs[col].dropna().values.astype(float)
        if len(values) < _MIN_GAMES:
            return None

        proj = self._weighted_average(values)
        std = float(np.std(values)) if len(values) > 1 else proj * 0.25
        std = max(std, 1.0)  # floor: avoid division by near-zero

        # Opponent defensive rating adjustment
        opp_def_rtg = self._get_opp_def_rating(opponent_team)
        if opp_def_rtg is not None and col == "PTS":
            # Better defense (lower def_rtg) → reduce projection
            proj = proj * (_LEAGUE_AVG_DEF_RTG / opp_def_rtg)

        p_over = float(1 - norm.cdf(line, loc=proj, scale=std))
        p_over = max(0.01, min(0.99, p_over))

        return {
            "player": player_name,
            "market": market,
            "line": line,
            "proj_stat": round(proj, 2),
            "std_stat": round(std, 2),
            "model_prob": round(p_over, 4),
            "source": "nba_api",
        }

    def predict_batch(
        self, props: list[dict], game: dict
    ) -> list[dict]:
        """
        Run predict_prop on a list of prop dicts (from PlayerPropsClient).
        Attaches model_prob and proj_stat to each prop dict.
        Returns only props where prediction succeeded.
        """
        results = []
        for prop in props:
            opponent = (
                game.get("away_team", "")
                if prop.get("home_team") == game.get("home_team")
                else game.get("home_team", "")
            )
            prediction = self.predict_prop(
                player_name=prop["player"],
                market=prop["market"],
                line=prop["line"],
                opponent_team=opponent,
            )
            if prediction is not None:
                results.append({**prop, **prediction})
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _market_col(self, market: str) -> str | None:
        return _MARKET_COL_MAP.get(market)

    def _weighted_average(self, values: np.ndarray) -> float:
        """
        Weighted average across 5/10/20-game windows.
        Shorter windows get higher weight to emphasize recent form.
        """
        total_weight = 0.0
        weighted_sum = 0.0
        for window, weight in _WINDOW_WEIGHTS:
            window_vals = values[:window] if len(values) >= window else values
            if len(window_vals) > 0:
                weighted_sum += weight * float(np.mean(window_vals))
                total_weight += weight
        return weighted_sum / total_weight if total_weight > 0 else float(np.mean(values))

    def _get_game_logs(self, player_name: str, n_games: int = 20) -> pd.DataFrame | None:
        """Fetch recent game logs for a player from nba_api."""
        try:
            from nba_api.stats.static import players as nba_players
            from nba_api.stats.endpoints import playergamelogs

            player_id = self._resolve_player_id(player_name)
            if player_id is None:
                return None

            time.sleep(_API_DELAY)
            logs = playergamelogs.PlayerGameLogs(
                player_id_nullable=str(player_id),
                last_n_games_nullable=str(n_games),
                season_nullable="2024-25",
            )
            df = logs.get_data_frames()[0]
            return df if not df.empty else None
        except Exception as exc:
            logger.debug("Game log fetch failed for %s: %s", player_name, exc)
            return None

    def _resolve_player_id(self, player_name: str) -> int | None:
        if player_name in self._player_id_cache:
            return self._player_id_cache[player_name]
        try:
            from nba_api.stats.static import players as nba_players
            matches = nba_players.find_players_by_full_name(player_name)
            if not matches:
                # Try first/last name substring match
                name_parts = player_name.lower().split()
                all_players = nba_players.get_active_players()
                for p in all_players:
                    full = p["full_name"].lower()
                    if all(part in full for part in name_parts):
                        matches = [p]
                        break
            if matches:
                pid = matches[0]["id"]
                self._player_id_cache[player_name] = pid
                return pid
        except Exception as exc:
            logger.debug("Player ID resolution failed for %s: %s", player_name, exc)
        return None

    def _get_opp_def_rating(self, team_name: str) -> float | None:
        """Fetch opponent team defensive rating from nba_api (cached per run)."""
        if not team_name:
            return None
        if self._def_rating_cache is None:
            self._def_rating_cache = self._load_def_ratings()
        return self._def_rating_cache.get(team_name)

    def _load_def_ratings(self) -> dict[str, float]:
        """Load all teams' defensive ratings from nba_api."""
        try:
            from nba_api.stats.endpoints import leaguedashteamstats
            time.sleep(_API_DELAY)
            stats = leaguedashteamstats.LeagueDashTeamStats(
                season="2024-25",
                measure_type_simple_game_nullable="Defense",
            )
            df = stats.get_data_frames()[0]
            return dict(zip(df["TEAM_NAME"], df["DEF_RATING"].astype(float)))
        except Exception as exc:
            logger.debug("Defensive ratings load failed: %s", exc)
            return {}
```

- [ ] **Step 4: Run tests**

```
VIRTUAL_ENV=./venv python -m pytest tests/unit/test_prop_model.py -v
```
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add alpha/engines/sports/prop_model.py tests/unit/test_prop_model.py
git commit -m "feat: add PropModel (nba_api rolling stats + normal distribution prop prediction)"
```

---

## Chunk 2: Correlation Engine + SGP Builder

### Task 3: CorrelationEngine (empirical correlation matrix)

**Files:**
- Create: `alpha/engines/sports/correlation.py`
- Test: `tests/unit/test_correlation.py`

**What it does:** Builds an empirical correlation matrix from historical NBA game logs. For each pair of (player_A_stat, player_B_stat), computes Pearson r between their binary "hit vs season avg" vectors across shared games. Also computes player_stat vs team_win correlation. Caches to disk with 24-hour TTL.

**Key insight:** If Player A and Player B both play many games together, we can compute: `hit_A[game] = 1 if A_stat > A_season_avg else 0`. Then `r = pearsonr(hit_A, hit_B)`. Positive r = they tend to hit/miss together. Negative r = anti-correlated (edge opportunity).

**Correlation types classified:**
- `POSITIVE` (r > 0.25): tend to co-occur — book prices these correctly, avoid or discount
- `NEUTRAL` (-0.25 ≤ r ≤ 0.25): near-independent — book's naive pricing is fair
- `NEGATIVE` (r < -0.25): anti-correlated — book underprices, this is your edge

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_correlation.py
import pytest
import numpy as np
from alpha.engines.sports.correlation import CorrelationEngine, CorrelationType


def test_perfect_positive_correlation():
    engine = CorrelationEngine()
    hits_a = np.array([1, 0, 1, 1, 0, 1, 0, 0, 1, 1], dtype=float)
    hits_b = hits_a.copy()  # identical → perfect correlation
    r = engine._pearson(hits_a, hits_b)
    assert abs(r - 1.0) < 0.01


def test_perfect_negative_correlation():
    engine = CorrelationEngine()
    hits_a = np.array([1, 0, 1, 1, 0, 1, 0, 0, 1, 1], dtype=float)
    hits_b = 1 - hits_a  # opposite → perfect anti-correlation
    r = engine._pearson(hits_a, hits_b)
    assert abs(r + 1.0) < 0.01


def test_zero_correlation_random():
    engine = CorrelationEngine()
    rng = np.random.default_rng(42)
    hits_a = rng.integers(0, 2, 50).astype(float)
    hits_b = rng.integers(0, 2, 50).astype(float)
    r = engine._pearson(hits_a, hits_b)
    assert -0.5 < r < 0.5  # should be near zero (loose check for random data)


def test_classify_correlation():
    engine = CorrelationEngine()
    assert engine._classify(0.4) == CorrelationType.POSITIVE
    assert engine._classify(0.1) == CorrelationType.NEUTRAL
    assert engine._classify(-0.3) == CorrelationType.NEGATIVE


def test_adjust_joint_prob_positive_correlation_reduces():
    engine = CorrelationEngine()
    # If legs are positively correlated, joint prob is HIGHER than independent product
    # So for a bettor: positive correlation means book may underprice, but it's also riskier
    p_a, p_b = 0.6, 0.55
    r = 0.4  # positive correlation
    adjusted = engine.adjust_joint_prob(p_a, p_b, r)
    independent = p_a * p_b
    # Positive correlation: P(A∩B) > P(A)*P(B)
    assert adjusted > independent


def test_adjust_joint_prob_negative_correlation_increases_naive_underprice():
    engine = CorrelationEngine()
    p_a, p_b = 0.6, 0.55
    r = -0.4  # negative correlation
    adjusted = engine.adjust_joint_prob(p_a, p_b, r)
    independent = p_a * p_b
    # Negative correlation: P(A∩B) < P(A)*P(B), so book overestimates the joint
    assert adjusted < independent


def test_get_correlation_returns_zero_for_unknown_pair():
    engine = CorrelationEngine()
    r = engine.get_correlation("Player X", "player_points", "Player Y", "player_assists")
    assert r == 0.0
```

- [ ] **Step 2: Run to confirm failures**

```
VIRTUAL_ENV=./venv python -m pytest tests/unit/test_correlation.py -v
```

- [ ] **Step 3: Implement CorrelationEngine**

```python
# alpha/engines/sports/correlation.py
"""
CorrelationEngine — empirical correlation matrix for NBA prop outcomes.

Builds Pearson correlation between pairs of player stat outcomes
(did player hit over their average?) using historical nba_api game logs.

Results are cached to disk (.corr_cache.pkl) with a 24-hour TTL.

Usage:
    engine = CorrelationEngine()
    engine.build(player_names=["LeBron James", "Anthony Davis"], season="2024-25")
    r = engine.get_correlation("LeBron James", "player_points", "Anthony Davis", "player_rebounds")
    p_joint = engine.adjust_joint_prob(0.6, 0.55, r)
"""
from __future__ import annotations

import logging
import pickle
import time
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_FILE = Path("data/.corr_cache.pkl")
_CACHE_TTL_HOURS = 24
_API_DELAY = 0.6

# Map market key → game log column
_MARKET_COL = {
    "player_points": "PTS",
    "player_rebounds": "REB",
    "player_assists": "AST",
    "player_threes": "FG3M",
}


class CorrelationType(Enum):
    POSITIVE = "positive"   # r > 0.25: co-occur, book may price correctly
    NEUTRAL = "neutral"     # -0.25 ≤ r ≤ 0.25: near-independent
    NEGATIVE = "negative"   # r < -0.25: anti-correlated, potential edge


class CorrelationEngine:
    def __init__(self):
        # (player_a, market_a, player_b, market_b) -> float
        self._matrix: dict[tuple, float] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def build(
        self,
        player_names: list[str],
        season: str = "2024-25",
        force_rebuild: bool = False,
    ) -> None:
        """
        Compute correlation matrix for a set of players.
        Loads from cache if fresh; rebuilds from nba_api otherwise.
        """
        if not force_rebuild and self._load_cache():
            logger.info("Correlation matrix loaded from cache")
            return

        logger.info("Building correlation matrix for %d players...", len(player_names))
        game_logs = self._fetch_all_logs(player_names, season)
        self._compute_matrix(game_logs)
        self._save_cache()
        self._loaded = True

    def get_correlation(
        self,
        player_a: str,
        market_a: str,
        player_b: str,
        market_b: str,
    ) -> float:
        """
        Return Pearson r between two player prop outcomes.
        Returns 0.0 if pair not in matrix (treat as independent).
        """
        key = (player_a, market_a, player_b, market_b)
        alt_key = (player_b, market_b, player_a, market_a)
        return self._matrix.get(key, self._matrix.get(alt_key, 0.0))

    def adjust_joint_prob(
        self, p_a: float, p_b: float, r: float
    ) -> float:
        """
        Bivariate normal copula approximation for joint probability.

        P(A ∩ B) ≈ P(A) * P(B) + r * sqrt(P(A)*(1-P(A)) * P(B)*(1-P(B)))

        This is a first-order Taylor expansion around the independent case.
        Positive r: actual joint prob is HIGHER than naive product.
        Negative r: actual joint prob is LOWER than naive product.
        """
        correction = r * np.sqrt(p_a * (1 - p_a) * p_b * (1 - p_b))
        joint = p_a * p_b + correction
        return float(np.clip(joint, 0.001, 0.999))

    def adjust_multi_leg_prob(
        self, legs: list[tuple[float, str, str]]
    ) -> float:
        """
        Compute correlation-adjusted joint probability for N legs.

        Args:
            legs: list of (model_prob, player_name, market)

        Algorithm:
            Start with leg 0. For each subsequent leg, apply pairwise
            correlation correction against all previous legs (averaged).
        """
        if not legs:
            return 0.0
        if len(legs) == 1:
            return legs[0][0]

        # Start with naive product
        probs = [leg[0] for leg in legs]
        p_joint = probs[0]

        for i in range(1, len(legs)):
            p_i = probs[i]
            # Average correlation between leg i and all previous legs
            corrs = []
            for j in range(i):
                r = self.get_correlation(
                    legs[j][1], legs[j][2], legs[i][1], legs[i][2]
                )
                corrs.append(r)
            avg_r = float(np.mean(corrs)) if corrs else 0.0
            p_joint = self.adjust_joint_prob(p_joint, p_i, avg_r)

        return p_joint

    def classify(self, r: float) -> CorrelationType:
        return self._classify(r)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _classify(self, r: float) -> CorrelationType:
        if r > 0.25:
            return CorrelationType.POSITIVE
        if r < -0.25:
            return CorrelationType.NEGATIVE
        return CorrelationType.NEUTRAL

    def _pearson(self, a: np.ndarray, b: np.ndarray) -> float:
        if len(a) < 5 or np.std(a) == 0 or np.std(b) == 0:
            return 0.0
        return float(np.corrcoef(a, b)[0, 1])

    def _fetch_all_logs(
        self, player_names: list[str], season: str
    ) -> dict[str, pd.DataFrame]:
        """Fetch game logs for all players. Returns {player_name: df}."""
        from alpha.engines.sports.prop_model import PropModel
        model = PropModel()
        logs = {}
        for name in player_names:
            df = model._get_game_logs(name, n_games=50)
            if df is not None and not df.empty:
                logs[name] = df
            time.sleep(_API_DELAY)
        return logs

    def _compute_matrix(self, logs: dict[str, pd.DataFrame]) -> None:
        """Compute pairwise Pearson r for all player/market combinations."""
        player_names = list(logs.keys())
        markets = list(_MARKET_COL.keys())

        for i, player_a in enumerate(player_names):
            for player_b in player_names[i + 1:]:
                df_a = logs[player_a]
                df_b = logs[player_b]

                for market_a in markets:
                    col_a = _MARKET_COL[market_a]
                    if col_a not in df_a.columns:
                        continue
                    for market_b in markets:
                        col_b = _MARKET_COL[market_b]
                        if col_b not in df_b.columns:
                            continue

                        # Build binary hit vectors on shared game dates
                        hits_a, hits_b = self._aligned_hits(
                            df_a, col_a, df_b, col_b
                        )
                        if len(hits_a) >= 10:
                            r = self._pearson(hits_a, hits_b)
                            key = (player_a, market_a, player_b, market_b)
                            self._matrix[key] = r

        logger.info("Correlation matrix: %d pairs computed", len(self._matrix))

    def _aligned_hits(
        self,
        df_a: pd.DataFrame,
        col_a: str,
        df_b: pd.DataFrame,
        col_b: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Build binary 'hit' vectors (did player exceed their mean?) for
        games where both players played. Aligns on game date.
        """
        date_col = "GAME_DATE" if "GAME_DATE" in df_a.columns else None
        if date_col is None:
            # No date alignment — just use min-length overlap
            n = min(len(df_a), len(df_b))
            vals_a = df_a[col_a].values[:n].astype(float)
            vals_b = df_b[col_b].values[:n].astype(float)
        else:
            merged = df_a[[date_col, col_a]].merge(
                df_b[[date_col, col_b]], on=date_col, suffixes=("_a", "_b")
            )
            if len(merged) < 5:
                return np.array([]), np.array([])
            vals_a = merged[col_a].values.astype(float)
            vals_b = merged[col_b].values.astype(float)

        mean_a = np.mean(vals_a)
        mean_b = np.mean(vals_b)
        hits_a = (vals_a > mean_a).astype(float)
        hits_b = (vals_b > mean_b).astype(float)
        return hits_a, hits_b

    def _load_cache(self) -> bool:
        if not _CACHE_FILE.exists():
            return False
        try:
            with open(_CACHE_FILE, "rb") as f:
                cached = pickle.load(f)
            age = datetime.now() - cached["timestamp"]
            if age > timedelta(hours=_CACHE_TTL_HOURS):
                return False
            self._matrix = cached["matrix"]
            self._loaded = True
            return True
        except Exception:
            return False

    def _save_cache(self) -> None:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_CACHE_FILE, "wb") as f:
            pickle.dump({"matrix": self._matrix, "timestamp": datetime.now()}, f)
```

- [ ] **Step 4: Run tests**

```
VIRTUAL_ENV=./venv python -m pytest tests/unit/test_correlation.py -v
```
Expected: 7 PASSED

- [ ] **Step 5: Commit**

```bash
git add alpha/engines/sports/correlation.py tests/unit/test_correlation.py
git commit -m "feat: add CorrelationEngine (empirical Pearson correlation matrix for prop outcomes)"
```

---

### Task 4: SGP Builder (multi-mode parlay engine)

**Files:**
- Create: `alpha/engines/sports/sgp_builder.py`
- Test: `tests/unit/test_sgp_builder.py`

**What it does:** Takes a list of prop predictions (from PropModel) + optional ML bet, generates all valid SGP combinations for each mode, applies correlation-adjusted joint probability via CorrelationEngine, computes EV vs naive market probability (product of individual implied probs), ranks by EV, returns top N.

**Four modes:**
- `PROPS_ONLY`: 2–4 player prop legs, same game
- `MONEYLINE_SGP`: ML leg + 1–3 player prop legs, same game. Flags if ML+player both from same team (high positive correlation — penalizes EV).
- `MIXED_SGP`: any combination of ML + props, same game, 2–5 legs
- `CLASSIC_PARLAY`: ML bets from 2–4 different games (independent legs — no correlation adjustment needed)

**EV formula for a parlay:**
```
combined_model_prob  = correlation_adjusted joint probability
combined_market_prob = product of individual market implied probs (book's naive assumption)
combined_decimal_odds = product of individual decimal odds (approximate book parlay price)
ev = combined_model_prob * (combined_decimal_odds - 1) - (1 - combined_model_prob)
edge = combined_model_prob - combined_market_prob
```

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_sgp_builder.py
import pytest
from unittest.mock import MagicMock
from alpha.engines.sports.sgp_builder import SGPBuilder, SGPMode, PropLeg, ParlayCombination


def _make_leg(player="Player A", market="player_points", line=20.0,
              model_prob=0.60, over_odds=-115, market="player_points"):
    return PropLeg(
        player=player,
        market=market,
        line=line,
        model_prob=model_prob,
        over_odds=over_odds,
        event_id="evt1",
        home_team="Lakers",
        away_team="Celtics",
    )


def test_props_only_requires_at_least_2_legs():
    corr = MagicMock()
    corr.adjust_multi_leg_prob.return_value = 0.35
    builder = SGPBuilder(correlation_engine=corr)
    legs = [_make_leg(player="A")]
    result = builder.build(legs, mode=SGPMode.PROPS_ONLY)
    assert result == []  # Need ≥2 legs for a parlay


def test_props_only_combines_2_legs():
    corr = MagicMock()
    corr.adjust_multi_leg_prob.return_value = 0.38
    builder = SGPBuilder(correlation_engine=corr)
    legs = [
        _make_leg(player="A", model_prob=0.62, over_odds=-115),
        _make_leg(player="B", model_prob=0.58, over_odds=-110),
    ]
    combos = builder.build(legs, mode=SGPMode.PROPS_ONLY)
    assert len(combos) >= 1
    combo = combos[0]
    assert combo.mode == SGPMode.PROPS_ONLY
    assert len(combo.legs) == 2
    assert combo.combined_model_prob == pytest.approx(0.38)


def test_ev_is_positive_when_model_beats_market():
    corr = MagicMock()
    corr.adjust_multi_leg_prob.return_value = 0.50  # model says 50%
    builder = SGPBuilder(correlation_engine=corr)
    # Two legs at -110 each → combined decimal = 1.909 * 1.909 ≈ 3.64
    # market_implied = (1/1.909)^2 ≈ 0.275
    # model says 0.50 >> 0.275 → big EV
    legs = [
        _make_leg(player="A", model_prob=0.65, over_odds=-110),
        _make_leg(player="B", model_prob=0.65, over_odds=-110),
    ]
    combos = builder.build(legs, mode=SGPMode.PROPS_ONLY)
    assert combos[0].ev > 0


def test_classic_parlay_uses_independent_games():
    corr = MagicMock()
    builder = SGPBuilder(correlation_engine=corr)
    ml_bets = [
        {"team": "Lakers", "model_prob": 0.60, "decimal_odds": 1.85, "event_id": "g1"},
        {"team": "Celtics", "model_prob": 0.65, "decimal_odds": 1.70, "event_id": "g2"},
    ]
    combos = builder.build_classic_parlay(ml_bets)
    assert len(combos) >= 1
    combo = combos[0]
    # No correlation adjustment for classic parlay (independent games)
    expected_prob = 0.60 * 0.65
    assert combo.combined_model_prob == pytest.approx(expected_prob, abs=0.01)


def test_results_sorted_by_ev_descending():
    corr = MagicMock()
    corr.adjust_multi_leg_prob.side_effect = [0.45, 0.30, 0.20]
    builder = SGPBuilder(correlation_engine=corr)
    legs = [
        _make_leg(player="A", model_prob=0.62, over_odds=-110),
        _make_leg(player="B", model_prob=0.60, over_odds=-115),
        _make_leg(player="C", model_prob=0.55, over_odds=-110),
    ]
    combos = builder.build(legs, mode=SGPMode.PROPS_ONLY, max_legs=3)
    evs = [c.ev for c in combos]
    assert evs == sorted(evs, reverse=True)
```

- [ ] **Step 2: Run to confirm failures**

```
VIRTUAL_ENV=./venv python -m pytest tests/unit/test_sgp_builder.py -v
```

- [ ] **Step 3: Implement SGPBuilder**

```python
# alpha/engines/sports/sgp_builder.py
"""
SGPBuilder — constructs optimal same-game parlays and classic parlays.

Four modes:
  PROPS_ONLY    — 2-4 player props from same game
  MONEYLINE_SGP — ML + 1-3 player props from same game
  MIXED_SGP     — any combination of ML + props, same game
  CLASSIC_PARLAY — ML bets from different games (truly independent legs)

Core algorithm:
  1. Enumerate all valid leg combinations for the chosen mode
  2. Compute correlation-adjusted joint probability via CorrelationEngine
  3. Compute naive market joint probability (product of implied probs)
  4. Edge = model_joint - market_joint
  5. EV = model_joint * (combined_dec_odds - 1) - (1 - model_joint)
  6. Rank by EV, return top N with Kelly stake
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from alpha.engines.sports.correlation import CorrelationEngine
from alpha.engines.sports.ev_calculator import EVCalculator
from alpha.engines.sports.kelly import KellySizer

logger = logging.getLogger(__name__)


class SGPMode(Enum):
    PROPS_ONLY = "props"
    MONEYLINE_SGP = "ml_sgp"
    MIXED_SGP = "mixed"
    CLASSIC_PARLAY = "parlay"


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
    direction: str = "over"  # "over" or "under"


@dataclass
class ParlayCombination:
    legs: list[PropLeg | dict]
    mode: SGPMode
    combined_model_prob: float
    combined_market_prob: float
    combined_decimal_odds: float
    ev: float
    edge: float
    correlation_note: str = ""
    stake: float = 0.0


class SGPBuilder:
    def __init__(
        self,
        correlation_engine: CorrelationEngine,
        min_edge: float = 0.05,
        kelly_fraction: float = 0.15,  # lower Kelly for parlays (more variance)
        bankroll: float = 10_000.0,
    ):
        self.corr = correlation_engine
        self.ev_calc = EVCalculator(min_edge=min_edge)
        self.kelly = KellySizer(kelly_fraction=kelly_fraction, max_stake_pct=0.03)
        self.bankroll = bankroll
        self.min_edge = min_edge

    # ------------------------------------------------------------------
    # Public: build SGP combinations
    # ------------------------------------------------------------------

    def build(
        self,
        prop_legs: list[PropLeg],
        mode: SGPMode = SGPMode.PROPS_ONLY,
        ml_leg: dict | None = None,
        min_legs: int = 2,
        max_legs: int = 4,
        top_n: int = 5,
    ) -> list[ParlayCombination]:
        """
        Generate and rank parlay combinations for a single game.

        Args:
            prop_legs: Player prop predictions from PropModel.
            mode: Which SGP mode to use.
            ml_leg: Optional moneyline bet dict ({team, model_prob, decimal_odds}).
            min_legs: Minimum legs in a combination.
            max_legs: Maximum legs in a combination.
            top_n: How many top combinations to return.

        Returns:
            List of ParlayCombination sorted by EV descending.
        """
        if len(prop_legs) < min_legs:
            return []

        combos: list[ParlayCombination] = []

        if mode == SGPMode.PROPS_ONLY:
            combos = self._build_props_only(prop_legs, min_legs, max_legs)

        elif mode == SGPMode.MONEYLINE_SGP:
            if ml_leg is None:
                logger.warning("MONEYLINE_SGP mode requires ml_leg — falling back to PROPS_ONLY")
                combos = self._build_props_only(prop_legs, min_legs, max_legs)
            else:
                combos = self._build_moneyline_sgp(prop_legs, ml_leg, max_legs)

        elif mode == SGPMode.MIXED_SGP:
            combos = self._build_mixed_sgp(prop_legs, ml_leg, min_legs, max_legs)

        # Sort by EV, filter to positive edge only
        combos = [c for c in combos if c.edge >= self.min_edge]
        combos.sort(key=lambda c: c.ev, reverse=True)
        combos = combos[:top_n]

        # Add Kelly stake to each
        for combo in combos:
            combo.stake = self.kelly.bet_size(
                win_prob=combo.combined_model_prob,
                decimal_odds=combo.combined_decimal_odds,
                bankroll=self.bankroll,
            )

        return combos

    def build_classic_parlay(
        self,
        ml_bets: list[dict],
        min_legs: int = 2,
        max_legs: int = 4,
        top_n: int = 3,
    ) -> list[ParlayCombination]:
        """
        Build classic multi-game parlays from ML bets on independent games.

        Args:
            ml_bets: list of {team, model_prob, decimal_odds, event_id}
        """
        if len(ml_bets) < min_legs:
            return []

        combos: list[ParlayCombination] = []

        for n_legs in range(min_legs, min(max_legs, len(ml_bets)) + 1):
            for combo_legs in itertools.combinations(ml_bets, n_legs):
                # Ensure all legs are from different games
                event_ids = [leg["event_id"] for leg in combo_legs]
                if len(set(event_ids)) < n_legs:
                    continue  # same game appears twice

                # Classic parlay: independent legs → simple multiplication
                combined_prob = 1.0
                combined_dec = 1.0
                combined_market = 1.0

                for leg in combo_legs:
                    combined_prob *= leg["model_prob"]
                    combined_dec *= leg["decimal_odds"]
                    combined_market *= (1.0 / leg["decimal_odds"])

                ev = self.ev_calc.expected_value(combined_prob, combined_dec)
                edge = combined_prob - combined_market

                combos.append(ParlayCombination(
                    legs=list(combo_legs),
                    mode=SGPMode.CLASSIC_PARLAY,
                    combined_model_prob=round(combined_prob, 4),
                    combined_market_prob=round(combined_market, 4),
                    combined_decimal_odds=round(combined_dec, 2),
                    ev=round(ev, 4),
                    edge=round(edge, 4),
                    correlation_note="Independent games — no correlation adjustment",
                ))

        combos = [c for c in combos if c.edge >= self.min_edge]
        combos.sort(key=lambda c: c.ev, reverse=True)
        combos = combos[:top_n]

        for combo in combos:
            combo.stake = self.kelly.bet_size(
                win_prob=combo.combined_model_prob,
                decimal_odds=combo.combined_decimal_odds,
                bankroll=self.bankroll,
            )

        return combos

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build_props_only(
        self,
        legs: list[PropLeg],
        min_legs: int,
        max_legs: int,
    ) -> list[ParlayCombination]:
        combos = []
        for n in range(min_legs, min(max_legs, len(legs)) + 1):
            for combo_legs in itertools.combinations(legs, n):
                combo = self._evaluate_prop_combo(list(combo_legs), SGPMode.PROPS_ONLY)
                if combo:
                    combos.append(combo)
        return combos

    def _build_moneyline_sgp(
        self,
        prop_legs: list[PropLeg],
        ml_leg: dict,
        max_legs: int,
    ) -> list[ParlayCombination]:
        """ML + 1 to (max_legs-1) props."""
        combos = []
        max_props = max_legs - 1
        for n in range(1, min(max_props, len(prop_legs)) + 1):
            for prop_combo in itertools.combinations(prop_legs, n):
                combo = self._evaluate_ml_prop_combo(ml_leg, list(prop_combo))
                if combo:
                    combos.append(combo)
        return combos

    def _build_mixed_sgp(
        self,
        prop_legs: list[PropLeg],
        ml_leg: dict | None,
        min_legs: int,
        max_legs: int,
    ) -> list[ParlayCombination]:
        """All combinations — with or without ML."""
        combos = self._build_props_only(prop_legs, min_legs, max_legs)
        if ml_leg is not None:
            combos += self._build_moneyline_sgp(prop_legs, ml_leg, max_legs)
        return combos

    # ------------------------------------------------------------------
    # Combination evaluators
    # ------------------------------------------------------------------

    def _evaluate_prop_combo(
        self,
        legs: list[PropLeg],
        mode: SGPMode,
    ) -> ParlayCombination | None:
        corr_legs = [(leg.model_prob, leg.player, leg.market) for leg in legs]
        model_joint = self.corr.adjust_multi_leg_prob(corr_legs)

        market_joint = 1.0
        dec_joint = 1.0
        for leg in legs:
            dec = self.ev_calc.american_to_decimal(leg.over_odds)
            market_joint *= self.ev_calc.implied_prob(dec)
            dec_joint *= dec

        ev = self.ev_calc.expected_value(model_joint, dec_joint)
        edge = model_joint - market_joint
        note = self._correlation_note(legs)

        return ParlayCombination(
            legs=legs,
            mode=mode,
            combined_model_prob=round(model_joint, 4),
            combined_market_prob=round(market_joint, 4),
            combined_decimal_odds=round(dec_joint, 2),
            ev=round(ev, 4),
            edge=round(edge, 4),
            correlation_note=note,
        )

    def _evaluate_ml_prop_combo(
        self,
        ml_leg: dict,
        prop_legs: list[PropLeg],
    ) -> ParlayCombination | None:
        # Build combined legs list including ML
        corr_legs = [(leg.model_prob, leg.player, leg.market) for leg in prop_legs]
        # ML leg treated as independent from props (approximate)
        prop_joint = self.corr.adjust_multi_leg_prob(corr_legs) if corr_legs else 1.0
        model_joint = ml_leg["model_prob"] * prop_joint

        ml_dec = ml_leg["decimal_odds"]
        prop_dec = 1.0
        prop_market = 1.0
        for leg in prop_legs:
            d = self.ev_calc.american_to_decimal(leg.over_odds)
            prop_dec *= d
            prop_market *= self.ev_calc.implied_prob(d)

        dec_joint = ml_dec * prop_dec
        ml_market = self.ev_calc.implied_prob(ml_dec)
        market_joint = ml_market * prop_market

        # Check if ML team's own players are over — high positive correlation warning
        ml_team = ml_leg.get("team", "")
        same_team_props = [
            leg for leg in prop_legs
            if ml_team and (ml_team in leg.home_team or ml_team in leg.away_team)
        ]
        note = "ML + props"
        if same_team_props:
            note += f" ⚠ CORR: {ml_team} players on same side as ML (positively correlated)"

        ev = self.ev_calc.expected_value(model_joint, dec_joint)
        edge = model_joint - market_joint

        all_legs: list[PropLeg | dict] = [ml_leg] + list(prop_legs)
        return ParlayCombination(
            legs=all_legs,
            mode=SGPMode.MONEYLINE_SGP,
            combined_model_prob=round(model_joint, 4),
            combined_market_prob=round(market_joint, 4),
            combined_decimal_odds=round(dec_joint, 2),
            ev=round(ev, 4),
            edge=round(edge, 4),
            correlation_note=note,
        )

    def _correlation_note(self, legs: list[PropLeg]) -> str:
        """Summarize dominant correlation pattern across leg pairs."""
        from alpha.engines.sports.correlation import CorrelationType
        notes = []
        for i, a in enumerate(legs):
            for b in legs[i + 1:]:
                r = self.corr.get_correlation(a.player, a.market, b.player, b.market)
                ct = self.corr.classify(r)
                if ct == CorrelationType.NEGATIVE:
                    notes.append(f"{a.player[:12]} vs {b.player[:12]}: r={r:.2f} (EDGE)")
                elif ct == CorrelationType.POSITIVE:
                    notes.append(f"{a.player[:12]} vs {b.player[:12]}: r={r:.2f} (caution)")
        return "; ".join(notes) if notes else "neutral correlation"
```

- [ ] **Step 4: Run tests**

```
VIRTUAL_ENV=./venv python -m pytest tests/unit/test_sgp_builder.py -v
```
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add alpha/engines/sports/sgp_builder.py tests/unit/test_sgp_builder.py
git commit -m "feat: add SGPBuilder with PROPS_ONLY / MONEYLINE_SGP / MIXED_SGP / CLASSIC_PARLAY modes"
```

---

## Chunk 3: Scanner + Integration

### Task 5: SGP Scanner (main CLI entry point)

**Files:**
- Create: `scripts/sgp_scanner.py`
- Test: `tests/unit/test_sgp_scanner.py` (integration smoke test)

**What it does:** Orchestrates the full pipeline. Pulls today's games + ML odds (existing OddsAPIClient), pulls player props (new PlayerPropsClient), runs PropModel on each prop, builds the correlation matrix, runs SGPBuilder in the chosen mode, and prints ranked results.

**CLI usage:**
```
python scripts/sgp_scanner.py                  # default: PROPS_ONLY
python scripts/sgp_scanner.py --mode ml_sgp    # ML + props
python scripts/sgp_scanner.py --mode mixed     # any combo
python scripts/sgp_scanner.py --mode parlay    # multi-game ML parlay
python scripts/sgp_scanner.py --bankroll 5000  # custom bankroll
python scripts/sgp_scanner.py --min-edge 0.03  # lower edge threshold
python scripts/sgp_scanner.py --max-legs 3     # cap legs per combo
```

- [ ] **Step 1: Write smoke tests**

```python
# tests/unit/test_sgp_scanner.py
"""Smoke tests — verifies CLI parses args and constructs pipeline correctly."""
import pytest
from unittest.mock import patch, MagicMock
import subprocess
import sys


def test_cli_help_exits_cleanly():
    result = subprocess.run(
        [sys.executable, "scripts/sgp_scanner.py", "--help"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "mode" in result.stdout


def test_cli_no_api_key_exits_gracefully(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    result = subprocess.run(
        [sys.executable, "scripts/sgp_scanner.py"],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}
    )
    # Should exit without traceback — graceful handling
    assert "Traceback" not in result.stderr
```

- [ ] **Step 2: Run to confirm failures**

```
VIRTUAL_ENV=./venv python -m pytest tests/unit/test_sgp_scanner.py -v
```

- [ ] **Step 3: Implement sgp_scanner.py**

```python
#!/usr/bin/env python
# scripts/sgp_scanner.py
"""
SGP Scanner — finds positive-EV same-game parlay and classic parlay opportunities.

Usage:
    python scripts/sgp_scanner.py [--mode props|ml_sgp|mixed|parlay]
                                  [--bankroll 10000]
                                  [--min-edge 0.05]
                                  [--max-legs 4]
                                  [--markets player_points,player_rebounds]
                                  [--top 5]
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NBA_DIR = ROOT / "NBA-Machine-Learning-Sports-Betting"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(NBA_DIR))

from dotenv import load_dotenv
load_dotenv()


def parse_args():
    p = argparse.ArgumentParser(description="SGP Scanner — NBA parlay edge finder")
    p.add_argument(
        "--mode", choices=["props", "ml_sgp", "mixed", "parlay"],
        default="props",
        help="SGP mode: props=player props only, ml_sgp=ML+props, mixed=any combo, parlay=classic multi-game",
    )
    p.add_argument("--bankroll", type=float, default=10_000.0)
    p.add_argument("--min-edge", type=float, default=0.05, dest="min_edge")
    p.add_argument("--max-legs", type=int, default=4, dest="max_legs")
    p.add_argument(
        "--markets", default="player_points,player_rebounds,player_assists",
        help="Comma-separated list of prop markets to fetch",
    )
    p.add_argument("--top", type=int, default=5, help="Number of top combos to display")
    p.add_argument(
        "--no-corr", action="store_true", dest="no_corr",
        help="Skip correlation matrix build (faster, less accurate)",
    )
    return p.parse_args()


def american_to_decimal(odds: int) -> float:
    if odds > 0:
        return 1 + odds / 100
    return 1 + 100 / abs(odds)


def print_banner():
    print("\n" + "=" * 60)
    print("  NBA SGP SCANNER — Positive EV Parlay Finder")
    print("=" * 60)


def print_combo(combo, idx: int):
    print(f"\n  #{idx + 1}  EV: {combo.ev:.1%}  |  Edge: {combo.edge:.1%}  |  Odds: {combo.combined_decimal_odds:.2f}x")
    print(f"       Model Prob: {combo.combined_model_prob:.1%}  |  Market Implied: {combo.combined_market_prob:.1%}")
    if combo.stake:
        print(f"       Stake: ${combo.stake:.2f}")
    if combo.correlation_note:
        print(f"       Correlation: {combo.correlation_note}")
    print("       Legs:")
    for leg in combo.legs:
        if isinstance(leg, dict):
            # ML leg
            print(f"         • ML: {leg.get('team', '?')} @ {leg.get('decimal_odds', 0):.2f}x  (model: {leg.get('model_prob', 0):.1%})")
        else:
            # Prop leg
            direction = leg.direction.upper()
            print(f"         • {leg.player}: {direction} {leg.line} {leg.market.replace('player_', '')}  "
                  f"({leg.over_odds:+d})  model: {leg.model_prob:.1%}")


def main():
    args = parse_args()
    print_banner()

    from alpha.data.ingestion.odds_api import OddsAPIClient
    from alpha.data.ingestion.player_props import PlayerPropsClient
    from alpha.engines.sports.prop_model import PropModel
    from alpha.engines.sports.correlation import CorrelationEngine
    from alpha.engines.sports.sgp_builder import SGPBuilder, SGPMode, PropLeg
    from alpha.engines.sports.nba_model import NBAModel

    markets = [m.strip() for m in args.markets.split(",")]
    mode_map = {
        "props": SGPMode.PROPS_ONLY,
        "ml_sgp": SGPMode.MONEYLINE_SGP,
        "mixed": SGPMode.MIXED_SGP,
        "parlay": SGPMode.CLASSIC_PARLAY,
    }
    mode = mode_map[args.mode]

    # --- Step 1: Fetch games + ML odds ---
    print("\n[1/5] Fetching today's NBA games...")
    games = OddsAPIClient().fetch_nba_games()
    if not games:
        print("No games found. Check ODDS_API_KEY in .env")
        sys.exit(1)
    print(f"      {len(games)} games found")

    # --- Step 2: Fetch player props ---
    if mode != SGPMode.CLASSIC_PARLAY:
        print(f"\n[2/5] Fetching player props ({', '.join(markets)})...")
        event_ids = [g["event_id"] for g in games]
        raw_props = PlayerPropsClient().fetch_nba_props(markets=markets, event_ids=event_ids)
        print(f"      {len(raw_props)} prop lines fetched")
    else:
        raw_props = []
        print("\n[2/5] Classic parlay mode — skipping props fetch")

    # --- Step 3: Run prop model ---
    if raw_props:
        print(f"\n[3/5] Running prop model (nba_api)...")
        prop_model = PropModel()
        game_map = {g["event_id"]: g for g in games}
        scored_props: list[dict] = []
        for prop in raw_props:
            game = game_map.get(prop["event_id"])
            if game is None:
                continue
            # Determine opponent
            is_home_player = True  # approximate: assume home if not determinable
            opponent = game["away_team"] if is_home_player else game["home_team"]
            pred = prop_model.predict_prop(
                player_name=prop["player"],
                market=prop["market"],
                line=prop["line"],
                opponent_team=opponent,
            )
            if pred is not None:
                scored_props.append({**prop, **pred})
        print(f"      {len(scored_props)} props modeled successfully")
    else:
        scored_props = []

    # --- Step 4: Build correlation matrix ---
    corr_engine = CorrelationEngine()
    if scored_props and not args.no_corr:
        print(f"\n[4/5] Building correlation matrix ({len({p['player'] for p in scored_props})} players)...")
        player_names = list({p["player"] for p in scored_props})
        corr_engine.build(player_names=player_names)
        print("      Correlation matrix ready")
    else:
        print("\n[4/5] Correlation matrix skipped")

    # --- Step 5: Build SGPs ---
    print(f"\n[5/5] Building {args.mode.upper()} combinations...")
    builder = SGPBuilder(
        correlation_engine=corr_engine,
        min_edge=args.min_edge,
        kelly_fraction=0.15,
        bankroll=args.bankroll,
    )

    all_combos = []

    if mode == SGPMode.CLASSIC_PARLAY:
        # Use ML model for each game
        nba_model = NBAModel()
        ml_bets = []
        for game in games:
            ev_result = nba_model.evaluate_bet(game)
            if ev_result["bet_side"] != "no_bet":
                ml_bets.append({
                    "team": ev_result["team"],
                    "model_prob": ev_result["model_prob"],
                    "decimal_odds": ev_result["decimal_odds"],
                    "event_id": game["event_id"],
                })
        combos = builder.build_classic_parlay(ml_bets, max_legs=args.max_legs, top_n=args.top)
        all_combos.extend(combos)
    else:
        # Group props by game
        by_game: dict[str, list[dict]] = {}
        for prop in scored_props:
            by_game.setdefault(prop["event_id"], []).append(prop)

        nba_model = NBAModel() if mode in (SGPMode.MONEYLINE_SGP, SGPMode.MIXED_SGP) else None

        for event_id, game_props in by_game.items():
            game = game_map.get(event_id)
            if game is None:
                continue

            prop_legs = [
                PropLeg(
                    player=p["player"],
                    market=p["market"],
                    line=p["line"],
                    model_prob=p["model_prob"],
                    over_odds=p["over_odds"],
                    event_id=event_id,
                    home_team=game["home_team"],
                    away_team=game["away_team"],
                )
                for p in game_props
            ]

            ml_leg = None
            if nba_model is not None:
                ev_result = nba_model.evaluate_bet(game)
                if ev_result["bet_side"] != "no_bet":
                    ml_leg = {
                        "team": ev_result["team"],
                        "model_prob": ev_result["model_prob"],
                        "decimal_odds": ev_result["decimal_odds"],
                        "event_id": event_id,
                    }

            combos = builder.build(
                prop_legs=prop_legs,
                mode=mode,
                ml_leg=ml_leg,
                max_legs=args.max_legs,
                top_n=args.top,
            )
            all_combos.extend(combos)

    # Sort all combos globally by EV
    all_combos.sort(key=lambda c: c.ev, reverse=True)
    top_combos = all_combos[:args.top]

    # --- Output ---
    print("\n" + "=" * 60)
    if not top_combos:
        print(f"  No {args.mode.upper()} combinations with >{args.min_edge:.0%} edge found today.")
        print(f"  Try --min-edge 0.03 or --mode mixed for more results.")
    else:
        print(f"  TOP {len(top_combos)} {args.mode.upper()} COMBINATIONS (min edge: {args.min_edge:.0%})")
        for i, combo in enumerate(top_combos):
            print_combo(combo, i)
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run smoke tests**

```
VIRTUAL_ENV=./venv python -m pytest tests/unit/test_sgp_scanner.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Verify CLI works end-to-end**

```bash
VIRTUAL_ENV=./venv python scripts/sgp_scanner.py --help
VIRTUAL_ENV=./venv python scripts/sgp_scanner.py --mode props --min-edge 0.03
```

- [ ] **Step 6: Commit**

```bash
git add scripts/sgp_scanner.py tests/unit/test_sgp_scanner.py
git commit -m "feat: add SGP Scanner CLI (props/ml_sgp/mixed/parlay modes)"
```

---

### Task 6: Run full test suite + final integration check

- [ ] **Step 1: Run all tests**

```
VIRTUAL_ENV=./venv python -m pytest tests/ -v --tb=short
```
Expected: All passing (existing 142 + ~17 new = ~159 tests)

- [ ] **Step 2: Smoke-run scanner in each mode**

```bash
# Props only
VIRTUAL_ENV=./venv python scripts/sgp_scanner.py --mode props --min-edge 0.03 --no-corr

# Classic parlay (fastest — no props needed)
VIRTUAL_ENV=./venv python scripts/sgp_scanner.py --mode parlay
```

Note: Full modes (ml_sgp, mixed) will make nba_api calls and take 2–5 minutes.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: SGP generator complete — player props + correlation + 4 parlay modes"
```

---

## Quick Reference: Running the Scanner

```bash
# Player props SGP (fastest with --no-corr flag)
.\venv\Scripts\python.exe .\scripts\sgp_scanner.py --mode props --no-corr

# ML + props SGP (best for sharp plays)
.\venv\Scripts\python.exe .\scripts\sgp_scanner.py --mode ml_sgp

# All combinations (most thorough)
.\venv\Scripts\python.exe .\scripts\sgp_scanner.py --mode mixed --max-legs 3

# Classic multi-game parlay
.\venv\Scripts\python.exe .\scripts\sgp_scanner.py --mode parlay --max-legs 3

# Lower edge threshold for more results
.\venv\Scripts\python.exe .\scripts\sgp_scanner.py --mode props --min-edge 0.03
```

## Key Algorithm Notes for Maintainers

**Why correlation matters:**
- Book prices SGP legs as if they're independent (multiplies implied probs)
- Positively correlated legs: true joint prob > naive product → book underprices for bettors but also makes edge calculation flatter
- Negatively correlated legs: true joint prob < naive product → book OVERPRICES, meaning the naive market implied is too high and our model joint is lower — this looks like *negative* edge unless our individual leg models have enough edge to overcome it
- **The real source of edge:** strong individual prop model predictions (65%+ confidence), combined with neutral-to-negative correlated legs

**Correlation adjustment formula (bivariate normal copula approximation):**
```
P(A ∩ B) ≈ P(A)*P(B) + r * sqrt(P(A)*(1-P(A)) * P(B)*(1-P(B)))
```
This is valid when individual probabilities are not extreme (0.2 – 0.8 range).

**API cost awareness:**
- The Odds API: each player props call costs multiple credits. ~4 markets × ~5 games = 20 credits per run.
- nba_api: rate-limited; PropModel sleeps 0.6s between calls. 20 players × 2 calls each ≈ 24 seconds.
- Correlation matrix: cached 24 hours → only 1 nba_api build per day.
