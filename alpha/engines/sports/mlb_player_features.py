"""Leakage-safe MLB player-aware game features.

Phase 22 builds additive feature rows for future player-aware moneyline models.
The v1.3 team-only training path remains unchanged.
"""
from __future__ import annotations

from datetime import date
from statistics import mean
from typing import Any, Iterable


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _float(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _game_date(row: dict) -> str:
    return str(row.get("game_date") or row.get("date") or "")[:10]


def _game_number(row: dict) -> int:
    return _int(row.get("game_number"), 1) or 1


def _sort_games(games: Iterable[dict]) -> list[dict]:
    return sorted(games or [], key=lambda g: (_game_date(g), _game_number(g), str(g.get("game_id", ""))))


def _is_prior(row: dict, target: dict, allow_between_games: bool) -> bool:
    row_date = _game_date(row)
    target_date = _game_date(target)
    if not row_date or not target_date:
        return False
    if row_date < target_date:
        return True
    if row_date > target_date or not allow_between_games:
        return False
    return _game_number(row) < _game_number(target)


def _days_between(start: str, end: str) -> float | None:
    if not start or not end:
        return None
    return float((date.fromisoformat(end) - date.fromisoformat(start)).days)


def _player_key(row: dict) -> str | None:
    return _text(row.get("player_id")) or _text(row.get("mlbam_id")) or _text(row.get("player_name"))


def _value(row: dict, *keys: str, default: float | None = None) -> float | None:
    for key in keys:
        if key in row:
            value = _float(row.get(key))
            if value is not None:
                return value
    return default


def _latest_prior(rows: list[dict], target: dict, allow_between_games: bool) -> dict | None:
    prior = [row for row in rows if _is_prior(row, target, allow_between_games)]
    if not prior:
        return None
    return sorted(prior, key=lambda r: (_game_date(r), _game_number(r), str(r.get("game_id", ""))))[-1]


def _prior_rows(rows: list[dict], target: dict, allow_between_games: bool) -> list[dict]:
    return [row for row in rows if _is_prior(row, target, allow_between_games)]


def _mean(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def _starter_id(game: dict, side: str) -> str | None:
    return _text(game.get(f"{side}_starter_id")) or _text(game.get(f"{side}_starter_name"))


def _starter_features(
    game: dict,
    side: str,
    pitcher_logs_by_player: dict[str, list[dict]],
    allow_between_games: bool,
) -> dict[str, float]:
    starter_id = _starter_id(game, side)
    if not starter_id:
        return {
            f"{side}_sp_quality": 0.0,
            f"{side}_sp_workload": 0.0,
            f"{side}_sp_rest_days": 0.0,
            f"{side}_sp_missing": 1.0,
        }
    prior = _prior_rows(pitcher_logs_by_player.get(starter_id, []), game, allow_between_games)
    if not prior:
        return {
            f"{side}_sp_quality": 0.0,
            f"{side}_sp_workload": 0.0,
            f"{side}_sp_rest_days": 0.0,
            f"{side}_sp_missing": 1.0,
        }
    quality = [_value(row, "starter_quality", "quality", "xera_score", default=0.0) or 0.0 for row in prior]
    latest = prior[-1]
    return {
        f"{side}_sp_quality": _mean(quality),
        f"{side}_sp_workload": _value(latest, "pitch_count", "pitches", "batters_faced", default=0.0) or 0.0,
        f"{side}_sp_rest_days": _days_between(_game_date(latest), _game_date(game)) or 0.0,
        f"{side}_sp_missing": 0.0,
    }


def _slot_side_matches(slot: dict, game: dict, side: str) -> bool:
    if slot.get("game_id") != game.get("game_id"):
        return False
    slot_side = _text(slot.get("side"))
    if slot_side:
        return slot_side == side
    team = _text(slot.get("team"))
    return bool(team and team == _text(game.get(f"{side}_team")))


def _lineup_slots(game: dict, slots: list[dict], side: str) -> list[dict]:
    return sorted(
        [slot for slot in slots if _slot_side_matches(slot, game, side)],
        key=lambda s: (_int(s.get("batting_order"), 99) or 99, _text(s.get("player_name")) or ""),
    )


def _batter_lookup(batter_rows: list[dict]) -> dict[str, list[dict]]:
    by_player: dict[str, list[dict]] = {}
    for row in batter_rows or []:
        key = _player_key(row)
        if key:
            by_player.setdefault(key, []).append(row)
    for rows in by_player.values():
        rows.sort(key=lambda r: (_game_date(r), _game_number(r), str(r.get("game_id", ""))))
    return by_player


def _lineup_features(
    game: dict,
    slots: list[dict],
    side: str,
    batter_rows_by_player: dict[str, list[dict]],
    allow_between_games: bool,
) -> dict[str, float]:
    lineup = _lineup_slots(game, slots, side)
    if not lineup:
        return {
            f"{side}_lineup_strength": 0.0,
            f"{side}_top_order_strength": 0.0,
            f"{side}_lineup_lefty_share": 0.0,
            f"{side}_lineup_missing_count": 9.0,
            f"{side}_lineup_confirmed_share": 0.0,
        }

    values: list[float] = []
    top_values: list[float] = []
    missing = 0
    confirmed = 0
    lefties = 0
    for slot in lineup:
        if slot.get("confirmed"):
            confirmed += 1
        key = _player_key(slot)
        latest = _latest_prior(batter_rows_by_player.get(key or "", []), game, allow_between_games)
        if latest is None:
            missing += 1
            value = 0.0
            bats = _text(slot.get("bats"))
        else:
            value = _value(latest, "batting_value", "xwoba", "quality", "ops", default=0.0) or 0.0
            bats = _text(slot.get("bats")) or _text(latest.get("bats"))
        values.append(value)
        if (_int(slot.get("batting_order"), 99) or 99) <= 5:
            top_values.append(value)
        if bats and bats.upper().startswith("L"):
            lefties += 1

    total = len(lineup)
    return {
        f"{side}_lineup_strength": _mean(values),
        f"{side}_top_order_strength": _mean(top_values),
        f"{side}_lineup_lefty_share": lefties / total if total else 0.0,
        f"{side}_lineup_missing_count": float(missing),
        f"{side}_lineup_confirmed_share": confirmed / total if total else 0.0,
    }


def _team_key(row: dict, side_or_team: str) -> str | None:
    if side_or_team in {"home", "away"}:
        return _text(row.get(f"{side_or_team}_team"))
    return _text(row.get("team"))


def _bullpen_features(
    game: dict,
    team: str | None,
    side: str,
    relief_logs_by_team: dict[str, list[dict]],
    allow_between_games: bool,
) -> dict[str, float]:
    if not team:
        return {
            f"{side}_bp_recent_pitches": 0.0,
            f"{side}_bp_quality": 0.0,
            f"{side}_bp_missing": 1.0,
        }
    prior = _prior_rows(relief_logs_by_team.get(team, []), game, allow_between_games)
    if not prior:
        return {
            f"{side}_bp_recent_pitches": 0.0,
            f"{side}_bp_quality": 0.0,
            f"{side}_bp_missing": 1.0,
        }
    target_date = _game_date(game)
    recent = [
        row for row in prior
        if (_days_between(_game_date(row), target_date) is not None and _days_between(_game_date(row), target_date) <= 3)
    ]
    quality = [_value(row, "relief_quality", "quality", default=0.0) or 0.0 for row in prior]
    return {
        f"{side}_bp_recent_pitches": sum(_value(row, "pitches", "pitch_count", default=0.0) or 0.0 for row in recent),
        f"{side}_bp_quality": _mean(quality),
        f"{side}_bp_missing": 0.0,
    }


def _absence_features(game: dict, side: str, absence_rows: list[dict]) -> dict[str, float]:
    team = _text(game.get(f"{side}_team"))
    game_id = game.get("game_id")
    matched = [
        row for row in absence_rows or []
        if row.get("game_id") == game_id and (_text(row.get("team")) == team or _text(row.get("side")) == side)
    ]
    value = sum(_value(row, "absence_value", "player_value", "batting_value", default=0.0) or 0.0 for row in matched)
    return {
        f"{side}_absence_value": value,
        f"{side}_absence_count": float(len(matched)),
    }


def _group_by_player(rows: list[dict]) -> dict[str, list[dict]]:
    by_player: dict[str, list[dict]] = {}
    for row in rows or []:
        key = _player_key(row)
        if key:
            by_player.setdefault(key, []).append(row)
    for values in by_player.values():
        values.sort(key=lambda r: (_game_date(r), _game_number(r), str(r.get("game_id", ""))))
    return by_player


def _group_by_team(rows: list[dict]) -> dict[str, list[dict]]:
    by_team: dict[str, list[dict]] = {}
    for row in rows or []:
        team = _text(row.get("team"))
        if team:
            by_team.setdefault(team, []).append(row)
    for values in by_team.values():
        values.sort(key=lambda r: (_game_date(r), _game_number(r), str(r.get("game_id", ""))))
    return by_team


def build_player_aware_game_rows(
    games: list[dict],
    player_slots: list[dict],
    pitcher_logs: list[dict] | None = None,
    batter_logs: list[dict] | None = None,
    relief_logs: list[dict] | None = None,
    absence_rows: list[dict] | None = None,
    *,
    allow_between_games: bool = False,
) -> list[dict]:
    """Return one player-aware pregame feature row per game.

    By default, all history is strictly before the target date. Setting
    ``allow_between_games`` permits earlier games on the same date to be used
    for later same-day games, which is useful only when the prediction time is
    explicitly between doubleheader games.
    """
    pitcher_by_player = _group_by_player(pitcher_logs or [])
    batter_by_player = _batter_lookup(batter_logs or [])
    relief_by_team = _group_by_team(relief_logs or [])
    rows: list[dict] = []

    for game in _sort_games(games):
        row = {
            "game_id": game.get("game_id"),
            "game_date": _game_date(game),
            "home_team": game.get("home_team"),
            "away_team": game.get("away_team"),
        }
        if "home_win" in game:
            row["home_win"] = game.get("home_win")

        for side in ("home", "away"):
            row.update(_starter_features(game, side, pitcher_by_player, allow_between_games))
            row.update(_lineup_features(game, player_slots, side, batter_by_player, allow_between_games))
            row.update(_bullpen_features(game, _text(game.get(f"{side}_team")), side, relief_by_team, allow_between_games))
            row.update(_absence_features(game, side, absence_rows or []))

        row.update({
            "sp_quality_diff": row["home_sp_quality"] - row["away_sp_quality"],
            "sp_workload_diff": row["home_sp_workload"] - row["away_sp_workload"],
            "lineup_strength_diff": row["home_lineup_strength"] - row["away_lineup_strength"],
            "top_order_strength_diff": row["home_top_order_strength"] - row["away_top_order_strength"],
            "bullpen_quality_diff": row["home_bp_quality"] - row["away_bp_quality"],
            "bullpen_recent_pitches_diff": row["home_bp_recent_pitches"] - row["away_bp_recent_pitches"],
            "absence_value_diff": row["home_absence_value"] - row["away_absence_value"],
            "lineup_missing_count_total": row["home_lineup_missing_count"] + row["away_lineup_missing_count"],
            "player_feature_missing_flag": float(
                row["home_sp_missing"]
                or row["away_sp_missing"]
                or row["home_bp_missing"]
                or row["away_bp_missing"]
                or row["lineup_missing_count_total"] > 0
            ),
        })
        rows.append(row)
    return rows
