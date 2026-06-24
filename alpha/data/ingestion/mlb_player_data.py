"""Canonical MLB game and player-slot data for player-aware moneyline work.

This module is intentionally additive. It does not replace the v1.3 team-only
MLB training schema; it provides normalized inputs that later phases can use to
build player-aware features.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CanonicalGame:
    game_id: str
    game_date: str
    home_team: str
    away_team: str
    venue: str | None = None
    status: str | None = None
    game_type: str | None = None
    doubleheader: bool = False
    game_number: int | None = None
    home_score: float | None = None
    away_score: float | None = None
    home_win: int | None = None
    home_starter_id: str | None = None
    home_starter_name: str | None = None
    away_starter_id: str | None = None
    away_starter_name: str | None = None
    source: str = "unknown"
    confirmed: bool = False
    missing_reason: str | None = None


@dataclass(frozen=True)
class GamePlayerSlot:
    game_id: str
    team: str | None
    side: str | None
    player_id: str | None
    player_name: str | None
    batting_order: int | None = None
    position: str | None = None
    slot_type: str = "lineup"
    source: str = "unknown"
    confirmed: bool = False
    missing_reason: str | None = None


ID_FIELDS = (
    "player_id",
    "mlbam_id",
    "key_mlbam",
    "retrosheet_id",
    "key_retro",
    "bbref_id",
    "key_bbref",
    "fangraphs_id",
    "key_fangraphs",
)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _first(raw: dict, *keys: str) -> Any:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "final", "confirmed"}


def _norm_name(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    return " ".join(text.casefold().replace(".", "").split())


def _source(raw: dict, default: str) -> str:
    return _text(raw.get("source")) or default


def _starter_id(raw: dict, side: str) -> str | None:
    pitcher = raw.get(f"{side}_probable_pitcher")
    if isinstance(pitcher, dict):
        return _text(_first(pitcher, "id", "player_id", "mlbam_id"))
    return _text(_first(raw, f"{side}_starter_id", f"{side}_probable_pitcher_id", f"{side}_pitcher_id"))


def _starter_name(raw: dict, side: str) -> str | None:
    pitcher = raw.get(f"{side}_probable_pitcher")
    if isinstance(pitcher, dict):
        return _text(_first(pitcher, "fullName", "name", "player_name"))
    return _text(_first(raw, f"{side}_starter_name", f"{side}_probable_pitcher", f"{side}_pitcher_name"))


def _missing_reasons(*parts: str | None) -> str | None:
    reasons = [part for part in parts if part]
    return "; ".join(reasons) if reasons else None


def _game_date(raw: dict) -> str:
    value = _first(raw, "game_date", "date", "gameDate", "game_datetime", "commence_time")
    if value is None:
        return ""
    return str(value)[:10]


def _game_id(raw: dict) -> str | None:
    return _text(_first(raw, "game_id", "gamePk", "game_pk", "event_id", "id"))


def _canonical_game(raw: dict) -> CanonicalGame | None:
    game_id = _game_id(raw)
    home_team = _text(_first(raw, "home_team", "home_name", "homeTeam", "home"))
    away_team = _text(_first(raw, "away_team", "away_name", "awayTeam", "away"))
    if not game_id or not home_team or not away_team:
        return None

    home_score = _float(_first(raw, "home_score", "homeScore"))
    away_score = _float(_first(raw, "away_score", "awayScore"))
    status = _text(_first(raw, "status", "detailed_state", "abstractGameState"))
    is_final = (status or "").casefold() == "final"
    home_win = None
    if is_final and home_score is not None and away_score is not None and home_score != away_score:
        home_win = int(home_score > away_score)

    home_starter_name = _starter_name(raw, "home")
    away_starter_name = _starter_name(raw, "away")
    missing_home = "missing_home_starter" if not home_starter_name else None
    missing_away = "missing_away_starter" if not away_starter_name else None
    explicit_missing = _text(raw.get("missing_reason"))

    return CanonicalGame(
        game_id=game_id,
        game_date=_game_date(raw),
        home_team=home_team,
        away_team=away_team,
        venue=_text(_first(raw, "venue", "venue_name", "venueName")),
        status=status,
        game_type=_text(_first(raw, "game_type", "gameType")),
        doubleheader=_bool(_first(raw, "doubleheader", "is_doubleheader")),
        game_number=_int(_first(raw, "game_number", "game_num", "gameNumber")),
        home_score=home_score,
        away_score=away_score,
        home_win=home_win,
        home_starter_id=_starter_id(raw, "home"),
        home_starter_name=home_starter_name,
        away_starter_id=_starter_id(raw, "away"),
        away_starter_name=away_starter_name,
        source=_source(raw, "statsapi"),
        confirmed=is_final or _bool(raw.get("confirmed")),
        missing_reason=_missing_reasons(explicit_missing, missing_home, missing_away),
    )


def normalize_games(raw_games: list[dict]) -> list[dict]:
    """Normalize StatsAPI-like schedule rows into canonical game dicts."""
    deduped: dict[str, CanonicalGame] = {}
    for raw in raw_games or []:
        game = _canonical_game(raw)
        if game is None:
            continue
        existing = deduped.get(game.game_id)
        if existing is None or (not existing.confirmed and game.confirmed):
            deduped[game.game_id] = game
    ordered = sorted(deduped.values(), key=lambda g: (g.game_date, g.game_id))
    return [asdict(game) for game in ordered]


def _side(raw: dict) -> str | None:
    side = _text(_first(raw, "side", "home_away", "team_side"))
    if side:
        value = side.casefold()
        if value in {"home", "h"}:
            return "home"
        if value in {"away", "a", "visitor"}:
            return "away"
    if "is_home" in raw:
        return "home" if _bool(raw["is_home"]) else "away"
    return None


def _canonical_slot(raw: dict, fallback_game_id: str | None) -> GamePlayerSlot | None:
    game_id = _text(_first(raw, "game_id", "gamePk", "game_pk")) or fallback_game_id
    if not game_id:
        return None
    player_name = _text(_first(raw, "player_name", "name", "player", "fullName"))
    player_id = _text(_first(raw, "player_id", "mlbam_id", "key_mlbam", "id"))
    missing = _text(raw.get("missing_reason"))
    if not player_name and not player_id:
        missing = _missing_reasons(missing, "missing_player_identity")

    return GamePlayerSlot(
        game_id=game_id,
        team=_text(_first(raw, "team", "team_name")),
        side=_side(raw),
        player_id=player_id,
        player_name=player_name,
        batting_order=_int(_first(raw, "batting_order", "batting_slot", "slot", "order")),
        position=_text(_first(raw, "position", "fielding_position", "pos")),
        slot_type=_text(_first(raw, "slot_type", "role")) or "lineup",
        source=_source(raw, "lineup"),
        confirmed=_bool(raw.get("confirmed")),
        missing_reason=missing,
    )


def normalize_player_slots(raw_slots: list[dict], game_id: str | None = None) -> list[dict]:
    """Normalize lineup/starter rows into canonical game-player slot dicts."""
    slots = []
    for raw in raw_slots or []:
        slot = _canonical_slot(raw, game_id)
        if slot is not None:
            slots.append(asdict(slot))
    side_order = {"home": 0, "away": 1}
    return sorted(
        slots,
        key=lambda s: (
            s["game_id"],
            side_order.get(s.get("side"), 2),
            s.get("batting_order") or 99,
            s.get("player_name") or "",
        ),
    )


def build_player_id_map(rows: list[dict]) -> dict[str, dict]:
    """Build lookup keys for known external IDs and normalized names."""
    mapping: dict[str, dict] = {}
    for raw in rows or []:
        canonical = {
            "player_name": _text(_first(raw, "player_name", "name", "player")),
            "mlbam_id": _text(_first(raw, "mlbam_id", "key_mlbam", "player_id")),
            "retrosheet_id": _text(_first(raw, "retrosheet_id", "key_retro")),
            "bbref_id": _text(_first(raw, "bbref_id", "key_bbref")),
            "fangraphs_id": _text(_first(raw, "fangraphs_id", "key_fangraphs")),
        }
        keys = []
        for field in ID_FIELDS:
            value = _text(raw.get(field))
            if value:
                keys.append(f"{field}:{value}")
                keys.append(value)
        name_key = _norm_name(canonical["player_name"])
        if name_key:
            keys.append(f"name:{name_key}")
        for key in keys:
            mapping[key] = canonical
    return mapping


def _slot_matches(slot: dict, id_map: dict[str, dict]) -> bool:
    player_id = _text(slot.get("player_id"))
    if player_id and player_id in id_map:
        return True
    if player_id and f"player_id:{player_id}" in id_map:
        return True
    name_key = _norm_name(slot.get("player_name"))
    return bool(name_key and f"name:{name_key}" in id_map)


def report_unmatched_players(slots: list[dict], id_map: dict[str, dict]) -> list[dict]:
    """Return player slots that cannot be joined to the supplied ID map."""
    unmatched = []
    for slot in slots or []:
        if _slot_matches(slot, id_map):
            continue
        unmatched.append({
            "game_id": slot.get("game_id"),
            "team": slot.get("team"),
            "side": slot.get("side"),
            "player_id": slot.get("player_id"),
            "player_name": slot.get("player_name"),
            "source": slot.get("source"),
            "missing_reason": slot.get("missing_reason") or "unmatched_player_id",
        })
    return unmatched


def _default_schedule_provider(target: str) -> list[dict]:
    import statsapi  # noqa: PLC0415

    return statsapi.schedule(date=target)


def _call_provider(provider: Callable | None, *args: Any) -> Any:
    if provider is None:
        return []
    try:
        return provider(*args)
    except TypeError:
        return provider(args[0])


def fetch_day_of_player_context(
    date_str: str | None = None,
    schedule_provider: Callable[[str], list[dict]] | None = None,
    lineup_provider: Callable[..., list[dict]] | None = None,
    injury_provider: Callable[..., Any] | None = None,
    id_rows: list[dict] | None = None,
) -> dict:
    """Assemble day-of games, player slots, injuries, and unmatched reports.

    Providers are injectable so unit tests and default runs can avoid live
    network calls. The default schedule provider uses MLB StatsAPI only when
    this function is called without an injected provider.
    """
    target = date_str or date.today().isoformat()
    errors: list[dict] = []

    try:
        raw_games = (schedule_provider or _default_schedule_provider)(target)
    except Exception as exc:  # pragma: no cover - exercised through behavior
        logger.debug("MLB day-of schedule provider failed: %s", exc)
        raw_games = []
        errors.append({"source": "schedule", "error": str(exc)})
    games = normalize_games(raw_games)

    try:
        raw_slots = _call_provider(lineup_provider, target, games)
    except Exception as exc:
        logger.debug("MLB day-of lineup provider failed: %s", exc)
        raw_slots = []
        errors.append({"source": "lineups", "error": str(exc)})
    slots = normalize_player_slots(raw_slots)

    if injury_provider is None:
        try:
            from alpha.data.ingestion.mlb_injuries import get_team_injury_impact  # noqa: PLC0415

            injuries = get_team_injury_impact()
        except Exception as exc:
            injuries = {}
            errors.append({"source": "injuries", "error": str(exc)})
    else:
        try:
            injuries = _call_provider(injury_provider, target)
        except Exception as exc:
            injuries = {}
            errors.append({"source": "injuries", "error": str(exc)})

    id_map = build_player_id_map(id_rows or [])
    unmatched = report_unmatched_players(slots, id_map) if id_map else []
    return {
        "date": target,
        "games": games,
        "game_player_slots": slots,
        "injuries": injuries or {},
        "unmatched_players": unmatched,
        "errors": errors,
    }


def espn_team_id_duplicates(team_ids: dict[str, int] | None = None) -> dict[int, list[str]]:
    """Return duplicate ESPN team IDs from a map for fallback-source auditing."""
    if team_ids is None:
        try:
            from alpha.data.ingestion.mlb_injuries import _ESPN_TEAM_IDS  # noqa: PLC0415

            team_ids = _ESPN_TEAM_IDS
        except Exception:
            return {}
    by_id: dict[int, list[str]] = {}
    for team, team_id in team_ids.items():
        by_id.setdefault(int(team_id), []).append(team)
    return {team_id: teams for team_id, teams in by_id.items() if len(teams) > 1}
