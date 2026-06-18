# Phase 5: Data Foundation - Pattern Map

**Mapped:** 2026-06-18
**Files analyzed:** 7 (3 source files + 1 script + 3 test files)
**Analogs found:** 7 / 7

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `alpha/data/ingestion/football_data_client.py` | service (HTTP client) | request-response | `alpha/data/ingestion/football_data_client.py` (self — modify in place) | exact |
| `alpha/data/ingestion/wc_stats.py` | service (cache reader) | file-I/O | `alpha/data/ingestion/soccer_stats.py` | exact (same cache pattern) |
| `alpha/data/ingestion/wc_elo.py` | utility (JSON loader) | file-I/O | `alpha/data/ingestion/mlb_stats.py` (_load_cache / _save_cache functions) | role-match |
| `scripts/build_wc_priors.py` | script (one-time offline) | batch | `scripts/fetch_historical_logs.py` | role-match (one-time batch fetcher) |
| `tests/unit/data/test_football_data_client_wc.py` | test | request-response | `tests/unit/data/test_odds_api.py` | exact (HTTP mock pattern) |
| `tests/unit/test_wc_stats.py` | test | file-I/O | `tests/unit/test_mlb_stats.py` | exact (tmp_path + pkl fixture pattern) |
| `tests/unit/test_wc_priors_loader.py` | test | file-I/O | `tests/unit/test_mlb_stats.py` | role-match (tmp_path + JSON fixture pattern) |

---

## Pattern Assignments

### `alpha/data/ingestion/football_data_client.py` (service, request-response — MODIFIED)

**Analog:** `alpha/data/ingestion/football_data_client.py` (self — current file is the template)

**Current imports block** (lines 1-21):
```python
from __future__ import annotations

import logging
import os
from datetime import date

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.football-data.org/v4"

_COMP_MAP: dict[str, str] = {
    "epl": "PL",   # English Premier League
    "ucl": "CL",   # UEFA Champions League
}
```

**Change 1 — add `"wc": "WC"` to `_COMP_MAP`** (line 26):
```python
_COMP_MAP: dict[str, str] = {
    "epl": "PL",   # English Premier League
    "ucl": "CL",   # UEFA Champions League
    "wc":  "WC",   # FIFA World Cup
}
```

**Change 2 — add `import time` to imports** (after `import requests`, line 19):
```python
import time
```

**Change 3 — add 429 retry wrapper as private helper** (insert after the `_COMP_MAP` block):
```python
def _get_with_retry(url: str, *, headers: dict, params: dict, timeout: int = 10):
    """
    GET with one 429 retry after 60s backoff.
    Raises requests.exceptions.HTTPError on non-429 HTTP errors.
    Returns requests.Response on success.
    """
    for attempt in range(2):
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        if resp.status_code == 429 and attempt == 0:
            logger.warning("football-data.org 429 — waiting 60s before retry")
            time.sleep(60)
            continue
        resp.raise_for_status()
        return resp
    # Second attempt still returned 429 — raise to let caller handle
    resp.raise_for_status()
    return resp  # unreachable but satisfies type checkers
```

**Change 4 — add `fetch_wc_games()` method** (copy method signature pattern from `fetch_today_games()`, lines 39-105):
```python
def fetch_wc_games(self, date_from: str, date_to: str) -> list[dict]:
    """
    Fetch WC 2026 fixtures for a date range.

    Returns game dicts with all standard fields plus two new fields:
        "stage": str   — e.g. "GROUP_STAGE", "LAST_16", "QUARTER_FINALS",
                         "SEMI_FINALS", "THIRD_PLACE", "FINAL"
        "group": str   — e.g. "Group A" (empty string in knockout rounds)

    Returns [] on any failure (including missing API key).
    """
    if not self.is_configured():
        logger.warning("FOOTBALL_API_KEY not set — WC game fetch skipped")
        return []

    try:
        resp = _get_with_retry(
            f"{_BASE_URL}/competitions/WC/matches",
            headers={"X-Auth-Token": self.api_key},
            params={"dateFrom": date_from, "dateTo": date_to},
            timeout=10,
        )
        data = resp.json()
        games = []
        for match in data.get("matches", []):
            home = match.get("homeTeam", {}).get("name", "")
            away = match.get("awayTeam", {}).get("name", "")
            if not home or not away:
                continue
            games.append({
                "home_team": home,
                "away_team": away,
                "home_odds": -110,
                "away_odds": -110,
                "league": "wc",
                "event_id": str(match.get("id", "")),
                "commence_time": match.get("utcDate", ""),
                "stage": match.get("stage", ""),
                "group": match.get("group", ""),
            })
        logger.info("Fetched %d WC games from football-data.org", len(games))
        return games

    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        logger.warning("football-data.org HTTP %s for WC", status)
    except Exception as exc:
        logger.warning("football-data.org WC error: %s", exc)
    return []
```

