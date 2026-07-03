"""Interpret local MLB player database rows into event-level runtime features."""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable

from alpha.data.ingestion.mlb_player_database import (
    _pitcher_quality_from_advanced,
    build_player_stat_snapshot,
    load_database_snapshot,
    write_json,
)
from alpha.data.ingestion.mlb_live_player_features import _normalize_pitcher_name

_LG_WOBA = 0.317
_WOBA_SCALE = 1.24
_RUNS_PER_WIN = 9.824
_REPL_RUNS_PER_PA = 0.028
_LEAGUE_RA9 = 4.50
_DEFAULT_HITTER_PA = 600.0
_DEFAULT_STARTER_IP = 5.3
_STARTER_RUN_DIFF_CAP = 0.75
_LINEUP_RUN_DIFF_CAP = 0.35
_TOP_ORDER_RUN_DIFF_CAP = 0.20
_BULLPEN_RUN_DIFF_CAP = 0.15
_ABSENCE_RUN_DIFF_CAP = 0.50
_BULLPEN_RUN_SHRINK = 0.0875
_LINEUP_PA_BY_SLOT = {
    1: 4.65,
    2: 4.55,
    3: 4.45,
    4: 4.35,
    5: 4.20,
    6: 4.05,
    7: 3.90,
    8: 3.75,
    9: 3.60,
}


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

            bullpen_features, hit = _bullpen_features(
                team,
                bullpen_rows,
                target_date,
                expected_bullpen_ip=max(
                    0.0,
                    9.0 - float(sp_features.get("sp_projected_innings") or _DEFAULT_STARTER_IP),
                ),
            )
            features.update({f"{side}_{key}": value for key, value in bullpen_features.items()})
            component_hits += int(hit)

            absence_features, hit = _absence_features(event_id, team, side, absence_rows)
            features.update({f"{side}_{key}": value for key, value in absence_features.items()})
            component_hits += int(hit)

        starter_run_diff = _clamp(
            float(features["home_starter_run_value"]) - float(features["away_starter_run_value"]),
            _STARTER_RUN_DIFF_CAP,
        )
        lineup_run_diff = _clamp(
            float(features["home_lineup_run_value"]) - float(features["away_lineup_run_value"]),
            _LINEUP_RUN_DIFF_CAP,
        )
        top_order_run_diff = _clamp(
            float(features["home_top_order_run_value"]) - float(features["away_top_order_run_value"]),
            _TOP_ORDER_RUN_DIFF_CAP,
        )
        bullpen_run_diff = _clamp(
            float(features["home_bullpen_run_value"]) - float(features["away_bullpen_run_value"]),
            _BULLPEN_RUN_DIFF_CAP,
        )
        absence_run_diff = _clamp(
            float(features["home_absence_run_value"]) - float(features["away_absence_run_value"]),
            _ABSENCE_RUN_DIFF_CAP,
        )
        features.update({
            "sp_quality_diff": float(features["home_sp_quality"]) - float(features["away_sp_quality"]),
            "starter_run_value_diff": starter_run_diff,
            "sp_workload_diff": float(features["home_sp_workload"]) - float(features["away_sp_workload"]),
            "lineup_strength_diff": float(features["home_lineup_strength"]) - float(features["away_lineup_strength"]),
            "lineup_run_value_diff": lineup_run_diff,
            "top_order_strength_diff": float(features["home_top_order_strength"]) - float(features["away_top_order_strength"]),
            "top_order_run_value_diff": top_order_run_diff,
            "bullpen_quality_diff": float(features["home_bp_quality"]) - float(features["away_bp_quality"]),
            "bullpen_run_value_diff": bullpen_run_diff,
            "bullpen_recent_pitches_diff": float(features["home_bp_recent_pitches"]) - float(features["away_bp_recent_pitches"]),
            "absence_value_diff": float(features["home_absence_value"]) - float(features["away_absence_value"]),
            "absence_run_value_diff": absence_run_diff,
            "player_run_value_diff": (
                starter_run_diff + lineup_run_diff + bullpen_run_diff - absence_run_diff
            ),
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
            "sp_projected_innings": 0.0,
            "starter_skill_ra9": 0.0,
            "starter_run_value": 0.0,
            "sp_missing": 1.0,
        }, False
    skill_ra9 = _starter_skill_ra9(stats)
    projected_ip = max(1.0, min(7.5, float(stats.get("projected_innings") or _DEFAULT_STARTER_IP)))
    starter_run_value = (projected_ip / 9.0) * (_LEAGUE_RA9 - skill_ra9) if skill_ra9 > 0.0 else 0.0
    return {
        "sp_quality": float(stats.get("starter_quality") or 0.0),
        "sp_workload": float(stats.get("pitch_count_workload") or stats.get("pitches") or 0.0),
        "sp_rest_days": float(stats.get("rest_days") or 0.0),
        "sp_projected_innings": projected_ip,
        "starter_skill_ra9": skill_ra9,
        "starter_run_value": starter_run_value,
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
            "lineup_run_value": 0.0,
            "top_order_run_value": 0.0,
            "lineup_lefty_share": 0.0,
            "lineup_missing_count": 9.0,
            "lineup_confirmed_share": 0.0,
            "lineup_source_confidence": 0.0,
            "lineup_source": "missing",
        }, False
    values: list[float] = []
    top_values: list[float] = []
    run_values: list[float] = []
    top_run_values: list[float] = []
    missing = 0
    confirmed = 0
    lefties = 0
    sources: set[str] = set()
    for row in rows:
        name = str(row.get("player_name") or "")
        stats = _lookup_player_stats(name, rolling_batters) or _lookup_player_stats(name, season_batters)
        if stats:
            value = float(stats.get("today_player_value") or stats.get("batting_value") or 0.0)
            run_value = _hitter_game_run_value(stats, float(row.get("batting_order") or 99.0))
        else:
            value = 0.0
            run_value = 0.0
            missing += 1
        values.append(value)
        run_values.append(run_value)
        if float(row.get("batting_order") or 99.0) <= 5:
            top_values.append(value)
            top_run_values.append(run_value)
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
        "lineup_run_value": sum(run_values),
        "top_order_run_value": sum(top_run_values),
        "lineup_lefty_share": lefties / total if total else 0.0,
        "lineup_missing_count": float(missing),
        "lineup_confirmed_share": confirmed_share,
        "lineup_source_confidence": lineup_source_confidence,
        "lineup_source": ",".join(sorted(sources)) or "general_lineup",
    }, True


