"""
Live player-aware feature builder for MLB v1.8 scanner.

Computes per-game starter quality features from today's probable pitchers
and season pitcher stats. Used by mlb_scanner.py to populate
game["player_features"] so the v1.8 bundle activates when present.

Features produced (starter_only set):
    {side}_sp_quality        — 0-1 pitcher quality (inverse-normalized ERA)
    {side}_sp_workload       — default 90.0 (pitch count; extended in future)
    {side}_sp_rest_days      — default 5.0 (days since last start)
    {side}_sp_missing        — 1.0 if pitcher unknown, 0.0 if found
    sp_quality_diff          — home - away
    sp_workload_diff         — home - away (always 0.0 in this version)
    player_feature_missing_flag — 1.0 if either starter is missing

Keys must match the feature_names stored in the v1.8 artifact.
"""
from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)

# ERA normalization: ERA 1.5 → quality 1.0, ERA 6.5 → quality 0.0
_ERA_MAX = 6.5
_ERA_MIN = 1.5

_DEFAULT_WORKLOAD: float = 90.0
_DEFAULT_REST_DAYS: float = 5.0

# Static mapping: pybaseball team abbreviations → statsapi full team names.
# Used to look up team-level ERA quality when no named starter is available.
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
    "KC":  "Kansas City Royals",
    "LAA": "Los Angeles Angels",
    "LAD": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",
    "NYM": "New York Mets",
    "NYY": "New York Yankees",
    "OAK": "Oakland Athletics",
    "ATH": "Athletics",
    "PHI": "Philadelphia Phillies",
    "PIT": "Pittsburgh Pirates",
    "SD":  "San Diego Padres",
    "SEA": "Seattle Mariners",
    "SF":  "San Francisco Giants",
    "STL": "St. Louis Cardinals",
    "TB":  "Tampa Bay Rays",
    "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",
    "WSH": "Washington Nationals",
}

# Inverse mapping (full name → abbr) for when we need to go the other direction
_FULL_TO_ABBR: dict[str, str] = {v: k for k, v in _ABBR_TO_FULL.items()}


def _era_to_quality(era: float) -> float:
    """Convert ERA to a 0-1 quality score. Lower ERA → higher quality."""
    score = (_ERA_MAX - float(era)) / (_ERA_MAX - _ERA_MIN)
    return max(0.0, min(1.0, score))


def _normalize_pitcher_name(name: str) -> str:
    """Normalize 'Cole, Gerrit' → 'Gerrit Cole'. Pass-through for 'Gerrit Cole'."""
    name = name.strip()
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        return f"{parts[1]} {parts[0]}"
    return name


def _pitcher_quality_lookup(season: int | None = None) -> dict[str, float]:
    """
    Return {normalized_pitcher_name: quality} from season pitcher stats.
    Keyed by normalized full name (first last).
    """
    try:
        from alpha.data.ingestion.mlb_stats import get_pitcher_stats
        stats = get_pitcher_stats(season=season)
        result: dict[str, float] = {}
        for row in stats:
            name = _normalize_pitcher_name(str(row.get("player", "")))
            if name:
                result[name] = _era_to_quality(float(row.get("era", 4.50) or 4.50))
        return result
    except Exception as exc:
        logger.debug("Pitcher quality lookup failed: %s", exc)
        return {}


def _team_quality_by_full_name(season: int | None = None) -> dict[str, float]:
    """
    Return {statsapi_full_team_name: quality} from team pitching ERA.
    Fallback when probable starter name is unknown.
    """
    try:
        from alpha.data.ingestion.mlb_stats import get_team_pitching_stats
        stats = get_team_pitching_stats(season=season)
        result: dict[str, float] = {}
        for row in stats:
            abbr = str(row.get("team", ""))
            full_name = _ABBR_TO_FULL.get(abbr)
            if full_name:
                result[full_name] = _era_to_quality(float(row.get("era", 4.50) or 4.50))
        return result
    except Exception as exc:
        logger.debug("Team quality lookup failed: %s", exc)
        return {}


def build_quality_from_team_state(team_state: dict) -> dict[str, float]:
    """
    Derive {full_team_name: sp_quality} from the v1.8 artifact's team_state.

    Uses runs-allowed-per-game as the quality proxy (same formula as the
    training script). Called by the scanner when pybaseball is unavailable.

    Parameters
    ----------
    team_state:
        {team_name: {games, wins, runs_for, runs_against, elo, last_date}}
        as stored in the mlb_player_moneyline.pkl artifact.
    """
    result: dict[str, float] = {}
    for team, state in (team_state or {}).items():
        games_n = int(state.get("games") or 0)
        if games_n <= 0:
            continue
        runs_against = float(state.get("runs_against") or 0.0)
        per_game = runs_against / games_n
        quality = max(0.0, min(1.0, (8.0 - per_game) / 6.0))
        result[str(team)] = quality
    return result


