"""Interpret local MLB player database rows into event-level runtime features."""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable

from alpha.data.ingestion.mlb_player_database import (
    build_player_stat_snapshot,
    load_database_snapshot,
    write_json,
)
from alpha.data.ingestion.mlb_live_player_features import _era_to_quality, _normalize_pitcher_name


def build_event_player_features(
    games: Iterable[dict],
    database_snapshot: dict,
    *,
    target_date: str,
    stale_after_days: int = 3,
) -> dict[str, dict]:
    """Return event-id keyed player features from a local MLB database snapshot."""
    components = database_snapshot.get("components") or {}
    games_list = list(games or [])
    stat_snapshot = build_player_stat_snapshot(
        batter_rows=components.get("batters", []),
        pitcher_rows=components.get("pitchers", []),
        target_date=target_date,
        windows=(7, 14, 30),
    )
    season_batters = stat_snapshot["season"]["batters"]
    season_pitchers = stat_snapshot["season"]["pitchers"]
    rolling_batters = stat_snapshot["rolling"].get("30", {}).get("batters", {})
    rolling_pitchers = stat_snapshot["rolling"].get("30", {}).get("pitchers", {})
    bullpen_rows = list(components.get("bullpen", []))
    lineup_rows = list(components.get("lineups", []))
    absence_rows = list(components.get("absences", []))

    result: dict[str, dict] = {}
    for game in games_list:
        event_id = str(game.get("event_id") or game.get("game_id") or "")
        if not event_id:
            continue
        home_team = str(game.get("home_team") or game.get("home_team_name") or "")
        away_team = str(game.get("away_team") or game.get("away_team_name") or "")
        features: dict[str, float | str] = {}
        component_hits = 0
        component_total = 8

        for side, team in (("home", home_team), ("away", away_team)):
            starter = str(game.get(f"{side}_probable_pitcher") or game.get(f"{side}_starter_name") or "")
            sp_features, hit = _starter_features(starter, season_pitchers, rolling_pitchers)
            features.update({f"{side}_{key}": value for key, value in sp_features.items()})
            component_hits += int(hit)

            lineup_features, hit = _lineup_features(
                event_id,
                team,
                lineup_rows,
                season_batters,
                rolling_batters,
            )
            features.update({f"{side}_{key}": value for key, value in lineup_features.items()})
            component_hits += int(hit)

            bullpen_features, hit = _bullpen_features(team, bullpen_rows, target_date)
            features.update({f"{side}_{key}": value for key, value in bullpen_features.items()})
            component_hits += int(hit)

            absence_features, hit = _absence_features(event_id, team, side, absence_rows)
            features.update({f"{side}_{key}": value for key, value in absence_features.items()})
            component_hits += int(hit)

        features.update({
            "sp_quality_diff": float(features["home_sp_quality"]) - float(features["away_sp_quality"]),
            "sp_workload_diff": float(features["home_sp_workload"]) - float(features["away_sp_workload"]),
            "lineup_strength_diff": float(features["home_lineup_strength"]) - float(features["away_lineup_strength"]),
            "top_order_strength_diff": float(features["home_top_order_strength"]) - float(features["away_top_order_strength"]),
            "bullpen_quality_diff": float(features["home_bp_quality"]) - float(features["away_bp_quality"]),
            "bullpen_recent_pitches_diff": float(features["home_bp_recent_pitches"]) - float(features["away_bp_recent_pitches"]),
            "absence_value_diff": float(features["home_absence_value"]) - float(features["away_absence_value"]),
            "lineup_missing_count_total": float(features["home_lineup_missing_count"]) + float(features["away_lineup_missing_count"]),
        })
        missing_flag = any(
            float(features.get(key, 0.0) or 0.0) >= 1.0
            for key in ("home_sp_missing", "away_sp_missing", "home_bp_missing", "away_bp_missing")
        ) or float(features["lineup_missing_count_total"]) > 0.0
        coverage = component_hits / component_total if component_total else 0.0
        last_updated = str(database_snapshot.get("updated_at") or "")
        stale = _is_stale(last_updated, target_date, stale_after_days)
        features.update({
            "player_feature_missing_flag": float(missing_flag),
            "player_component_coverage": coverage,
            "player_source_confidence": max(0.0, min(1.0, coverage - (0.25 if stale else 0.0))),
            "lineup_source_confidence": min(
                float(features["home_lineup_source_confidence"]),
                float(features["away_lineup_source_confidence"]),
            ),
            "player_data_stale_flag": float(stale),
            "player_data_source": "local_player_database",
            "player_data_last_updated": last_updated,
        })
        result[event_id] = features
    return result


def write_event_player_features_file(
    path: str | Path,
    *,
    games: Iterable[dict],
    database_snapshot: dict,
    target_date: str,
) -> Path:
    events = build_event_player_features(games, database_snapshot, target_date=target_date)
    payload = {
        "schema_version": "mlb-player-features-v2.3",
        "target_date": target_date,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "events": events,
    }
    return write_json(path, payload)


