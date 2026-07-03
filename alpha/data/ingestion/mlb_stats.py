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
_FIP_CONSTANT = 3.10

_ABBR_TO_FULL: dict[str, str] = {
    "ARI": "Arizona Diamondbacks",
    "ATL": "Atlanta Braves",
    "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox",
    "CHC": "Chicago Cubs",
    "CHW": "Chicago White Sox",
    "CIN": "Cincinnati Reds",
    "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies",
    "DET": "Detroit Tigers",
    "HOU": "Houston Astros",
    "KC": "Kansas City Royals",
    "KCR": "Kansas City Royals",
    "LAA": "Los Angeles Angels",
    "LAD": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",
    "NYM": "New York Mets",
    "NYY": "New York Yankees",
    "OAK": "Athletics",
    "ATH": "Athletics",
    "PHI": "Philadelphia Phillies",
    "PIT": "Pittsburgh Pirates",
    "SD": "San Diego Padres",
    "SDP": "San Diego Padres",
    "SEA": "Seattle Mariners",
    "SF": "San Francisco Giants",
    "SFG": "San Francisco Giants",
    "STL": "St. Louis Cardinals",
    "TB": "Tampa Bay Rays",
    "TBR": "Tampa Bay Rays",
    "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",
    "WSH": "Washington Nationals",
    "WSN": "Washington Nationals",
}


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


def _num(value: object, default: float = 0.0) -> float:
    if value in (None, "", ".---", "-.--"):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if number != number else number


def _pct(value: object, default: float = 0.0) -> float:
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    number = _num(value, default)
    return number / 100.0 if abs(number) > 1.0 else number


def _player_name(value: object) -> str:
    text = str(value or "").strip()
    if "," not in text:
        return text
    last, first = [part.strip() for part in text.split(",", 1)]
    return f"{first} {last}".strip()


def _team_name(value: object) -> str:
    text = str(value or "").strip()
    return _ABBR_TO_FULL.get(text, text)


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