def build_live_player_features(
    games: list[dict],
    *,
    game_date: str | None = None,
    season: int | None = None,
    team_quality_override: dict[str, float] | None = None,
    database_features_by_event: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """
    Build starter-only player feature dicts for today's games.

    Parameters
    ----------
    games:
        List of game dicts as returned by fetch_today_games().
        Each must have at minimum: event_id, home_team, away_team.
    game_date:
        ISO date string to use for probable-pitcher lookup.
        Defaults to today.
    season:
        MLB season year for pitcher stats (defaults to current year).
    database_features_by_event:
        Optional event-id keyed feature overrides from the local player database.

    Returns
    -------
    dict[event_id, feature_dict]
        Each feature_dict contains starter-only player features ready
        to be stored in game["player_features"].
    """
    today = game_date or date.today().isoformat()

    # Probable pitchers: {team_full_name: pitcher_name_raw}
    probable: dict[str, str] = {}
    try:
        from alpha.data.ingestion.mlb_stats import get_probable_pitchers
        probable = get_probable_pitchers(today)
    except Exception as exc:
        logger.warning("Probable pitchers unavailable: %s", exc)

    pitcher_quality = _pitcher_quality_lookup(season=season)
    # Team quality: try pybaseball first, then caller-supplied override (e.g. team_state-derived)
    team_quality = _team_quality_by_full_name(season=season)
    if not team_quality and team_quality_override:
        team_quality = team_quality_override
        logger.debug("Using team_quality_override (%d teams)", len(team_quality))

    result: dict[str, dict] = {}

    for game in games:
        event_id = str(game.get("event_id", ""))
        if not event_id:
            continue

        home_team = str(game.get("home_team", ""))
        away_team = str(game.get("away_team", ""))

        features: dict[str, float] = {}
        feature_sources: list[str] = []

        for side, team in (("home", home_team), ("away", away_team)):
            raw_pitcher = (
                str(game.get(f"{side}_probable_pitcher") or "").strip()
                or probable.get(team, "")
            )
            pitcher_name = _normalize_pitcher_name(raw_pitcher) if raw_pitcher else ""

            if pitcher_name and pitcher_name in pitcher_quality:
                quality = pitcher_quality[pitcher_name]
                missing = 0.0
                feature_sources.append(f"{side}_named_starter")
            elif team in team_quality:
                # Fall back to team-level ERA proxy
                quality = team_quality[team]
                missing = 0.0
                feature_sources.append(f"{side}_team_pitching_fallback")
            else:
                quality = 0.0
                missing = 1.0
                feature_sources.append(f"{side}_starter_missing")

            features[f"{side}_sp_quality"] = quality
            features[f"{side}_sp_workload"] = _DEFAULT_WORKLOAD
            features[f"{side}_sp_rest_days"] = _DEFAULT_REST_DAYS
            features[f"{side}_sp_missing"] = missing

        features["sp_quality_diff"] = (
            features["home_sp_quality"] - features["away_sp_quality"]
        )
        features["sp_workload_diff"] = 0.0
        features["player_feature_missing_flag"] = float(
            features["home_sp_missing"] >= 1.0 or features["away_sp_missing"] >= 1.0
        )
        features["player_source_confidence"] = 1.0 - (
            0.25 * features["player_feature_missing_flag"]
        )
        features["player_data_stale_flag"] = 0.0
        features["player_data_source"] = ",".join(feature_sources)

        if database_features_by_event and event_id in database_features_by_event:
            db_features = dict(database_features_by_event[event_id] or {})
            features.update(db_features)
            source = str(features.get("player_data_source") or "")
            features["player_data_source"] = (
                f"{source},local_player_database" if source else "local_player_database"
            )

        result[event_id] = features

    logger.debug(
        "Built live player features for %d/%d games", len(result), len(games)
    )
    return result


def team_era_quality_map_by_full_name(season: int) -> dict[str, float]:
    """
    Public helper for training scripts.

    Returns {statsapi_full_team_name: sp_quality_score} for the given season.
    Used to add team-level pitcher quality as a proxy for historical games.
    """
    return _team_quality_by_full_name(season=season)
