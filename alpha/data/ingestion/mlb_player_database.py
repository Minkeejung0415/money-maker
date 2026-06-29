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


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if denominator else default


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
            "hits": _float(row, "hits", "h"),
            "at_bats": _float(row, "at_bats", "ab"),
            "walks": _float(row, "walks", "bb"),
            "hbp": _float(row, "hbp"),
            "sac_flies": _float(row, "sac_flies", "sf"),
            "total_bases": _float(row, "total_bases", "tb"),
            "home_runs": _float(row, "home_runs", "hr"),
            "rbi": _float(row, "rbi"),
            "plate_appearances": _float(row, "plate_appearances", "pa"),
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
            "earned_runs": _float(row, "earned_runs", "er"),
            "innings_pitched": parse_innings(row.get("innings_pitched", row.get("ip"))),
            "runs": _float(row, "runs", "r"),
            "hits_allowed": _float(row, "hits_allowed", "h"),
            "walks": _float(row, "walks", "bb"),
            "strikeouts": _float(row, "strikeouts", "so", "k"),
            "home_runs_allowed": _float(row, "home_runs_allowed", "hr"),
            "pitches": _float(row, "pitches", "pit"),
            "batters_faced": _float(row, "batters_faced", "bf"),
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
            "innings_pitched": parse_innings(row.get("innings_pitched", row.get("ip"))),
            "earned_runs": _float(row, "earned_runs", "er"),
            "walks": _float(row, "walks", "bb"),
            "strikeouts": _float(row, "strikeouts", "so", "k"),
            "home_runs_allowed": _float(row, "home_runs_allowed", "hr"),
            "pitches": _float(row, "pitches", "pit"),
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
        normalized.append({
            "game_id": _text(row, "game_id", "event_id"),
            "player_id": _text(row, "player_id", "id", "mlbam_id"),
            "player_name": _text(row, "player_name", "player", "name"),
            "team": _text(row, "team", "team_abbr"),
            "side": _text(row, "side", "home_away"),
            "game_date": _text(row, "game_date", "date", default=as_of or ""),
            "reason": _text(row, "reason", "status"),
            "absence_value": _float(row, "absence_value", "player_value", "batting_value"),
            "source": source or _text(row, "source"),
            "as_of": as_of or _text(row, "as_of"),
        })
    return normalized


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
        totals = defaultdict(float)
        for row in player_rows:
            for field in ("hits", "at_bats", "walks", "hbp", "sac_flies", "total_bases", "home_runs", "rbi", "plate_appearances"):
                totals[field] += float(row.get(field) or 0.0)
        obp_den = totals["at_bats"] + totals["walks"] + totals["hbp"] + totals["sac_flies"]
        avg = _safe_div(totals["hits"], totals["at_bats"])
        obp = _safe_div(totals["hits"] + totals["walks"] + totals["hbp"], obp_den)
        slg = _safe_div(totals["total_bases"], totals["at_bats"])
        pa = totals["plate_appearances"] or obp_den
        result[key] = {
            "player_name": player_rows[-1].get("player_name", key),
            "team": player_rows[-1].get("team", ""),
            "games": len({row.get("game_date") for row in player_rows if row.get("game_date")}),
            "hits": totals["hits"],
            "at_bats": totals["at_bats"],
            "avg": avg,
            "obp": obp,
            "slg": slg,
            "ops": obp + slg,
            "hr_rate": _safe_div(totals["home_runs"], pa),
            "rbi_per_pa": _safe_div(totals["rbi"], pa),
            "batting_value": obp + slg,
        }
    return result


def derive_pitcher_stats(rows: Iterable[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for key, player_rows in _group_player_rows(rows).items():
        totals = defaultdict(float)
        for row in player_rows:
            for field in ("earned_runs", "innings_pitched", "runs", "hits_allowed", "walks", "strikeouts", "home_runs_allowed", "pitches", "batters_faced"):
                totals[field] += float(row.get(field) or 0.0)
        ip = totals["innings_pitched"]
        era = _safe_div(totals["earned_runs"] * 9.0, ip)
        whip = _safe_div(totals["walks"] + totals["hits_allowed"], ip)
        result[key] = {
            "player_name": player_rows[-1].get("player_name", key),
            "team": player_rows[-1].get("team", ""),
            "games": len({row.get("game_date") for row in player_rows if row.get("game_date")}),
            "innings_pitched": ip,
            "era": era,
            "whip": whip,
            "k_per9": _safe_div(totals["strikeouts"] * 9.0, ip),
            "bb_per9": _safe_div(totals["walks"] * 9.0, ip),
            "hr_per9": _safe_div(totals["home_runs_allowed"] * 9.0, ip),
            "starter_quality": max(0.0, min(1.0, (6.5 - era) / 5.0)) if ip else 0.0,
            "pitches": totals["pitches"],
            "batters_faced": totals["batters_faced"],
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