def get_advanced_batter_stats(season: int | None = None, min_pa: int = 20) -> list[dict]:
    """
    Return advanced individual hitter inputs for the local player database.

    Online sources:
        - Baseball Savant expected stats for xwOBA.
        - Baseball-Reference WAR via pybaseball for WAR.

    Fields unavailable from these stable feeds, such as true wRC+ and platoon
    splits, remain 0.0 so downstream code can see they were not populated.
    """
    s = season or _CURRENT_SEASON
    cache_key = f"advanced_batter_stats_{s}_{min_pa}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    try:
        import pybaseball as pb  # noqa: PLC0415

        by_id: dict[str, dict] = {}
        try:
            savant = pb.statcast_batter_expected_stats(s)
            if savant is not None and not savant.empty:
                for _, row in savant.iterrows():
                    player_id = str(int(_num(row.get("player_id")))) if _num(row.get("player_id")) else ""
                    if not player_id:
                        continue
                    pa = int(_num(row.get("pa")))
                    if pa < min_pa:
                        continue
                    by_id[player_id] = {
                        "player_id": player_id,
                        "player": _player_name(row.get("last_name, first_name")),
                        "team": "",
                        "war": 0.0,
                        "xwoba": round(_num(row.get("est_woba")), 3),
                        "wrc_plus": 0.0,
                        "platoon_wrc_plus": 0.0,
                        "lineup_spot": 0.0,
                        "vs_opponent_wrc_plus": 0.0,
                        "vs_opponent_xwoba": 0.0,
                        "pa": pa,
                    }
        except Exception as exc:
            logger.warning("Savant hitter expected stats fetch failed: %s", exc)

        try:
            bwar = pb.bwar_bat()
            if bwar is not None and not bwar.empty:
                season_rows = bwar[bwar["year_ID"] == s]
                grouped: dict[str, dict] = {}
                for _, row in season_rows.iterrows():
                    player_id = str(int(_num(row.get("mlb_ID")))) if _num(row.get("mlb_ID")) else ""
                    if not player_id:
                        continue
                    bucket = grouped.setdefault(player_id, {
                        "player_id": player_id,
                        "player": str(row.get("name_common") or "").strip(),
                        "team": "",
                        "war": 0.0,
                        "pa": 0,
                    })
                    bucket["war"] += _num(row.get("WAR"))
                    bucket["pa"] += int(_num(row.get("PA")))
                    team = str(row.get("team_ID") or "").strip()
                    if team and team != "TOT":
                        bucket["team"] = _team_name(team)
                for player_id, war_row in grouped.items():
                    if int(war_row.get("pa") or 0) < min_pa and player_id not in by_id:
                        continue
                    row = by_id.setdefault(player_id, {
                        "player_id": player_id,
                        "player": war_row.get("player", ""),
                        "team": "",
                        "war": 0.0,
                        "xwoba": 0.0,
                        "wrc_plus": 0.0,
                        "platoon_wrc_plus": 0.0,
                        "lineup_spot": 0.0,
                        "vs_opponent_wrc_plus": 0.0,
                        "vs_opponent_xwoba": 0.0,
                        "pa": int(war_row.get("pa") or 0),
                    })
                    row["player"] = row.get("player") or war_row.get("player", "")
                    row["team"] = row.get("team") or war_row.get("team", "")
                    row["war"] = round(_num(war_row.get("war")), 2)
                    row["pa"] = max(int(row.get("pa") or 0), int(war_row.get("pa") or 0))
        except Exception as exc:
            logger.warning("Baseball-Reference hitter WAR fetch failed: %s", exc)

        results = [
            row for row in by_id.values()
            if row.get("player") and int(row.get("pa") or 0) >= min_pa
        ]
        _save_cache(cache_key, results)
        logger.info("Fetched advanced MLB batter stats: %d players", len(results))
        return results
    except Exception as exc:
        logger.warning("Advanced MLB batter stats fetch failed: %s", exc)
        return []