**Error handling pattern** (from lines 100-105 of current `fetch_today_games()`):
```python
except requests.exceptions.HTTPError as exc:
    status = exc.response.status_code if exc.response is not None else "?"
    logger.warning("football-data.org HTTP %s for %s", status, league_key)
except Exception as exc:
    logger.warning("football-data.org error for %s: %s", league_key, exc)
return []
```

---

### `alpha/data/ingestion/wc_stats.py` (service, file-I/O — NEW)

**Analog:** `alpha/data/ingestion/soccer_stats.py`

**Imports pattern** — mirrors soccer_stats.py lines 19-29 but removes async deps:
```python
from __future__ import annotations

import logging
import pickle
from pathlib import Path

logger = logging.getLogger(__name__)
```

**Cache constants pattern** — mirrors soccer_stats.py lines 43-49 with WC namespace:
```python
# Separate namespace from data/.soccer_cache/ — never share keys
_WC_CACHE_DIR = Path("data/.wc_cache")
_WC_STATS_CACHE = _WC_CACHE_DIR / "wc_stats.pkl"   # no date suffix: historical data is static

# StatsBomb name -> football-data.org name normalisation
# Populated after first run of build_wc_priors.py by inspecting sb.matches() team names
_TEAM_NAME_MAP: dict[str, str] = {
    # Examples (complete map built during Phase 5 execution):
    # "United States Men's National Team": "United States",
    # "Korea Republic": "South Korea",
}
```

**Core pattern — public loader** (mirrors `get_team_rolling_stats()` cache-hit path in soccer_stats.py lines 111-198):
```python
def get_wc_team_stats() -> dict[str, dict]:
    """
    Return StatsBomb-derived team stats keyed by football-data.org team name.

    Output shape per team:
        {
            "avg_goals":     float,   # goals scored per game
            "avg_xG":        float,   # xG for per game
            "avg_shots":     float,   # shots per game
            "defense_score": float,   # xG against per game (lower = better)
        }

    Raises FileNotFoundError if cache missing.
    Instructs user to run: python scripts/build_wc_priors.py
    """
    if not _WC_STATS_CACHE.exists():
        raise FileNotFoundError(
            f"WC stats cache not found at {_WC_STATS_CACHE}. "
            "Run: ./venv/Scripts/python.exe scripts/build_wc_priors.py"
        )
    with open(_WC_STATS_CACHE, "rb") as f:
        data: dict = pickle.load(f)

    built_at = data.pop("built_at", "unknown")
    logger.debug("WC stats cache loaded (built_at=%s, teams=%d)", built_at, len(data))

    # Apply team name normalisation map
    normalised: dict[str, dict] = {}
    for team, stats in data.items():
        canonical = _TEAM_NAME_MAP.get(team, team)
        normalised[canonical] = stats
    return normalised
```

**Error handling:** `FileNotFoundError` raised (not swallowed) — caller must handle. The scanner should catch and log a warning, then proceed without WC stats (same graceful degradation as soccer_stats.py returning `[]` for unsupported leagues).

---

### `alpha/data/ingestion/wc_elo.py` (utility, file-I/O — NEW)

**Analog:** `alpha/data/ingestion/mlb_stats.py` (cache load/save helpers, lines 29-51)

**Imports pattern:**
```python
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
```

**Cache constants:**
```python
_WC_PRIORS_PATH = Path("data/wc_priors.json")
_ELO_FALLBACK = 1500   # FIFA world average
```

