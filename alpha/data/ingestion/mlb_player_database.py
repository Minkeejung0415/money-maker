"""
Local MLB player-stat database helpers.

This module is intentionally network-free. It normalizes CSV-style daily rows,
derives formula stats from raw components, and can export inspectable local
files for future scanner/retraining steps.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Iterable

WAR_ABSENCE_VALUE_SCALE = 20.0
MAX_WAR_ABSENCE_VALUE = 0.50

_LEAGUE_XWOBA = 0.320
_LEAGUE_WRC_PLUS = 100.0
_LEAGUE_XERA = 4.20
_LEAGUE_FIP = 4.20
_LEAGUE_K_BB_RATE = 0.14
_OPTIMAL_STARTER_REST_DAYS = 5.0

_LINEUP_SLOT_WEIGHTS = {
    1: 0.25,
    2: 0.30,
    3: 0.25,
    4: 0.25,
    5: 0.15,
    6: 0.08,
    7: 0.03,
    8: 0.00,
    9: 0.00,
}

_UNSUPPORTED_ABSENCE_STAT_COLUMNS = (
    "era",
    "ERA",
    "ba",
    "BA",
    "avg",
    "AVG",
    "batting_average",
    "home_runs",
    "hr",
    "rbi",
    "wins",
    "losses",
)


def _text(row: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return default


def _float(row: dict, *keys: str, default: float = 0.0) -> float:
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _has_value(row: dict, *keys: str) -> bool:
    return any(row.get(key) not in (None, "") for key in keys)


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if denominator else default


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def parse_innings(value: object) -> float:
    """Parse baseball innings notation where .1 means one out and .2 means two outs."""
    if value in (None, ""):
        return 0.0
    text = str(value).strip()
    if "." not in text:
        try:
            return float(text)
        except ValueError:
            return 0.0
    whole, frac = text.split(".", 1)
    try:
        innings = float(int(whole or 0))
    except ValueError:
        return 0.0
    outs = {"0": 0.0, "1": 1.0 / 3.0, "2": 2.0 / 3.0}.get(frac[:1])
    if outs is None:
        try:
            return float(text)
        except ValueError:
            return 0.0
    return innings + outs


def normalize_batter_rows(rows: Iterable[dict], *, source: str = "", as_of: str | None = None) -> list[dict]:
    normalized: list[dict] = []
    for row in rows:
        normalized.append({
            "player_id": _text(row, "player_id", "id"),
            "player_name": _text(row, "player_name", "player", "name"),
            "team": _text(row, "team", "team_abbr"),
            "game_date": _text(row, "game_date", "date", default=as_of or ""),
            "pa": _float(row, "pa", "PA", "plate_appearances"),
            "war": _float(row, "war", "WAR", "fwar", "bwar", "total_war", default=_float(row, "batting_war", "offensive_war", "oWAR")),
            "xwoba": _float(row, "xwoba", "xwOBA"),
            "wrc_plus": _float(row, "wrc_plus", "wRC+", "wrc+"),
            "platoon_wrc_plus": _float(row, "platoon_wrc_plus", "platoon_wRC+", "split_wrc_plus", "split_wRC+"),
            "lineup_spot": _float(row, "lineup_spot", "lineup_slot", "batting_order", "order"),
            "vs_opponent_wrc_plus": _float(row, "vs_opponent_wrc_plus", "vs_opponent_wRC+", "vs_team_wrc_plus", "vs_team_wRC+"),
            "vs_opponent_xwoba": _float(row, "vs_opponent_xwoba", "vs_opponent_xwOBA", "vs_team_xwoba", "vs_team_xwOBA"),
            "platoon_adjustment": _float(row, "platoon_adjustment"),
            "recent_health_rest_adjustment": _float(row, "recent_health_rest_adjustment"),
            "recent_player_performance": _float(row, "recent_player_performance", "recent_performance_adjustment"),
            "lineup_slot_weight": _float(row, "lineup_slot_weight"),
            "park_weather_adjustment": _float(row, "park_weather_adjustment"),
            "team_matchup_adjustment": _float(row, "team_matchup_adjustment", "vs_team_adjustment"),
            "source": source or _text(row, "source"),
            "as_of": as_of or _text(row, "as_of"),
        })
    return normalized


def normalize_pitcher_rows(rows: Iterable[dict], *, source: str = "", as_of: str | None = None) -> list[dict]:
    normalized: list[dict] = []
    for row in rows:
        normalized.append({
            "player_id": _text(row, "player_id", "id"),
            "player_name": _text(row, "player_name", "player", "name"),
            "team": _text(row, "team", "team_abbr"),
            "game_date": _text(row, "game_date", "date", default=as_of or ""),
            "role": _text(row, "role", "player_type", "position"),
            "ip": _float(row, "ip", "IP", "innings", "innings_pitched"),
            "war": _float(row, "war", "WAR", "fwar", "bwar", "total_war", default=_float(row, "pitching_war", "pWAR")),
            "xera": _float(row, "xera", "xERA"),
            "fip": _float(row, "fip", "FIP"),
            "k_bb_pct": _float(row, "k_bb_pct", "k_minus_bb_pct", "k-bb%", "K-BB%"),
            "rest_days": _float(row, "rest_days"),
            "pitch_count_workload": _float(row, "pitch_count_workload", "recent_pitch_count", "last_pitch_count"),
            "velocity_change": _float(row, "velocity_change", "velo_change"),
            "projected_innings": _float(row, "projected_innings", "projected_ip"),
            "vs_opponent_fip": _float(row, "vs_opponent_fip", "vs_team_fip"),
            "recent_health_rest_adjustment": _float(row, "recent_health_rest_adjustment"),
            "recent_player_performance": _float(row, "recent_player_performance", "recent_performance_adjustment"),
            "park_weather_adjustment": _float(row, "park_weather_adjustment"),
            "starter_bullpen_role_adjustment": _float(row, "starter_bullpen_role_adjustment", "role_adjustment"),
            "team_matchup_adjustment": _float(row, "team_matchup_adjustment", "vs_team_adjustment"),
            "source": source or _text(row, "source"),
            "as_of": as_of or _text(row, "as_of"),
        })
    return normalized


def normalize_bullpen_rows(rows: Iterable[dict], *, source: str = "", as_of: str | None = None) -> list[dict]:
    normalized: list[dict] = []
    for row in rows:
        normalized.append({
            "team": _text(row, "team", "team_abbr"),
            "game_date": _text(row, "game_date", "date", default=as_of or ""),
            "xera": _float(row, "xera", "xERA"),
            "fip": _float(row, "fip", "FIP"),
            "k_bb_pct": _float(row, "k_bb_pct", "k_minus_bb_pct", "k-bb%", "K-BB%"),
            "pitch_count_workload": _float(row, "pitch_count_workload", "recent_pitch_count", "last_pitch_count", "pitches", "pit"),
            "rest_days": _float(row, "rest_days"),
            "velocity_change": _float(row, "velocity_change", "velo_change"),
            "projected_innings": _float(row, "projected_innings", "projected_ip"),
            "starter_bullpen_role_adjustment": _float(row, "starter_bullpen_role_adjustment", "role_adjustment"),
            "team_matchup_adjustment": _float(row, "team_matchup_adjustment", "vs_team_adjustment"),
            "source": source or _text(row, "source"),
            "as_of": as_of or _text(row, "as_of"),
        })
    return normalized


def normalize_lineup_rows(rows: Iterable[dict], *, source: str = "", as_of: str | None = None) -> list[dict]:
    normalized: list[dict] = []
    for row in rows:
        normalized.append({
            "game_id": _text(row, "game_id", "event_id"),
            "player_id": _text(row, "player_id", "id", "mlbam_id"),
            "player_name": _text(row, "player_name", "player", "name"),
            "team": _text(row, "team", "team_abbr"),
            "side": _text(row, "side", "home_away"),
            "game_date": _text(row, "game_date", "date", default=as_of or ""),
            "batting_order": _float(row, "batting_order", "order", default=99.0),
            "confirmed": bool(str(row.get("confirmed", "")).lower() in {"1", "true", "yes", "y"}),
            "bats": _text(row, "bats", "bat_side"),
            "source": source or _text(row, "source"),
            "as_of": as_of or _text(row, "as_of"),
        })
    return normalized


def normalize_absence_rows(rows: Iterable[dict], *, source: str = "", as_of: str | None = None) -> list[dict]:
    normalized: list[dict] = []
    for row in rows:
        _raise_on_unsupported_absence_stats(row)
        explicit_absence_value = _has_value(row, "absence_value", "player_value", "batting_value")
        explicit_today_value = _has_value(row, "today_player_value")
        batting_war = _float(row, "batting_war", "offensive_war", "oWAR")
        pitching_war = _float(row, "pitching_war", "pWAR")
        total_war = _float(row, "war", "WAR", "fwar", "bwar", "total_war", default=batting_war + pitching_war)
        today_player_value = (
            _float(row, "today_player_value")
            if explicit_today_value
            else _derive_today_player_value(row, total_war)
        )
        absence_value = (
            _float(row, "absence_value", "player_value", "batting_value")
            if explicit_absence_value
            else _war_to_absence_value(today_player_value)
        )
        normalized.append({
            "game_id": _text(row, "game_id", "event_id"),
            "player_id": _text(row, "player_id", "id", "mlbam_id"),
            "player_name": _text(row, "player_name", "player", "name"),
            "team": _text(row, "team", "team_abbr"),
            "side": _text(row, "side", "home_away"),
            "game_date": _text(row, "game_date", "date", default=as_of or ""),
            "reason": _text(row, "reason", "status"),
            "absence_value": absence_value,
            "war": total_war,
            "batting_war": batting_war,
            "pitching_war": pitching_war,
            "today_player_value": today_player_value,
            "today_player_value_source": (
                "explicit" if explicit_today_value else ("components" if today_player_value else "")
            ),
            "absence_value_source": "explicit" if explicit_absence_value else ("today_player_value" if today_player_value else ""),
            "source": source or _text(row, "source"),
            "as_of": as_of or _text(row, "as_of"),
        })
    return normalized


def _raise_on_unsupported_absence_stats(row: dict) -> None:
    unsupported = [key for key in _UNSUPPORTED_ABSENCE_STAT_COLUMNS if key in row and row.get(key) not in (None, "")]
    if unsupported:
        joined = ", ".join(sorted(unsupported))
        raise ValueError(
            "unsupported absence stat column(s): "
            f"{joined}. Use derived value inputs such as WAR, xwOBA, wRC+, platoon splits, "
            "xERA, FIP, K-BB%, workload/rest, and explicit context adjustments."
        )


def _war_to_absence_value(war: float) -> float:
    if war <= 0.0:
        return 0.0
    return min(MAX_WAR_ABSENCE_VALUE, war / WAR_ABSENCE_VALUE_SCALE)


def _derive_today_player_value(row: dict, total_war: float) -> float:
    role = _text(row, "role", "player_type", "position").lower()
    value = total_war
    if role in {"p", "sp", "rp", "pitcher", "starter", "reliever"}:
        value += _pitcher_today_adjustment(row)
    else:
        value += _hitter_today_adjustment(row)
    value += _common_today_adjustment(row)
    return max(0.0, value)


def _common_today_adjustment(row: dict) -> float:
    adjustment = 0.0
    for key in (
        "platoon_adjustment",
        "recent_health_rest_adjustment",
        "recent_player_performance",
        "recent_performance_adjustment",
        "lineup_slot_weight",
        "park_weather_adjustment",
        "starter_bullpen_role_adjustment",
        "role_adjustment",
        "team_matchup_adjustment",
        "vs_team_adjustment",
    ):
        adjustment += _float(row, key)
    return adjustment


def _hitter_today_adjustment(row: dict) -> float:
    adjustment = 0.0
    xwoba = _float(row, "xwoba", "xwOBA")
    wrc_plus = _float(row, "wrc_plus", "wRC+", "wrc+")
    platoon_wrc_plus = _float(row, "platoon_wrc_plus", "platoon_wRC+", "split_wrc_plus", "split_wRC+")
    vs_wrc_plus = _float(row, "vs_opponent_wrc_plus", "vs_opponent_wRC+", "vs_team_wrc_plus", "vs_team_wRC+")
    vs_xwoba = _float(row, "vs_opponent_xwoba", "vs_opponent_xwOBA", "vs_team_xwoba", "vs_team_xwOBA")
    if xwoba > 0.0:
        adjustment += (xwoba - _LEAGUE_XWOBA) * 8.0
    if wrc_plus > 0.0:
        adjustment += (wrc_plus - _LEAGUE_WRC_PLUS) / 120.0
    if platoon_wrc_plus > 0.0:
        adjustment += (platoon_wrc_plus - _LEAGUE_WRC_PLUS) / 160.0
    if vs_wrc_plus > 0.0:
        adjustment += (vs_wrc_plus - _LEAGUE_WRC_PLUS) / 200.0
    if vs_xwoba > 0.0:
        adjustment += (vs_xwoba - _LEAGUE_XWOBA) * 5.0
    if not _has_value(row, "lineup_slot_weight"):
        adjustment += _lineup_slot_adjustment(_float(row, "lineup_spot", "lineup_slot", "batting_order", "order"))
    return adjustment


def _pitcher_today_adjustment(row: dict) -> float:
    adjustment = 0.0
    if _has_value(row, "xera", "xERA"):
        adjustment += (_LEAGUE_XERA - _float(row, "xera", "xERA")) * 0.30
    if _has_value(row, "fip", "FIP"):
        adjustment += (_LEAGUE_FIP - _float(row, "fip", "FIP")) * 0.25
    if _has_value(row, "k_bb_pct", "k_minus_bb_pct", "k-bb%", "K-BB%"):
        adjustment += (_float(row, "k_bb_pct", "k_minus_bb_pct", "k-bb%", "K-BB%") - _LEAGUE_K_BB_RATE) * 5.0
    if _has_value(row, "rest_days"):
        adjustment += max(-0.30, min(0.20, (_float(row, "rest_days") - _OPTIMAL_STARTER_REST_DAYS) * 0.05))
    if _has_value(row, "pitch_count_workload", "recent_pitch_count", "last_pitch_count"):
        adjustment -= max(0.0, _float(row, "pitch_count_workload", "recent_pitch_count", "last_pitch_count") - 95.0) / 200.0
    if _has_value(row, "velocity_change", "velo_change"):
        adjustment += _float(row, "velocity_change", "velo_change") * 0.15
    if _has_value(row, "projected_innings", "projected_ip"):
        adjustment += (_float(row, "projected_innings", "projected_ip") - 5.0) * 0.15
    if _has_value(row, "vs_opponent_fip", "vs_team_fip"):
        adjustment += (_LEAGUE_FIP - _float(row, "vs_opponent_fip", "vs_team_fip")) * 0.15
    return adjustment


def _lineup_slot_adjustment(slot: float) -> float:
    if slot <= 0.0:
        return 0.0
    return _LINEUP_SLOT_WEIGHTS.get(int(slot), 0.0)


def _pitcher_quality_from_advanced(*, xera: float, fip: float, k_bb_pct: float) -> float:
    run_prevention_inputs = [value for value in (xera, fip) if value > 0.0]
    run_prevention = _mean([max(0.0, min(1.0, (6.5 - value) / 5.0)) for value in run_prevention_inputs])
    command = max(0.0, min(1.0, k_bb_pct / 0.30)) if k_bb_pct > 0.0 else 0.0
    if run_prevention_inputs and k_bb_pct > 0.0:
        return (0.70 * run_prevention) + (0.30 * command)
    return run_prevention or command


def append_rows(existing: Iterable[dict], new_rows: Iterable[dict]) -> list[dict]:
    rows = list(existing) + list(new_rows)
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for row in sorted(rows, key=lambda r: (
        str(r.get("game_date", "")),
        str(r.get("team", "")),
        str(r.get("player_id") or r.get("player_name", "")),
        str(r.get("source", "")),
    )):
        key = tuple((k, row.get(k)) for k in sorted(row))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(row))
    return deduped


def _group_player_rows(rows: Iterable[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        key = str(row.get("player_id") or row.get("player_name") or "").strip()
        if key:
            grouped[key].append(row)
    return grouped


def derive_batter_stats(rows: Iterable[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for key, player_rows in _group_player_rows(rows).items():
        latest = player_rows[-1]
        war = _mean([float(row.get("war") or 0.0) for row in player_rows])
        value = _mean([_derive_today_player_value(row, float(row.get("war") or 0.0)) for row in player_rows])
        result[key] = {
            "player_name": latest.get("player_name", key),
            "team": latest.get("team", ""),
            "games": len({row.get("game_date") for row in player_rows if row.get("game_date")}),
            "war": war,
            "pa": _mean([float(row.get("pa") or 0.0) for row in player_rows]),
            "xwoba": _mean([float(row.get("xwoba") or 0.0) for row in player_rows]),
            "wrc_plus": _mean([float(row.get("wrc_plus") or 0.0) for row in player_rows]),
            "platoon_wrc_plus": _mean([float(row.get("platoon_wrc_plus") or 0.0) for row in player_rows]),
            "lineup_spot": float(latest.get("lineup_spot") or 0.0),
            "vs_opponent_wrc_plus": _mean([float(row.get("vs_opponent_wrc_plus") or 0.0) for row in player_rows]),
            "vs_opponent_xwoba": _mean([float(row.get("vs_opponent_xwoba") or 0.0) for row in player_rows]),
            "today_player_value": value,
            "batting_value": value,
        }
    return result


def derive_pitcher_stats(rows: Iterable[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for key, player_rows in _group_player_rows(rows).items():
        latest = player_rows[-1]
        xera = _mean([float(row.get("xera") or 0.0) for row in player_rows])
        fip = _mean([float(row.get("fip") or 0.0) for row in player_rows])
        k_bb_pct = _mean([float(row.get("k_bb_pct") or 0.0) for row in player_rows])
        starter_quality = _pitcher_quality_from_advanced(xera=xera, fip=fip, k_bb_pct=k_bb_pct)
        result[key] = {
            "player_name": latest.get("player_name", key),
            "team": latest.get("team", ""),
            "games": len({row.get("game_date") for row in player_rows if row.get("game_date")}),
            "role": latest.get("role", ""),
            "war": _mean([float(row.get("war") or 0.0) for row in player_rows]),
            "ip": _mean([float(row.get("ip") or 0.0) for row in player_rows]),
            "xera": xera,
            "fip": fip,
            "k_bb_pct": k_bb_pct,
            "rest_days": float(latest.get("rest_days") or 0.0),
            "pitch_count_workload": float(latest.get("pitch_count_workload") or 0.0),
            "velocity_change": float(latest.get("velocity_change") or 0.0),
            "projected_innings": float(latest.get("projected_innings") or 0.0),
            "vs_opponent_fip": _mean([float(row.get("vs_opponent_fip") or 0.0) for row in player_rows]),
            "starter_quality": starter_quality,
            "pitches": float(latest.get("pitch_count_workload") or 0.0),
        }
    return result


def filter_rows_through(rows: Iterable[dict], target_date: str, *, window_days: int | None = None) -> list[dict]:
    target = date.fromisoformat(target_date)
    start = date.min if window_days is None else target - timedelta(days=window_days - 1)
    filtered: list[dict] = []
    for row in rows:
        row_date_text = str(row.get("game_date") or "")
        if not row_date_text:
            continue
        row_date = date.fromisoformat(row_date_text[:10])
        if start <= row_date <= target:
            filtered.append(dict(row))
    return filtered


def build_player_stat_snapshot(
    *,
    batter_rows: Iterable[dict] = (),
    pitcher_rows: Iterable[dict] = (),
    target_date: str,
    windows: tuple[int, ...] = (7, 14, 30),
) -> dict:
    batters = list(batter_rows)
    pitchers = list(pitcher_rows)
    snapshot = {
        "target_date": target_date,
        "season": {
            "batters": derive_batter_stats(filter_rows_through(batters, target_date)),
            "pitchers": derive_pitcher_stats(filter_rows_through(pitchers, target_date)),
        },
        "rolling": {},
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    for window in windows:
        snapshot["rolling"][str(window)] = {
            "batters": derive_batter_stats(filter_rows_through(batters, target_date, window_days=window)),
            "pitchers": derive_pitcher_stats(filter_rows_through(pitchers, target_date, window_days=window)),
        }
    return snapshot


def write_rows_csv(path: str | Path, rows: Iterable[dict]) -> Path:
    rows = list(rows)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output


def read_rows_csv(path: str | Path) -> list[dict]:
    input_path = Path(path)
    if not input_path.exists():
        return []
    with input_path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_json(path: str | Path, default: object | None = None) -> object:
    input_path = Path(path)
    if not input_path.exists():
        return {} if default is None else default
    return json.loads(input_path.read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: object) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output


def empty_database_snapshot(*, schema_version: str = "mlb-player-db-v2.3") -> dict:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    return {
        "schema_version": schema_version,
        "created_at": now,
        "updated_at": now,
        "components": {
            "batters": [],
            "pitchers": [],
            "bullpen": [],
            "lineups": [],
            "absences": [],
        },
        "sources": {},
    }


def load_database_snapshot(path: str | Path) -> dict:
    payload = read_json(path, default=None)
    if not payload:
        return empty_database_snapshot()
    if not isinstance(payload, dict):
        raise ValueError("MLB player database snapshot must be a JSON object")
    payload.setdefault("components", {})
    for name in ("batters", "pitchers", "bullpen", "lineups", "absences"):
        payload["components"].setdefault(name, [])
    payload.setdefault("sources", {})
    return payload


def update_database_snapshot(
    snapshot: dict,
    *,
    batters: Iterable[dict] = (),
    pitchers: Iterable[dict] = (),
    bullpen: Iterable[dict] = (),
    lineups: Iterable[dict] = (),
    absences: Iterable[dict] = (),
    source: str,
    import_date: str,
) -> dict:
    result = load_database_snapshot_from_object(snapshot)
    components = result["components"]
    components["batters"] = append_rows(components.get("batters", []), batters)
    components["pitchers"] = append_rows(components.get("pitchers", []), pitchers)
    components["bullpen"] = append_rows(components.get("bullpen", []), bullpen)
    components["lineups"] = append_rows(components.get("lineups", []), lineups)
    components["absences"] = append_rows(components.get("absences", []), absences)
    result["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    result["sources"][source] = {
        "last_import_date": import_date,
        "updated_at": result["updated_at"],
    }
    return result


def load_database_snapshot_from_object(snapshot: dict) -> dict:
    if not snapshot:
        return empty_database_snapshot()
    result = dict(snapshot)
    result["components"] = dict(result.get("components") or {})
    for name in ("batters", "pitchers", "bullpen", "lineups", "absences"):
        result["components"][name] = list(result["components"].get(name) or [])
    result["sources"] = dict(result.get("sources") or {})
    return result


def write_rows_parquet_or_csv(path: str | Path, rows: Iterable[dict]) -> Path:
    rows = list(rows)
    output = Path(path)
    try:
        import pandas as pd  # noqa: PLC0415

        output.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(output, index=False)
        return output
    except Exception:
        fallback = output.with_suffix(".csv")
        return write_rows_csv(fallback, rows)