def get_advanced_pitcher_stats(season: int | None = None, min_bf: int = 20) -> list[dict]:
    """
    Return advanced individual pitcher inputs for the local player database.

    Online sources:
        - Baseball Savant expected stats for xERA.
        - Baseball-Reference WAR via pybaseball for WAR.
        - MLB StatsAPI season components to derive FIP and K-BB%.
    """
    s = season or _CURRENT_SEASON
    cache_key = f"advanced_pitcher_stats_{s}_{min_bf}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    try:
        import pybaseball as pb  # noqa: PLC0415

        by_id: dict[str, dict] = {}
        try:
            savant = pb.statcast_pitcher_expected_stats(s)
            if savant is not None and not savant.empty:
                for _, row in savant.iterrows():
                    player_id = str(int(_num(row.get("player_id")))) if _num(row.get("player_id")) else ""
                    if not player_id:
                        continue
                    bf = int(_num(row.get("pa")))
                    if bf < min_bf:
                        continue
                    by_id[player_id] = {
                        "player_id": player_id,
                        "player": _player_name(row.get("last_name, first_name")),
                        "team": "",
                        "role": "",
                        "war": 0.0,
                        "xera": round(_num(row.get("xera")), 2),
                        "fip": 0.0,
                        "k_bb_pct": 0.0,
                        "rest_days": 0.0,
                        "pitch_count_workload": 0.0,
                        "velocity_change": 0.0,
                        "projected_innings": 0.0,
                        "vs_opponent_fip": 0.0,
                        "bf": bf,
                    }
        except Exception as exc:
            logger.warning("Savant pitcher expected stats fetch failed: %s", exc)

        try:
            for stat_row in _statsapi_pitching_metric_rows(s):
                player_id = str(stat_row.get("player_id") or "")
                if not player_id:
                    continue
                row = by_id.setdefault(player_id, {
                    "player_id": player_id,
                    "player": stat_row.get("player", ""),
                    "team": "",
                    "role": "",
                    "war": 0.0,
                    "xera": 0.0,
                    "fip": 0.0,
                    "k_bb_pct": 0.0,
                    "rest_days": 0.0,
                    "pitch_count_workload": 0.0,
                    "velocity_change": 0.0,
                    "projected_innings": 0.0,
                    "vs_opponent_fip": 0.0,
                    "bf": int(stat_row.get("bf") or 0),
                })
                row["player"] = row.get("player") or stat_row.get("player", "")
                row["team"] = row.get("team") or stat_row.get("team", "")
                row["role"] = stat_row.get("role", "")
                row["fip"] = stat_row.get("fip", 0.0)
                row["k_bb_pct"] = stat_row.get("k_bb_pct", 0.0)
                row["projected_innings"] = stat_row.get("projected_innings", 0.0)
                row["bf"] = max(int(row.get("bf") or 0), int(stat_row.get("bf") or 0))
        except Exception as exc:
            logger.warning("StatsAPI pitcher advanced components fetch failed: %s", exc)

        try:
            bwar = pb.bwar_pitch()
            if bwar is not None and not bwar.empty:
                season_rows = bwar[bwar["year_ID"] == s]
                grouped: dict[str, dict] = {}
                for _, row in season_rows.iterrows():
                    player_id = str(int(_num(row.get("mlb_ID")))) if _num(row.get("mlb_ID")) else ""
                    if not player_id:
                        continue
                    bucket = grouped.setdefault(player_id, {
                        "player_id": player_id,
                        "player": str(row.get("name_common") or "").strip(),
                        "team": "",
                        "war": 0.0,
                        "gs": 0.0,
                    })
                    bucket["war"] += _num(row.get("WAR"))
                    bucket["gs"] += _num(row.get("GS"))
                    team = str(row.get("team_ID") or "").strip()
                    if team and team != "TOT":
                        bucket["team"] = _team_name(team)
                for player_id, war_row in grouped.items():
                    row = by_id.setdefault(player_id, {
                        "player_id": player_id,
                        "player": war_row.get("player", ""),
                        "team": "",
                        "role": "starter" if _num(war_row.get("gs")) > 0 else "reliever",
                        "war": 0.0,
                        "xera": 0.0,
                        "fip": 0.0,
                        "k_bb_pct": 0.0,
                        "rest_days": 0.0,
                        "pitch_count_workload": 0.0,
                        "velocity_change": 0.0,
                        "projected_innings": 0.0,
                        "vs_opponent_fip": 0.0,
                        "bf": 0,
                    })
                    row["player"] = row.get("player") or war_row.get("player", "")
                    row["team"] = row.get("team") or war_row.get("team", "")
                    row["war"] = round(_num(war_row.get("war")), 2)
        except Exception as exc:
            logger.warning("Baseball-Reference pitcher WAR fetch failed: %s", exc)

        results = [
            row for row in by_id.values()
            if row.get("player") and int(row.get("bf") or 0) >= min_bf
        ]
        _save_cache(cache_key, results)
        logger.info("Fetched advanced MLB pitcher stats: %d pitchers", len(results))
        return results
    except Exception as exc:
        logger.warning("Advanced MLB pitcher stats fetch failed: %s", exc)
        return []