def _bullpen_features(
    team: str,
    bullpen_rows: list[dict],
    target_date: str,
    *,
    expected_bullpen_ip: float,
) -> tuple[dict, bool]:
    rows = [row for row in bullpen_rows if str(row.get("team") or "") == team and str(row.get("game_date") or "")[:10] <= target_date]
    if not rows:
        return {"bp_recent_pitches": 0.0, "bp_quality": 0.0, "bullpen_skill_ra9": 0.0, "bullpen_run_value": 0.0, "bp_missing": 1.0}, False
    recent = [row for row in rows if _days_ago(str(row.get("game_date") or "")[:10], target_date) <= 3]
    xera = _mean([float(row.get("xera") or 0.0) for row in rows if float(row.get("xera") or 0.0) > 0.0])
    fip = _mean([float(row.get("fip") or 0.0) for row in rows if float(row.get("fip") or 0.0) > 0.0])
    k_bb_pct = _mean([float(row.get("k_bb_pct") or 0.0) for row in rows if float(row.get("k_bb_pct") or 0.0) > 0.0])
    skill_ra9 = _bullpen_skill_ra9(fip=fip, xera=xera, k_bb_pct=k_bb_pct)
    run_value = _BULLPEN_RUN_SHRINK * (max(0.0, expected_bullpen_ip) / 9.0) * (_LEAGUE_RA9 - skill_ra9) if skill_ra9 > 0.0 else 0.0
    return {
        "bp_recent_pitches": sum(float(row.get("pitch_count_workload") or 0.0) for row in recent),
        "bp_quality": _pitcher_quality_from_advanced(xera=xera, fip=fip, k_bb_pct=k_bb_pct),
        "bullpen_skill_ra9": skill_ra9,
        "bullpen_run_value": run_value,
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
        "absence_run_value": sum(_absence_run_value(row) for row in rows),
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


def _clamp(value: float, cap: float) -> float:
    return max(-cap, min(cap, value))


def _hitter_game_run_value(stats: dict, lineup_slot: float) -> float:
    projected_pa = _projected_pa(lineup_slot)
    season_pa = float(stats.get("pa") or 0.0) or _DEFAULT_HITTER_PA
    war = float(stats.get("war") or 0.0)
    xwoba = float(stats.get("xwoba") or 0.0)
    components: list[float] = []
    if season_pa > 0.0 and war:
        components.append((war * _RUNS_PER_WIN) / season_pa)
    if xwoba > 0.0:
        components.append(((xwoba - _LG_WOBA) / _WOBA_SCALE) + _REPL_RUNS_PER_PA)
    if not components:
        today_value = float(stats.get("today_player_value") or stats.get("batting_value") or 0.0)
        components.append((today_value * _RUNS_PER_WIN) / _DEFAULT_HITTER_PA)
    return projected_pa * _mean(components)


def _projected_pa(lineup_slot: float) -> float:
    slot = int(lineup_slot) if lineup_slot > 0.0 and lineup_slot < 99.0 else 6
    return _LINEUP_PA_BY_SLOT.get(slot, 4.0)


def _starter_skill_ra9(stats: dict) -> float:
    fip = float(stats.get("fip") or 0.0)
    xera = float(stats.get("xera") or 0.0)
    if fip > 0.0 and xera > 0.0:
        value = (0.60 * fip) + (0.40 * xera)
    else:
        value = fip or xera
    return max(2.5, min(7.0, value)) if value > 0.0 else 0.0


def _bullpen_skill_ra9(*, fip: float, xera: float, k_bb_pct: float) -> float:
    if fip > 0.0 and xera > 0.0:
        return (0.75 * fip) + (0.25 * xera)
    if fip > 0.0:
        return fip
    if xera > 0.0:
        return xera
    if k_bb_pct > 0.0:
        return max(2.5, min(6.5, _LEAGUE_RA9 - ((k_bb_pct - 0.14) * 8.0)))
    return 0.0


def _absence_run_value(row: dict) -> float:
    if row.get("absence_run_value") not in (None, ""):
        return float(row.get("absence_run_value") or 0.0)
    today_value = float(row.get("today_player_value") or row.get("war") or 0.0)
    role = str(row.get("role") or row.get("player_type") or "").lower()
    if role in {"p", "sp", "starter", "pitcher"}:
        projected_ip = float(row.get("projected_innings") or _DEFAULT_STARTER_IP)
        return (today_value * _RUNS_PER_WIN) * (projected_ip / 180.0)
    projected_pa = float(row.get("projected_pa") or 4.2)
    season_pa = float(row.get("pa") or _DEFAULT_HITTER_PA)
    return (today_value * _RUNS_PER_WIN / season_pa) * projected_pa


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
