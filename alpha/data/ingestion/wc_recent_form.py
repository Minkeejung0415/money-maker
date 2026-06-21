"""Recent, leakage-safe national-team goal form from EloRatings match history."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
from typing import Any

import requests

_BASE_URL = "https://www.eloratings.net"
_CACHE_PATH = Path("data/.wc_cache/recent_form.json")
_CACHE_TTL = timedelta(hours=6)
_DECAY = 0.85
_REFERENCE_ELO = 1800.0
_MIN_GAMES = 5

_SLUG_OVERRIDES = {
    "Bosnia-Herzegovina": "Bosnia_and_Herzegovina",
    "Cape Verde Islands": "Cape_Verde",
    "Congo DR": "DR_Congo",
    "Curaçao": "Curacao",
    "Ivory Coast": "Ivory_Coast",
    "New Zealand": "New_Zealand",
    "Saudi Arabia": "Saudi_Arabia",
    "South Africa": "South_Africa",
    "South Korea": "South_Korea",
    "United States": "United_States",
}


def _slug(team_name: str) -> str:
    return _SLUG_OVERRIDES.get(team_name, team_name.replace(" ", "_").replace("'", ""))


def _safe_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_recent_form_tsv(
    text: str,
    *,
    as_of: date,
    n: int = 10,
    min_games: int = _MIN_GAMES,
) -> dict[str, Any] | None:
    """Parse the last `n` matches strictly before `as_of` from one team TSV."""
    rows = [row.split("\t") for row in text.splitlines() if row.strip()]
    valid = []
    for row in rows:
        if len(row) < 12:
            continue
        try:
            match_date = date(int(row[0]), int(row[1]), int(row[2]))
        except (TypeError, ValueError):
            continue
        if match_date >= as_of:
            continue
        if None in (_safe_float(row[5]), _safe_float(row[6]), _safe_float(row[10]), _safe_float(row[11])):
            continue
        valid.append((match_date, row))
    if not valid:
        return None

    team_iso = Counter(
        code for _, row in valid for code in (row[3], row[4])
    ).most_common(1)[0][0]
    matches = []
    for match_date, row in sorted(valid, key=lambda item: item[0])[-n:]:
        is_home = row[3] == team_iso
        if not is_home and row[4] != team_iso:
            continue
        goals_for = float(row[5] if is_home else row[6])
        goals_against = float(row[6] if is_home else row[5])
        team_elo = float(row[10] if is_home else row[11])
        opponent_elo = float(row[11] if is_home else row[10])
        # Goals against stronger opponents count more for attack and less for
        # defensive blame; weak-opponent results receive the inverse treatment.
        attack_factor = 10.0 ** ((opponent_elo - _REFERENCE_ELO) / 1600.0)
        defense_factor = 1.0 / attack_factor
        matches.append({
            "date": match_date,
            "adjusted_for": goals_for * attack_factor,
            "adjusted_against": goals_against * defense_factor,
            "opponent_elo": opponent_elo,
            "team_elo": team_elo,
        })
    if len(matches) < min(min_games, n):
        return None

    weights = [_DECAY ** index for index in range(len(matches) - 1, -1, -1)]
    weight_total = sum(weights)
    return {
        "avg_goals": round(sum(m["adjusted_for"] * w for m, w in zip(matches, weights)) / weight_total, 4),
        "avg_xG": round(sum(m["adjusted_for"] * w for m, w in zip(matches, weights)) / weight_total, 4),
        "defense_score": round(sum(m["adjusted_against"] * w for m, w in zip(matches, weights)) / weight_total, 4),
        "games": len(matches),
        "latest_match": matches[-1]["date"].isoformat(),
        "elo_rating": round(matches[-1]["team_elo"]),
        "source": "eloratings_recent_results",
    }


class WCRecentFormClient:
    """Fetch and cache recent form for every team requested by the scanner."""

    def __init__(self, cache_path: str | Path = _CACHE_PATH) -> None:
        self._cache_path = Path(cache_path)

    def _load_cache(self) -> dict[str, Any]:
        try:
            with self._cache_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_cache(self, cache: dict[str, Any]) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self._cache_path.open("w", encoding="utf-8") as handle:
            json.dump(cache, handle, indent=2, sort_keys=True)

    def fetch(self, team_name: str, as_of: date, n: int = 10) -> dict[str, Any] | None:
        key = f"{team_name}|{as_of.isoformat()}|{n}"
        cache = self._load_cache()
        cached = cache.get(key)
        if isinstance(cached, dict):
            try:
                fetched_at = datetime.fromisoformat(str(cached["fetched_at"]))
                if datetime.now(timezone.utc) - fetched_at < _CACHE_TTL:
                    return cached.get("stats")
            except (KeyError, TypeError, ValueError):
                pass

        response = requests.get(
            f"{_BASE_URL}/{_slug(team_name)}.tsv",
            headers={"User-Agent": "alpha-terminal/1.5"},
            timeout=15,
        )
        response.raise_for_status()
        stats = parse_recent_form_tsv(response.text, as_of=as_of, n=n)
        cache[key] = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "stats": stats,
        }
        self._save_cache(cache)
        return stats