def get_advanced_bullpen_stats(season: int | None = None) -> list[dict]:
    """Return team bullpen advanced inputs derived from MLB StatsAPI reliever rows."""
    s = season or _CURRENT_SEASON
    cache_key = f"advanced_bullpen_stats_{s}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached
    try:
        totals: dict[str, dict[str, float]] = {}
        for row in _statsapi_pitching_metric_rows(s):
            if row.get("role") == "starter":
                continue
            team = str(row.get("team") or "")
            if not team:
                continue
            bucket = totals.setdefault(team, {
                "ip": 0.0,
                "hr": 0.0,
                "bb": 0.0,
                "hbp": 0.0,
                "so": 0.0,
                "bf": 0.0,
            })
            for key in ("ip", "hr", "bb", "hbp", "so", "bf"):
                bucket[key] += _num(row.get(key))
        results = []
        for team, values in totals.items():
            ip = values["ip"]
            bf = values["bf"]
            results.append({
                "team": team,
                "xera": 0.0,
                "fip": _derive_fip(values["hr"], values["bb"], values["hbp"], values["so"], ip),
                "k_bb_pct": round((values["so"] - values["bb"]) / bf, 4) if bf else 0.0,
                "pitch_count_workload": 0.0,
                "rest_days": 0.0,
                "velocity_change": 0.0,
                "projected_innings": 0.0,
                "starter_bullpen_role_adjustment": 0.0,
                "team_matchup_adjustment": 0.0,
            })
        _save_cache(cache_key, results)
        logger.info("Fetched advanced MLB bullpen stats: %d teams", len(results))
        return results
    except Exception as exc:
        logger.warning("Advanced MLB bullpen stats fetch failed: %s", exc)
        return []


def _statsapi_pitching_metric_rows(season: int) -> list[dict]:
    import requests  # noqa: PLC0415

    response = requests.get(
        "https://statsapi.mlb.com/api/v1/stats",
        params={
            "stats": "season",
            "group": "pitching",
            "playerPool": "ALL",
            "season": str(season),
            "sportIds": "1",
            "limit": "5000",
            "hydrate": "team",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    splits = list((payload.get("stats") or [{}])[0].get("splits") or [])
    rows: list[dict] = []
    for split in splits:
        player = split.get("player") or {}
        stat = split.get("stat") or {}
        team = split.get("team") or {}
        player_id = str(player.get("id") or "").strip()
        name = str(player.get("fullName") or "").strip()
        team_name = str(team.get("name") or "").strip()
        if not player_id or not name:
            continue
        ip = _parse_statsapi_innings(stat.get("inningsPitched"))
        bb = _num(stat.get("baseOnBalls"))
        hbp = _num(stat.get("hitByPitch"))
        so = _num(stat.get("strikeOuts"))
        hr = _num(stat.get("homeRuns"))
        bf = _num(stat.get("battersFaced"))
        starts = _num(stat.get("gamesStarted"))
        games = _num(stat.get("games"))
        rows.append({
            "player_id": player_id,
            "player": name,
            "team": team_name,
            "role": "starter" if starts > 0 else "reliever",
            "fip": _derive_fip(hr, bb, hbp, so, ip),
            "k_bb_pct": round((so - bb) / bf, 4) if bf else 0.0,
            "projected_innings": round(ip / starts, 2) if starts else 0.0,
            "ip": ip,
            "hr": hr,
            "bb": bb,
            "hbp": hbp,
            "so": so,
            "bf": bf,
            "games": games,
            "starts": starts,
        })
    return rows


def _parse_statsapi_innings(value: object) -> float:
    text = str(value or "0").strip()
    if "." not in text:
        return _num(text)
    whole, frac = text.split(".", 1)
    innings = _num(whole)
    outs = {"0": 0.0, "1": 1.0 / 3.0, "2": 2.0 / 3.0}.get(frac[:1])
    return innings + outs if outs is not None else _num(text)


def _derive_fip(hr: float, bb: float, hbp: float, so: float, ip: float) -> float:
    if ip <= 0.0:
        return 0.0
    fip = ((13.0 * hr) + (3.0 * (bb + hbp)) - (2.0 * so)) / ip + _FIP_CONSTANT
    return round(max(0.0, fip), 2)


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
                "home_odds": -110,
                "away_odds": -110,
                "league": "mlb",
                "event_id": game_id,
                "commence_time": commence,
                "game_date": target,
                "game_number": game.get("game_num") or game.get("game_number"),
                "home_probable_pitcher": game.get("home_probable_pitcher", ""),
                "away_probable_pitcher": game.get("away_probable_pitcher", ""),
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
