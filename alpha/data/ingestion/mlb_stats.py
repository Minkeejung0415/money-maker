"""
MLB team and player rolling stats via pybaseball.

Team stats (rolling 10-game window):
    runs_per_game, runs_allowed, batting_avg, era, whip

Player stats (per game):
    avg, obp, slg, hr_per_game (batters)
    k_per9, era (pitchers)

Starting pitcher lookup via MLB StatsAPI (probable pitchers).
Cache: data/.mlb_cache/ with 24-hour TTL.
"""
from __future__ import annotations

import logging
import pickle
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("data/.mlb_cache")
_ROLLING_WINDOW = 10
_CURRENT_SEASON = datetime.now().year


def _cache_path(key: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{key}_{date.today()}.pkl"


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


def get_team_batting_stats(season: int | None = None) -> list[dict]:
    """
    Return team batting stats for the given season.

    Each record:
        {
            "team": str,
            "runs_per_game": float,
            "batting_avg": float,
            "obp": float,
            "slg": float,
            "ops": float,
        }

    Returns [] on any failure.
    """
    s = season or _CURRENT_SEASON
    cache_key = f"team_batting_{s}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    try:
        import pybaseball as pb  # noqa: PLC0415

        df = pb.team_batting(s)
        if df is None or df.empty:
            return []

        results = []
        for _, row in df.iterrows():
            team = str(row.get("Team", row.get("teamID", ""))).strip()
            if not team or team == "nan":
                continue
            games = float(row.get("G", 1) or 1)
            results.append({
                "team": team,
                "runs_per_game": round(float(row.get("R", 0) or 0) / games, 3),
                "batting_avg": round(float(row.get("BA", row.get("AVG", 0.250)) or 0.250), 3),
                "obp": round(float(row.get("OBP", 0.320) or 0.320), 3),
                "slg": round(float(row.get("SLG", 0.400) or 0.400), 3),
                "ops": round(float(row.get("OPS", 0.720) or 0.720), 3),
            })

        _save_cache(cache_key, results)
        logger.info("Fetched MLB team batting stats: %d teams", len(results))
        return results
    except Exception as exc:
        logger.warning("MLB team batting stats fetch failed: %s", exc)
        return []


def get_team_pitching_stats(season: int | None = None) -> list[dict]:
    """
    Return team pitching stats for the given season.

    Each record:
        {
            "team": str,
            "era": float,
            "whip": float,
            "runs_allowed_per_game": float,
            "k_per9": float,
        }

    Returns [] on any failure.
    """
    s = season or _CURRENT_SEASON
    cache_key = f"team_pitching_{s}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    try:
        import pybaseball as pb  # noqa: PLC0415

        df = pb.team_pitching(s)
        if df is None or df.empty:
            return []

        results = []
        for _, row in df.iterrows():
            team = str(row.get("Team", row.get("teamID", ""))).strip()
            if not team or team == "nan":
                continue
            games = float(row.get("G", 1) or 1)
            ip = float(row.get("IP", 1) or 1)
            results.append({
                "team": team,
                "era": round(float(row.get("ERA", 4.50) or 4.50), 2),
                "whip": round(float(row.get("WHIP", 1.30) or 1.30), 3),
                "runs_allowed_per_game": round(float(row.get("R", 0) or 0) / games, 3),
                "k_per9": round(float(row.get("SO", 0) or 0) / ip * 9, 2),
            })

        _save_cache(cache_key, results)
        logger.info("Fetched MLB team pitching stats: %d teams", len(results))
        return results
    except Exception as exc:
        logger.warning("MLB team pitching stats fetch failed: %s", exc)
        return []


def get_batter_stats(season: int | None = None, min_pa: int = 50) -> list[dict]:
    """
    Return individual batter stats for the given season.

    Each record:
        {
            "player": str,
            "team": str,
            "avg": float,
            "obp": float,
            "slg": float,
            "hr_per_game": float,
            "pa": int,
        }

    Returns [] on any failure.
    """
    s = season or _CURRENT_SEASON
    cache_key = f"batter_stats_{s}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    try:
        import pybaseball as pb  # noqa: PLC0415

        df = pb.batting_stats(s, qual=min_pa)
        if df is None or df.empty:
            return []

        results = []
        for _, row in df.iterrows():
            name = str(row.get("Name", "")).strip()
            if not name:
                continue
            games = float(row.get("G", 1) or 1)
            results.append({
                "player": name,
                "team": str(row.get("Team", "")).strip(),
                "avg": round(float(row.get("AVG", 0.250) or 0.250), 3),
                "obp": round(float(row.get("OBP", 0.320) or 0.320), 3),
                "slg": round(float(row.get("SLG", 0.400) or 0.400), 3),
                "hr_per_game": round(float(row.get("HR", 0) or 0) / games, 4),
                "pa": int(row.get("PA", 0) or 0),
            })

        _save_cache(cache_key, results)
        logger.info("Fetched MLB batter stats: %d players", len(results))
        return results
    except Exception as exc:
        logger.warning("MLB batter stats fetch failed: %s", exc)
        return []


def get_pitcher_stats(season: int | None = None, min_ip: int = 10) -> list[dict]:
    """
    Return individual pitcher stats for the given season.

    Each record:
        {
            "player": str,
            "team": str,
            "era": float,
            "whip": float,
            "k_per9": float,
            "ip": float,
        }

    Returns [] on any failure.
    """
    s = season or _CURRENT_SEASON
    cache_key = f"pitcher_stats_{s}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    try:
        import pybaseball as pb  # noqa: PLC0415

        df = pb.pitching_stats(s, qual=min_ip)
        if df is None or df.empty:
            return []

        results = []
        for _, row in df.iterrows():
            name = str(row.get("Name", "")).strip()
            if not name:
                continue
            ip = float(row.get("IP", 1) or 1)
            results.append({
                "player": name,
                "team": str(row.get("Team", "")).strip(),
                "era": round(float(row.get("ERA", 4.50) or 4.50), 2),
                "whip": round(float(row.get("WHIP", 1.30) or 1.30), 3),
                "k_per9": round(float(row.get("SO", 0) or 0) / ip * 9, 2),
                "ip": round(ip, 1),
            })

        _save_cache(cache_key, results)
        logger.info("Fetched MLB pitcher stats: %d pitchers", len(results))
        return results
    except Exception as exc:
        logger.warning("MLB pitcher stats fetch failed: %s", exc)
        return []


def get_probable_pitchers(date_str: str | None = None) -> dict[str, str]:
    """
    Return {team_abbr: pitcher_name} for today's probable starters
    via MLB StatsAPI.

    Returns {} on any failure.
    """
    target = date_str or date.today().isoformat()
    cache_key = f"probable_pitchers_{target}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    result: dict[str, str] = {}

    # Try mlb-statsapi first
    try:
        import statsapi  # noqa: PLC0415

        schedule = statsapi.schedule(date=target)
        for game in schedule:
            home_team = game.get("home_name", "")
            away_team = game.get("away_name", "")
            home_pitcher = game.get("home_probable_pitcher", "")
            away_pitcher = game.get("away_probable_pitcher", "")
            if home_team and home_pitcher:
                result[home_team] = home_pitcher
            if away_team and away_pitcher:
                result[away_team] = away_pitcher
    except Exception as exc:
        logger.debug("StatsAPI probable pitchers failed: %s", exc)

    # Fallback: pybaseball schedule_and_record (season-wide)
    if not result:
        try:
            import pybaseball as pb  # noqa: PLC0415
            logger.debug("Falling back to pybaseball schedule for pitchers")
            # pybaseball doesn't provide probable pitchers directly
        except Exception:
            pass

    if result:
        _save_cache(cache_key, result)
    return result


def fetch_today_games(date_str: str | None = None) -> list[dict]:
    """
    Return today's MLB games via MLB StatsAPI (free, no key needed).

    Returns list of game dicts:
        {
            "home_team": str,
            "away_team": str,
            "home_odds": int,    # -110 default (no odds available)
            "away_odds": int,    # -110 default
            "league": "mlb",
            "event_id": str,
            "commence_time": str,
        }

    Returns [] on any failure.
    """
    target = date_str or date.today().isoformat()
    cache_key = f"today_games_{target}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    try:
        import statsapi  # noqa: PLC0415

        schedule = statsapi.schedule(date=target)
        games = []
        for game in schedule:
            home = game.get("home_name", "")
            away = game.get("away_name", "")
            game_id = str(game.get("game_id", ""))
            commence = game.get("game_datetime", "")
            if not home or not away:
                continue
            # Only include regular season + postseason (skip spring training)
            if game.get("game_type", "R") not in ("R", "F", "D", "L", "W"):
                continue
            games.append({
                "home_team": home,
                "away_team": away,
                # StatsAPI carries no odds; these are PLACEHOLDERS and must
                # never be bet on — has_real_odds gates paper bets off.
                "home_odds": -110,
                "away_odds": -110,
                "has_real_odds": False,
                "league": "mlb",
                "event_id": game_id,
                "commence_time": commence,
            })

        if games:
            _save_cache(cache_key, games)
        logger.info("Fetched %d MLB games from StatsAPI", len(games))
        return games

    except Exception as exc:
        logger.warning("MLB StatsAPI game fetch failed: %s", exc)
        return []


def get_team_stats_map(season: int | None = None) -> dict[str, dict]:
    """
    Return combined team stats (batting + pitching) keyed by team name/abbr.
    Used by MLBModel._build_game_features().
    """
    batting = {r["team"]: r for r in get_team_batting_stats(season)}
    pitching = {r["team"]: r for r in get_team_pitching_stats(season)}

    teams = set(batting) | set(pitching)
    result = {}
    for t in teams:
        b = batting.get(t, {})
        p = pitching.get(t, {})
        result[t] = {
            "runs_per_game": b.get("runs_per_game", 4.5),
            "batting_avg": b.get("batting_avg", 0.250),
            "obp": b.get("obp", 0.320),
            "slg": b.get("slg", 0.400),
            "ops": b.get("ops", 0.720),
            "era": p.get("era", 4.50),
            "whip": p.get("whip", 1.30),
            "runs_allowed_per_game": p.get("runs_allowed_per_game", 4.5),
            "k_per9": p.get("k_per9", 8.5),
        }
    return result
