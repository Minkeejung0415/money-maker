"""Build historical as-of MLB starter snapshots from completed game feeds."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

import requests

LEAGUE_RA9 = 4.50
DEFAULT_PROJECTED_INNINGS = 5.30
FIP_CONSTANT = 3.20


@dataclass
class PitcherState:
    starts: int = 0
    games: int = 0
    outs: int = 0
    strikeouts: int = 0
    walks: int = 0
    hbp: int = 0
    home_runs: int = 0
    batters_faced: int = 0
    last_date: str | None = None
    previous_pitch_count: float = 0.0
    recent_start_outs: list[int] = field(default_factory=list)


def fetch_game_feed(game_id: str, *, cache_dir: Path | None = None, timeout: int = 20) -> dict[str, Any]:
    """Fetch an MLB StatsAPI live feed, with an optional local raw JSON cache."""
    cache_path = cache_dir / f"{game_id}.json" if cache_dir else None
    if cache_path and cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live"
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def extract_starter_lines(feed: dict[str, Any], game: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract actual home/away starting pitcher lines from a completed game feed."""
    lines: list[dict[str, Any]] = []
    boxscore = ((feed.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}
    for side in ("home", "away"):
        team_box = boxscore.get(side) or {}
        pitcher_ids = team_box.get("pitchers") or []
        if not pitcher_ids:
            continue
        starter_id = str(pitcher_ids[0])
        player = (team_box.get("players") or {}).get(f"ID{starter_id}") or {}
        pitching = (player.get("stats") or {}).get("pitching") or {}
        if not pitching:
            continue
        lines.append(
            {
                "game_id": str(game.get("game_id") or feed.get("gamePk") or ""),
                "game_date": str(game.get("date") or "")[:10],
                "side": side,
                "team": str(game.get(f"{side}_team") or (team_box.get("team") or {}).get("name") or ""),
                "opponent": str(game.get("away_team" if side == "home" else "home_team") or ""),
                "pitcher_id": starter_id,
                "pitcher_name": str((player.get("person") or {}).get("fullName") or ""),
                "outs": int(_float(pitching.get("outs"), _parse_ip_to_outs(pitching.get("inningsPitched")))),
                "innings_pitched": _parse_ip(pitching.get("inningsPitched")),
                "strikeouts": int(_float(pitching.get("strikeOuts"), 0.0)),
                "walks": int(_float(pitching.get("baseOnBalls"), 0.0)),
                "hbp": int(_float(pitching.get("hitByPitch", pitching.get("hitBatsmen")), 0.0)),
                "home_runs": int(_float(pitching.get("homeRuns"), 0.0)),
                "batters_faced": int(_float(pitching.get("battersFaced"), 0.0)),
                "earned_runs": int(_float(pitching.get("earnedRuns"), 0.0)),
                "runs": int(_float(pitching.get("runs"), 0.0)),
                "pitch_count": float(_float(pitching.get("numberOfPitches", pitching.get("pitchesThrown")), 0.0)),
            }
        )
    return lines


def build_snapshot_payload(games: list[dict[str, Any]], *, feed_cache_dir: Path | None = None) -> dict[str, Any]:
    """Fetch game feeds and return a snapshot payload keyed by game id and side."""
    lines: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for game in sorted(games, key=lambda g: (str(g.get("date", "")), str(g.get("game_id", "")))):
        game_id = str(game.get("game_id") or "")
        if not game_id:
            continue
        try:
            feed = fetch_game_feed(game_id, cache_dir=feed_cache_dir)
            lines.extend(extract_starter_lines(feed, game))
        except Exception as exc:  # pragma: no cover - network failure path
            failures.append({"game_id": game_id, "error": str(exc)})
    snapshots = build_snapshots_from_lines(lines)
    return {
        "schema_version": "mlb-starter-snapshots-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "MLB StatsAPI live feed boxscore pitching lines",
        "coverage": {
            "games_requested": len(games),
            "games_with_snapshots": len(snapshots),
            "starter_lines": len(lines),
            "failures": len(failures),
        },
        "unavailable_fields": {
            "xera": "not present in StatsAPI game boxscore; left null",
            "velocity_change": "requires pitch-level Statcast history; left null",
            "war_per_ip": "estimated from prior FIP run value, not official WAR",
        },
        "failures": failures[:100],
        "snapshots": snapshots,
    }


def build_snapshots_from_lines(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    states: dict[str, PitcherState] = {}
    snapshots: dict[str, dict[str, Any]] = {}
    for line in sorted(lines, key=lambda x: (str(x.get("game_date", "")), str(x.get("game_id", "")), str(x.get("side", "")))):
        pitcher_id = str(line.get("pitcher_id") or "")
        if not pitcher_id:
            continue
        state = states.setdefault(pitcher_id, PitcherState())
        snapshot = _snapshot_from_state(state, line)
        snapshots.setdefault(str(line["game_id"]), {})[str(line["side"])] = snapshot
        _update_state(state, line)
    return snapshots


def starter_snapshot_to_training_features(snapshot: dict[str, Any] | None) -> dict[str, float]:
    """Map a snapshot into the starter fields used by MLB player training."""
    if not snapshot:
        return {}
    skill = _float(snapshot.get("starter_skill_ra9"), LEAGUE_RA9)
    projected_ip = _float(snapshot.get("projected_innings"), DEFAULT_PROJECTED_INNINGS)
    return {
        "sp_quality": max(0.0, min(1.0, (8.0 - skill) / 6.0)),
        "sp_workload": _float(snapshot.get("previous_pitch_count"), 90.0),
        "sp_rest_days": _float(snapshot.get("rest_days"), 5.0),
        "sp_projected_innings": projected_ip,
        "starter_skill_ra9": skill,
        "starter_run_value": _float(snapshot.get("starter_run_value"), 0.0),
        "sp_missing": _float(snapshot.get("missing_flag"), 1.0),
    }


def _snapshot_from_state(state: PitcherState, line: dict[str, Any]) -> dict[str, Any]:
    prior_ip = state.outs / 3.0
    fip = _derive_fip(state)
    k_bb_pct = ((state.strikeouts - state.walks) / state.batters_faced) if state.batters_faced > 0 else 0.0
    projected_ip = (
        sum(state.recent_start_outs[-5:]) / len(state.recent_start_outs[-5:]) / 3.0
        if state.recent_start_outs
        else DEFAULT_PROJECTED_INNINGS
    )
    rest_days = _rest_days(state.last_date, str(line.get("game_date") or ""))
    skill_ra9 = max(2.5, min(7.0, fip))
    starter_run_value = (projected_ip / 9.0) * (LEAGUE_RA9 - skill_ra9)
    confidence = max(0.0, min(1.0, state.starts / 5.0))
    return {
        "game_id": str(line.get("game_id") or ""),
        "game_date": str(line.get("game_date") or ""),
        "side": str(line.get("side") or ""),
        "team": str(line.get("team") or ""),
        "opponent": str(line.get("opponent") or ""),
        "pitcher_id": str(line.get("pitcher_id") or ""),
        "pitcher_name": str(line.get("pitcher_name") or ""),
        "prior_starts": state.starts,
        "prior_games": state.games,
        "prior_ip": prior_ip,
        "fip": fip,
        "xera": None,
        "k_bb_pct": k_bb_pct,
        "war_per_ip": (LEAGUE_RA9 - skill_ra9) / 90.0,
        "projected_innings": max(1.0, min(8.0, projected_ip)),
        "rest_days": rest_days,
        "previous_pitch_count": state.previous_pitch_count,
        "velocity_change": None,
        "starter_skill_ra9": skill_ra9,
        "starter_run_value": starter_run_value,
        "missing_flag": float(state.starts == 0),
        "source_confidence": confidence,
    }


def _update_state(state: PitcherState, line: dict[str, Any]) -> None:
    outs = int(_float(line.get("outs"), 0.0))
    state.starts += 1
    state.games += 1
    state.outs += outs
    state.strikeouts += int(_float(line.get("strikeouts"), 0.0))
    state.walks += int(_float(line.get("walks"), 0.0))
    state.hbp += int(_float(line.get("hbp"), 0.0))
    state.home_runs += int(_float(line.get("home_runs"), 0.0))
    state.batters_faced += int(_float(line.get("batters_faced"), 0.0))
    state.last_date = str(line.get("game_date") or "")
    state.previous_pitch_count = _float(line.get("pitch_count"), 0.0)
    if outs > 0:
        state.recent_start_outs.append(outs)


def _derive_fip(state: PitcherState) -> float:
    ip = state.outs / 3.0
    if ip <= 0:
        return LEAGUE_RA9
    fip = ((13.0 * state.home_runs) + (3.0 * (state.walks + state.hbp)) - (2.0 * state.strikeouts)) / ip + FIP_CONSTANT
    return max(1.5, min(8.5, fip))


def _parse_ip(value: Any) -> float:
    return _parse_ip_to_outs(value) / 3.0


def _parse_ip_to_outs(value: Any) -> int:
    if value is None or value == "":
        return 0
    text = str(value)
    if "." not in text:
        return int(float(text) * 3)
    whole, frac = text.split(".", 1)
    return int(whole or 0) * 3 + int(frac[:1] or 0)


def _rest_days(last_date: str | None, game_date: str) -> float:
    if not last_date or not game_date:
        return 5.0
    try:
        return float(max(0, (date.fromisoformat(game_date) - date.fromisoformat(last_date)).days - 1))
    except ValueError:
        return 5.0


def _float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default