**Core pattern — public loader** (JSON read, mirrors mlb_stats.py `_load_cache` + graceful fallback):
```python
def load_wc_elo_ratings() -> dict[str, int]:
    """
    Load Elo ratings from data/wc_priors.json.

    Returns {team_name: elo_rating} for all teams in the file.
    Raises FileNotFoundError if wc_priors.json is missing.
    """
    if not _WC_PRIORS_PATH.exists():
        raise FileNotFoundError(
            f"WC Elo priors not found at {_WC_PRIORS_PATH}. "
            "Run: ./venv/Scripts/python.exe scripts/build_wc_priors.py"
        )
    with open(_WC_PRIORS_PATH, "r", encoding="utf-8") as f:
        ratings: dict[str, int] = json.load(f)
    logger.debug("Loaded Elo ratings for %d teams from %s", len(ratings), _WC_PRIORS_PATH)
    return ratings


def get_elo_rating(team: str, ratings: dict[str, int]) -> int:
    """Return Elo rating for team, falling back to 1500 if missing."""
    rating = ratings.get(team, _ELO_FALLBACK)
    if rating == _ELO_FALLBACK and team not in ratings:
        logger.warning("No Elo rating for team '%s' — using fallback %d", team, _ELO_FALLBACK)
    return rating
```

---

### `scripts/build_wc_priors.py` (one-time offline script — NEW)

**Analog:** `scripts/fetch_historical_logs.py` (one-time batch fetcher pattern, lines 1-97)

**Module header pattern** (mirrors fetch_historical_logs.py lines 1-13):
```python
"""
Build WC 2026 priors: Elo ratings + StatsBomb team stats.

ONE-TIME OFFLINE SCRIPT — do not call from the live scanner.
Runtime: ~2-5 minutes (128 StatsBomb match fetches + 48 Elo TSV requests).

Outputs:
    data/wc_priors.json        — {team_name: elo_rating} for all 48 WC teams
    data/.wc_cache/wc_stats.pkl — StatsBomb team stats dict

Usage:
    ./venv/Scripts/python.exe scripts/build_wc_priors.py
"""
from __future__ import annotations

import json
import logging
import pickle
import time
from pathlib import Path

import requests
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)
```

**Constants block** (mirrors SEASONS constant in fetch_historical_logs.py line 25):
```python
WC_SEASONS = [
    {"competition_id": 43, "season_id": 3},    # 2018 WC
    {"competition_id": 43, "season_id": 106},  # 2022 WC
]
WC_CACHE_DIR = Path("data/.wc_cache")
WC_STATS_CACHE = WC_CACHE_DIR / "wc_stats.pkl"
WC_PRIORS_PATH = Path("data/wc_priors.json")
ELO_BASE = "https://www.eloratings.net"
ELO_FALLBACK = 1500
ELO_SLEEP = 0.1   # rate limit between TSV requests
```

**Progress reporting pattern** (mirrors fetch_historical_logs.py lines 62-64):
```python
print(f"\r  [{done}/{total}] {team_name[:35]:<35}", end="", flush=True)
```

**try/except per-item pattern** (mirrors fetch_historical_logs.py lines 65-91):
```python
for match_id in match_ids:
    try:
        events = sb.events(match_id=match_id)
        # ... aggregate
    except Exception as exc:
        logger.warning("StatsBomb events failed for match %s: %s", match_id, exc)
        continue   # partial data is acceptable — log n_games_loaded
```

**Output write pattern** (mirrors fetch_historical_logs.py lines 55-57 but uses json/pickle):
```python
WC_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Write stats pickle — always overwrite (never check if exists)
stats["built_at"] = str(pd.Timestamp.now())
with open(WC_STATS_CACHE, "wb") as f:
    pickle.dump(stats, f)
logger.info("Wrote WC stats to %s (%d teams)", WC_STATS_CACHE, len(stats) - 1)

# Write Elo JSON
WC_PRIORS_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(WC_PRIORS_PATH, "w", encoding="utf-8") as f:
    json.dump(elo_ratings, f, indent=2)
logger.info("Wrote Elo ratings to %s (%d teams)", WC_PRIORS_PATH, len(elo_ratings))
```

**`if __name__ == "__main__":` guard** (mirrors fetch_historical_logs.py line 96):
```python
if __name__ == "__main__":
    build_wc_priors()
```

---

### `tests/unit/data/test_football_data_client_wc.py` (test — NEW)