def build_features_from_database_file(
    database_path: str | Path,
    output_path: str | Path,
    *,
    games: Iterable[dict],
    target_date: str,
) -> Path:
    snapshot = load_database_snapshot(database_path)
    return write_event_player_features_file(
        output_path,
        games=games,
        database_snapshot=snapshot,
        target_date=target_date,
    )


def _starter_features(starter_name: str, season_pitchers: dict, rolling_pitchers: dict) -> tuple[dict, bool]:
    normalized = _normalize_pitcher_name(starter_name) if starter_name else ""
    stats = _lookup_player_stats(normalized, rolling_pitchers) or _lookup_player_stats(normalized, season_pitchers)
    if not stats:
        return {
            "sp_quality": 0.0,
            "sp_workload": 0.0,
            "sp_rest_days": 0.0,
            "sp_missing": 1.0,
        }, False
    return {
        "sp_quality": float(stats.get("starter_quality") or _era_to_quality(float(stats.get("era") or 4.5))),
        "sp_workload": float(stats.get("pitches") or 90.0),
        "sp_rest_days": 5.0,
        "sp_missing": 0.0,
    }, True


def _lineup_features(event_id: str, team: str, lineup_rows: list[dict], season_batters: dict, rolling_batters: dict) -> tuple[dict, bool]:
    rows = [
        row for row in lineup_rows
        if str(row.get("game_id") or row.get("event_id") or "") == event_id
        and (str(row.get("team") or "") == team or not row.get("team"))
    ]
    if not rows:
        return {
            "lineup_strength": 0.0,
            "top_order_strength": 0.0,
            "lineup_lefty_share": 0.0,
            "lineup_missing_count": 9.0,
            "lineup_confirmed_share": 0.0,
        }, False
    values: list[float] = []
    top_values: list[float] = []
    missing = 0
    confirmed = 0
    lefties = 0
    sources: set[str] = set()
    for row in rows:
        name = str(row.get("player_name") or "")
        stats = _lookup_player_stats(name, rolling_batters) or _lookup_player_stats(name, season_batters)
        if stats:
            value = float(stats.get("batting_value") or stats.get("ops") or 0.0)
        else:
            value = 0.0
            missing += 1
        values.append(value)
        if float(row.get("batting_order") or 99.0) <= 5:
            top_values.append(value)
        if str(row.get("confirmed")).lower() in {"true", "1", "yes"}:
            confirmed += 1
        source = str(row.get("source") or "")
        if source:
            sources.add(source)
        if str(row.get("bats") or "").upper().startswith("L"):
            lefties += 1
    total = len(rows)
    confirmed_share = confirmed / total if total else 0.0
    lineup_source_confidence = confirmed_share or 0.80
    return {
        "lineup_strength": _mean(values),
        "top_order_strength": _mean(top_values),
        "lineup_lefty_share": lefties / total if total else 0.0,
        "lineup_missing_count": float(missing),
        "lineup_confirmed_share": confirmed_share,
        "lineup_source_confidence": lineup_source_confidence,
        "lineup_source": ",".join(sorted(sources)) or "general_lineup",
    }, True


def _bullpen_features(team: str, bullpen_rows: list[dict], target_date: str) -> tuple[dict, bool]:
    rows = [row for row in bullpen_rows if str(row.get("team") or "") == team and str(row.get("game_date") or "")[:10] <= target_date]
    if not rows:
        return {"bp_recent_pitches": 0.0, "bp_quality": 0.0, "bp_missing": 1.0}, False
    recent = [row for row in rows if _days_ago(str(row.get("game_date") or "")[:10], target_date) <= 3]
    innings = sum(float(row.get("innings_pitched") or 0.0) for row in rows)
    er = sum(float(row.get("earned_runs") or 0.0) for row in rows)
    era = (er * 9.0 / innings) if innings else 4.5
    return {
        "bp_recent_pitches": sum(float(row.get("pitches") or 0.0) for row in recent),
        "bp_quality": _era_to_quality(era),
        "bp_missing": 0.0,
    }, True


def _absence_features(event_id: str, team: str, side: str, absence_rows: list[dict]) -> tuple[dict, bool]:
    rows = [
        row for row in absence_rows
        if str(row.get("game_id") or row.get("event_id") or "") == event_id
        and (str(row.get("team") or "") == team or str(row.get("side") or "") == side)
    ]
    return {
        "absence_value": sum(float(row.get("absence_value") or 0.0) for row in rows),
        "absence_count": float(len(rows)),
    }, True


def _lookup_player_stats(player_name: str, stats: dict) -> dict | None:
    if not player_name:
        return None
    normalized = _normalize_pitcher_name(player_name).lower()
    for key, value in stats.items():
        name = str(value.get("player_name") or key).lower()
        if name == normalized:
            return value
    return None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _days_ago(row_date: str, target_date: str) -> int:
    if not row_date:
        return 999
    return (date.fromisoformat(target_date) - date.fromisoformat(row_date)).days


def _is_stale(updated_at: str, target_date: str, stale_after_days: int) -> bool:
    if not updated_at:
        return True
    try:
        updated = date.fromisoformat(updated_at[:10])
    except ValueError:
        return True
    return (date.fromisoformat(target_date) - updated).days > stale_after_days
