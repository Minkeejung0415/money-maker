"""Recent World Cup tactical profiles from ESPN soccer match summaries."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

import requests

_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
_CACHE_DIR = Path("data/.wc_cache/espn_tactics")
_DECAY = 0.82
_MIN_MATCHES = 3


@dataclass(frozen=True)
class WCTacticalProfile:
    team: str
    matches: int
    latest_match: str
    formation: str
    possession: float
    pass_completion: float
    long_ball_rate: float
    cross_rate: float
    shots_for: float
    shots_allowed: float
    shot_on_target_rate: float
    corners_for: float
    corners_allowed: float
    pressing_proxy: float
    clearances: float


def _number(stats: dict[str, Any], name: str) -> float:
    try:
        return float(stats.get(name, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _fraction(stats: dict[str, Any], name: str) -> float:
    value = _number(stats, name)
    return value / 100.0 if value > 1.0 else value


def _team_stats(entry: dict[str, Any]) -> dict[str, float]:
    return {
        str(stat.get("name")): stat.get("displayValue", stat.get("value", 0.0))
        for stat in entry.get("statistics", [])
    }


def parse_tactical_match(summary: dict[str, Any], team_name: str) -> dict[str, Any] | None:
    """Extract one team's tactical metrics with opponent context."""
    teams = summary.get("boxscore", {}).get("teams", [])
    target = next(
        (entry for entry in teams if entry.get("team", {}).get("displayName") == team_name),
        None,
    )
    opponent = next((entry for entry in teams if entry is not target), None)
    if target is None or opponent is None:
        return None
    stats = _team_stats(target)
    opp_stats = _team_stats(opponent)
    required = {"possessionPct", "totalPasses", "totalShots", "wonCorners"}
    if not required <= stats.keys() or not required <= opp_stats.keys():
        return None

    total_passes = max(_number(stats, "totalPasses"), 1.0)
    opp_passes = max(_number(opp_stats, "totalPasses"), 1.0)
    total_shots = max(_number(stats, "totalShots"), 1.0)
    defensive_actions = _number(stats, "totalTackles") + _number(stats, "interceptions")
    formation = ""
    for roster in summary.get("rosters", []):
        if roster.get("team", {}).get("displayName") == team_name:
            formation = str(roster.get("formation") or "")
            break
    return {
        "formation": formation,
        "possession": _fraction(stats, "possessionPct"),
        "pass_completion": _fraction(stats, "passPct"),
        "long_ball_rate": _number(stats, "totalLongBalls") / total_passes,
        "cross_rate": _number(stats, "totalCrosses") / total_passes,
        "shots_for": _number(stats, "totalShots"),
        "shots_allowed": _number(opp_stats, "totalShots"),
        "shot_on_target_rate": _number(stats, "shotsOnTarget") / total_shots,
        "corners_for": _number(stats, "wonCorners"),
        "corners_allowed": _number(opp_stats, "wonCorners"),
        "pressing_proxy": defensive_actions / (opp_passes / 100.0),
        "clearances": _number(stats, "totalClearance"),
    }


def aggregate_tactical_profile(
    team_name: str,
    matches: list[dict[str, Any]],
    *,
    min_matches: int = _MIN_MATCHES,
) -> WCTacticalProfile | None:
    """Exponentially weight parsed match metrics into one tactical profile."""
    usable = [match for match in matches if match.get("metrics")]
    if len(usable) < min_matches:
        return None
    usable.sort(key=lambda item: item["date"])
    weights = [_DECAY ** index for index in range(len(usable) - 1, -1, -1)]
    total_weight = sum(weights)

    def weighted(field: str) -> float:
        return sum(float(item["metrics"][field]) * weight for item, weight in zip(usable, weights)) / total_weight

    formations = [item["metrics"].get("formation", "") for item in usable]
    formation = Counter(value for value in formations if value).most_common(1)
    return WCTacticalProfile(
        team=team_name,
        matches=len(usable),
        latest_match=str(usable[-1]["date"]),
        formation=formation[0][0] if formation else "unknown",
        possession=round(weighted("possession"), 4),
        pass_completion=round(weighted("pass_completion"), 4),
        long_ball_rate=round(weighted("long_ball_rate"), 4),
        cross_rate=round(weighted("cross_rate"), 4),
        shots_for=round(weighted("shots_for"), 3),
        shots_allowed=round(weighted("shots_allowed"), 3),
        shot_on_target_rate=round(weighted("shot_on_target_rate"), 4),
        corners_for=round(weighted("corners_for"), 3),
        corners_allowed=round(weighted("corners_allowed"), 3),
        pressing_proxy=round(weighted("pressing_proxy"), 3),
        clearances=round(weighted("clearances"), 3),
    )


class WCTacticsClient:
    """Resolve teams and build recent tactical profiles with disk caching."""

    def __init__(self, cache_dir: str | Path = _CACHE_DIR) -> None:
        self._cache_dir = Path(cache_dir)

    def _cached_json(self, key: str, url: str, ttl: timedelta | None) -> dict[str, Any]:
        path = self._cache_dir / f"{key}.json"
        if path.exists() and (ttl is None or datetime.now(timezone.utc).timestamp() - path.stat().st_mtime < ttl.total_seconds()):
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        response = requests.get(url, headers={"User-Agent": "alpha-terminal/1.6"}, timeout=20)
        response.raise_for_status()
        data = response.json()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return data

    def resolve_team_ids(self, game_date: date) -> dict[str, str]:
        result = {}
        # ESPN groups events by North American display date while the fixture
        # source uses UTC. Merge adjacent dates so evening Pacific fixtures
        # crossing midnight UTC still resolve.
        for offset in (-1, 0, 1):
            date_key = (game_date + timedelta(days=offset)).strftime("%Y%m%d")
            data = self._cached_json(
                f"scoreboard_{date_key}",
                f"{_BASE}/fifa.world/scoreboard?dates={date_key}",
                timedelta(hours=1),
            )
            for event in data.get("events", []):
                for competitor in event.get("competitions", [{}])[0].get("competitors", []):
                    team = competitor.get("team", {})
                    if team.get("displayName") and team.get("id"):
                        result[str(team["displayName"])] = str(team["id"])
        return result

    def fetch_profile(self, team_name: str, team_id: str, as_of: datetime, n: int = 5) -> WCTacticalProfile | None:
        schedule = self._cached_json(
            f"schedule_{team_id}",
            f"{_BASE}/all/teams/{team_id}/schedule",
            timedelta(hours=6),
        )
        completed = []
        for event in schedule.get("events", []):
            try:
                event_time = datetime.fromisoformat(str(event["date"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            status = event.get("competitions", [{}])[0].get("status", {}).get("type", {})
            if event_time >= as_of or not status.get("completed"):
                continue
            completed.append((event_time, str(event.get("id", ""))))
        completed.sort(reverse=True)
        parsed = []
        for event_time, event_id in completed[:n]:
            if not event_id:
                continue
            summary = self._cached_json(
                f"event_{event_id}", f"{_BASE}/all/summary?event={event_id}", None
            )
            metrics = parse_tactical_match(summary, team_name)
            if metrics:
                parsed.append({"date": event_time.date().isoformat(), "metrics": metrics})
        return aggregate_tactical_profile(team_name, parsed)