**Analog:** `tests/unit/data/test_odds_api.py`

**Imports pattern** (mirrors test_odds_api.py lines 1-8):
```python
"""Tests for FootballDataClient.fetch_wc_games() and 429 retry."""
from unittest.mock import MagicMock, call, patch

import pytest
import requests as req_lib

from alpha.data.ingestion.football_data_client import FootballDataClient, _COMP_MAP
```

**Fixture builder pattern** (mirrors test_odds_api.py `_make_event()` helper, lines 15-43):
```python
def _make_match_response(home: str, away: str, match_id: int = 1,
                         stage: str = "GROUP_STAGE", group: str = "Group A") -> dict:
    """Build a minimal football-data.org matches response body."""
    return {
        "matches": [{
            "id": match_id,
            "utcDate": "2026-06-12T18:00:00Z",
            "stage": stage,
            "group": group,
            "homeTeam": {"name": home},
            "awayTeam": {"name": away},
        }]
    }
```

**HTTP mock pattern** (mirrors test_odds_api.py lines 84-107):
```python
def test_fetch_wc_games_returns_stage_and_group():
    client = FootballDataClient(api_key="testkey")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _make_match_response("Brazil", "Germany")
    mock_resp.raise_for_status.return_value = None

    with patch("alpha.data.ingestion.football_data_client.requests.get",
               return_value=mock_resp):
        games = client.fetch_wc_games("2026-06-12", "2026-06-12")

    assert len(games) == 1
    g = games[0]
    assert g["home_team"] == "Brazil"
    assert g["away_team"] == "Germany"
    assert g["stage"] == "GROUP_STAGE"
    assert g["group"] == "Group A"
    assert g["league"] == "wc"
```

**Error path pattern** (mirrors test_odds_api.py `test_fetch_returns_empty_on_http_error`, lines 132-142):
```python
def test_fetch_wc_games_returns_empty_on_http_error():
    client = FootballDataClient(api_key="testkey")
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    http_err = req_lib.exceptions.HTTPError(response=mock_resp)

    with patch("alpha.data.ingestion.football_data_client.requests.get",
               side_effect=http_err):
        result = client.fetch_wc_games("2026-06-12", "2026-06-12")

    assert result == []
```

**429 retry test pattern** (unique to WC — uses `side_effect` list and `time.sleep` mock):
```python
def test_fetch_wc_games_429_retry(monkeypatch):
    """First call returns 429; second call returns 200 with data."""
    client = FootballDataClient(api_key="testkey")

    resp_429 = MagicMock()
    resp_429.status_code = 429

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = _make_match_response("France", "Argentina")
    resp_200.raise_for_status.return_value = None

    sleep_calls = []
    monkeypatch.setattr("alpha.data.ingestion.football_data_client.time.sleep",
                        lambda s: sleep_calls.append(s))

    with patch("alpha.data.ingestion.football_data_client.requests.get",
               side_effect=[resp_429, resp_200]):
        games = client.fetch_wc_games("2026-06-14", "2026-06-14")

    assert len(games) == 1
    assert sleep_calls == [60]   # exactly one 60s wait
```

**`_COMP_MAP` regression test:**
```python
def test_comp_map_has_wc():
    assert "wc" in _COMP_MAP
    assert _COMP_MAP["wc"] == "WC"

def test_comp_map_epl_ucl_unchanged():
    assert _COMP_MAP["epl"] == "PL"
    assert _COMP_MAP["ucl"] == "CL"
```

---

### `tests/unit/test_wc_stats.py` (test — NEW)

**Analog:** `tests/unit/test_mlb_stats.py`

**Imports pattern** (mirrors test_mlb_stats.py lines 1-19):
```python
"""Tests for alpha/data/ingestion/wc_stats.py."""
from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from alpha.data.ingestion.wc_stats import get_wc_team_stats, _WC_STATS_CACHE, _WC_CACHE_DIR
```

**`tmp_path` + cache fixture pattern** (mirrors test_mlb_stats.py `test_team_batting_stats_uses_cache`, lines 46-56):
```python
def test_get_wc_team_stats_loads_pkl(tmp_path, monkeypatch):
    """get_wc_team_stats() loads data from the pkl file."""
    monkeypatch.setattr("alpha.data.ingestion.wc_stats._WC_STATS_CACHE",
                        tmp_path / "wc_stats.pkl")
    monkeypatch.setattr("alpha.data.ingestion.wc_stats._WC_CACHE_DIR", tmp_path)

    fake_stats = {
        "Brazil": {"avg_goals": 2.1, "avg_xG": 1.9, "avg_shots": 14.5, "defense_score": 0.7},
        "built_at": "2026-06-18T12:00:00",
    }
    with open(tmp_path / "wc_stats.pkl", "wb") as f:
        pickle.dump(fake_stats, f)

    result = get_wc_team_stats()
    assert "Brazil" in result
    assert result["Brazil"]["avg_goals"] == pytest.approx(2.1)
    assert "built_at" not in result   # popped from output dict
```

**Missing cache raises pattern** (mirrors test_mlb_stats.py `test_team_batting_stats_returns_empty_on_pybaseball_error`, lines 26-30 — but here we raise):
```python
def test_get_wc_team_stats_missing_pkl_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.data.ingestion.wc_stats._WC_STATS_CACHE",
                        tmp_path / "nonexistent.pkl")
    with pytest.raises(FileNotFoundError, match="build_wc_priors.py"):
        get_wc_team_stats()
```

**Output shape test:**
```python
def test_wc_stats_output_shape(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.data.ingestion.wc_stats._WC_STATS_CACHE",
                        tmp_path / "wc_stats.pkl")
    fake = {"Germany": {"avg_goals": 1.8, "avg_xG": 1.7, "avg_shots": 12.0, "defense_score": 0.9}}
    with open(tmp_path / "wc_stats.pkl", "wb") as f:
        pickle.dump(fake, f)

    result = get_wc_team_stats()
    team_stats = result["Germany"]
    assert set(team_stats.keys()) == {"avg_goals", "avg_xG", "avg_shots", "defense_score"}
```

**Cache path isolation test:**
```python
def test_wc_cache_path_isolated():
    """WC cache dir must be data/.wc_cache, NOT data/.soccer_cache."""
    assert "wc_cache" in str(_WC_CACHE_DIR)
    assert "soccer_cache" not in str(_WC_CACHE_DIR)
    assert "wc_stats.pkl" in str(_WC_STATS_CACHE)
```

---

### `tests/unit/test_wc_priors_loader.py` (test — NEW)

**Analog:** `tests/unit/test_mlb_stats.py` (tmp_path + JSON fixture variant)

**Imports pattern:**
```python
"""Tests for alpha/data/ingestion/wc_elo.py — Elo loader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from alpha.data.ingestion.wc_elo import load_wc_elo_ratings, get_elo_rating, _ELO_FALLBACK
```

**JSON fixture pattern** (monkeypatch + tmp_path, same idiom as test_mlb_stats.py lines 46-56):
```python
def test_load_wc_priors_returns_dict(tmp_path, monkeypatch):
    priors_file = tmp_path / "wc_priors.json"
    priors_file.write_text(json.dumps({"Brazil": 2100, "Germany": 1980}), encoding="utf-8")
    monkeypatch.setattr("alpha.data.ingestion.wc_elo._WC_PRIORS_PATH", priors_file)

    result = load_wc_elo_ratings()
    assert isinstance(result, dict)
    assert len(result) >= 1
    assert result["Brazil"] == 2100
```

**Fallback test:**
```python
def test_elo_fallback_1500():
    ratings = {"Brazil": 2100}
    assert get_elo_rating("Zimbabwe", ratings) == _ELO_FALLBACK
    assert get_elo_rating("Brazil", ratings) == 2100
```

**Missing file raises pattern** (mirrors test_mlb_stats.py missing-data tests):
```python
def test_missing_priors_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("alpha.data.ingestion.wc_elo._WC_PRIORS_PATH",
                        tmp_path / "nonexistent.json")
    with pytest.raises(FileNotFoundError, match="build_wc_priors.py"):
        load_wc_elo_ratings()
```

---

## Shared Patterns

### Cache Read/Write (pickle)
**Source:** `alpha/data/ingestion/soccer_stats.py` lines 47-68
**Apply to:** `wc_stats.py` (read-only), `scripts/build_wc_priors.py` (write)
```python
def _cache_path(key: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{key}_{date.today()}.pkl"   # WC variant uses fixed name (no date)

def _load_cache(key: str) -> Any | None:
    path = _cache_path(key)
    if path.exists():
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    return None

def _save_cache(key: str, data: Any) -> None:
    try:
        with open(_cache_path(key), "wb") as f:
            pickle.dump(data, f)
    except Exception as exc:
        logger.debug("Cache write failed: %s", exc)
```
Note: WC stats use a fixed filename `wc_stats.pkl` (no date suffix) because historical StatsBomb data does not change. This diverges from the date-keyed `f"{key}_{date.today()}.pkl"` pattern used by `soccer_stats.py` and `mlb_stats.py`.

### HTTP Request Pattern
**Source:** `alpha/data/ingestion/football_data_client.py` lines 68-74
**Apply to:** `football_data_client.py` (`fetch_wc_games()`), `scripts/build_wc_priors.py` (eloratings.net fetch)
```python
resp = requests.get(
    f"{_BASE_URL}/competitions/{comp}/matches",
    headers={"X-Auth-Token": self.api_key},
    params={"dateFrom": today, "dateTo": today},
    timeout=10,
)
resp.raise_for_status()
data = resp.json()
```

### Logging Pattern
**Source:** `alpha/data/ingestion/football_data_client.py` lines 21, 95-97
**Apply to:** All new files
```python
logger = logging.getLogger(__name__)
# ...
logger.info("Fetched %d WC games from football-data.org", len(games))
logger.warning("football-data.org HTTP %s for WC", status)
# NEVER log self.api_key
```

### Graceful Degradation (return [] / raise clearly)
**Source:** `alpha/data/ingestion/soccer_stats.py` lines 129-135, 196-198
**Apply to:** All new ingestion files

Two patterns are used — choose by context:
- **Return `[]`** when the caller can continue with no data (scanner skips, uses market-implied fallback)
- **Raise `FileNotFoundError`** with a clear action message when a required pre-built file is missing (`wc_stats.pkl`, `wc_priors.json`) — these indicate the user forgot to run `build_wc_priors.py`

```python
# Pattern A: return [] (caller degrades gracefully)
except Exception as exc:
    logger.warning("fetch failed: %s", exc)
    return []

# Pattern B: raise with action message (missing pre-built artifact)
if not _WC_STATS_CACHE.exists():
    raise FileNotFoundError(
        f"Cache not found at {_WC_STATS_CACHE}. "
        "Run: ./venv/Scripts/python.exe scripts/build_wc_priors.py"
    )
```

### Monkeypatch Cache Dir in Tests
**Source:** `tests/unit/test_mlb_stats.py` lines 26-30
**Apply to:** All new cache-reading test files
```python
def test_something(monkeypatch, tmp_path):
    monkeypatch.setattr("alpha.data.ingestion.wc_stats._WC_STATS_CACHE",
                        tmp_path / "wc_stats.pkl")
    monkeypatch.setattr("alpha.data.ingestion.wc_stats._WC_CACHE_DIR", tmp_path)
    # ... build fixture, call function, assert
```

### HTTP Mock in Tests
**Source:** `tests/unit/data/test_odds_api.py` lines 92-107
**Apply to:** `tests/unit/data/test_football_data_client_wc.py`
```python
mock_resp = MagicMock()
mock_resp.json.return_value = {...}
mock_resp.raise_for_status.return_value = None

with patch("alpha.data.ingestion.football_data_client.requests.get",
           return_value=mock_resp):
    result = client.fetch_wc_games(...)
```

---

## No Analog Found

All files have close analogs. No entries in this section.

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| — | — | — | — |

---

## Metadata

**Analog search scope:** `alpha/data/ingestion/`, `scripts/`, `tests/unit/data/`, `tests/unit/`
**Files scanned:** 8 source files read in full
**Analogs confirmed:** soccer_stats.py (cache pattern), football_data_client.py (HTTP + class), mlb_stats.py (cache helpers + test fixtures), test_odds_api.py (HTTP mock tests), test_mlb_stats.py (tmp_path + pkl tests), fetch_historical_logs.py (one-time script), cache_hygiene.py (Path + mkdir pattern)
**Pattern extraction date:** 2026-06-18
