"""
MLB team offense baseline (lineup-agnostic MVP) — free pybaseball data.

Record per team:
    team, runs_per_game_season, runs_per_game_last10, woba_season,
    obp_season, slg_season, k_rate_batting, bb_rate_batting,
    games_sample, missing_features

MVP rules:
  - Lineup-specific features are intentionally NOT produced here.  The
    model may substitute a neutral factor, but the paper-bet gate keeps
    seeing ``lineup_confirmed`` as missing (see TeamSideFeatures).
  - Missing values stay None and appear in ``missing_features``.
  - last-10 uses only completed games dated strictly BEFORE the target
    date — future/same-day games can never leak in.

Cache: derived records refresh once daily (data/cache/mlb/team_offense/).
"""
from __future__ import annotations

import json
import logging
import pickle
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from alpha.engines.sports.mlb_features import TeamOffenseFeatures

logger = logging.getLogger(__name__)

_BASE_CACHE = Path(__file__).resolve().parents[3] / "data" / "cache" / "mlb" / "team_offense"
RAW_CACHE_DIR = _BASE_CACHE / "raw"
FEATURES_CACHE_DIR = _BASE_CACHE / "features"

_FEATURE_FIELDS = (
    "runs_per_game_season",
    "runs_per_game_last10",
    "woba_season",
    "obp_season",
    "slg_season",
    "k_rate_batting",
    "bb_rate_batting",
)


class TeamOffenseDataSource(Protocol):
    """Pluggable free-data source (default: pybaseball)."""

    def season_batting_record(self, team: str, season: int) -> dict | None:
        """Season aggregates: games, runs_per_game, woba, obp, slg,
        k_rate, bb_rate (any may be absent)."""
        ...

    def team_game_results(self, team: str, season: int) -> list[dict] | None:
        """Completed games: [{date: YYYY-MM-DD, runs: int}]."""
        ...


class PybaseballTeamOffenseSource:
    """Default source backed by pybaseball FanGraphs team batting."""

    def __init__(self, raw_cache_dir: Path | None = RAW_CACHE_DIR):
        self._raw_cache_dir = raw_cache_dir

    def _raw_cached(self, key: str) -> Any | None:
        if self._raw_cache_dir is None:
            return None
        path = self._raw_cache_dir / f"{key}_{date_cls.today()}.pkl"
        if path.exists():
            try:
                with open(path, "rb") as f:
                    return pickle.load(f)
            except Exception:
                pass
        return None

    def _raw_save(self, key: str, data: Any) -> None:
        if self._raw_cache_dir is None:
            return
        try:
            self._raw_cache_dir.mkdir(parents=True, exist_ok=True)
            with open(self._raw_cache_dir / f"{key}_{date_cls.today()}.pkl", "wb") as f:
                pickle.dump(data, f)
        except Exception as exc:
            logger.debug("Raw team offense cache write failed: %s", exc)

    def season_batting_record(self, team: str, season: int) -> dict | None:
        key = f"fg_team_batting_{season}"
        df = self._raw_cached(key)
        if df is None:
            try:
                import pybaseball as pb  # noqa: PLC0415

                df = pb.team_batting(season)
                self._raw_save(key, df)
            except Exception as exc:
                logger.warning("FanGraphs team batting fetch failed: %s", exc)
                return None
        try:
            rows = df[df["Team"].astype(str).str.strip() == team]
            if rows.empty:
                return None
            row = rows.iloc[0]

            def _num(col: str) -> float | None:
                try:
                    v = row.get(col)
                    return float(v) if v is not None and v == v else None
                except (TypeError, ValueError):
                    return None

            games = _num("G")
            runs = _num("R")
            pa = _num("PA")
            so = _num("SO")
            bb = _num("BB")
            return {
                "games": int(games) if games else None,
                "runs_per_game": (
                    round(runs / games, 3) if runs is not None and games else None
                ),
                "woba": _num("wOBA"),
                "obp": _num("OBP"),
                "slg": _num("SLG"),
                "k_rate": round(so / pa, 4) if so is not None and pa else None,
                "bb_rate": round(bb / pa, 4) if bb is not None and pa else None,
            }
        except Exception as exc:
            logger.warning("Team batting record lookup failed (%s): %s", team, exc)
            return None

    def team_game_results(self, team: str, season: int) -> list[dict] | None:
        # Per-game team run logs need a schedule-and-record pull keyed by
        # team abbreviation; left to the StatsAPI-backed scanner where the
        # schedule is already free.  Returning None keeps last-10 missing
        # rather than invented.
        return None


# ---------------------------------------------------------------------------
# Feature builder
# ---------------------------------------------------------------------------

def get_team_offense(
    team: str,
    game_date: str,
    season: int | None = None,
    source: TeamOffenseDataSource | None = None,
    features_cache_dir: Path | None = FEATURES_CACHE_DIR,
) -> dict:
    """
    Build the daily team offense baseline record for ``team``.

    Returns an all-missing record (fail closed) when the source has no
    data for the team — values are never invented.
    """
    cached = _load_feature_cache(features_cache_dir, team, game_date)
    if cached is not None:
        return cached

    season = season or int(game_date[:4])
    source = source or PybaseballTeamOffenseSource()

    record: dict = {"team": team, "games_sample": None}
    record.update({f: None for f in _FEATURE_FIELDS})

    season_rec = source.season_batting_record(team, season) or {}
    record["games_sample"] = season_rec.get("games")
    record["runs_per_game_season"] = season_rec.get("runs_per_game")
    record["woba_season"] = season_rec.get("woba")
    record["obp_season"] = season_rec.get("obp")
    record["slg_season"] = season_rec.get("slg")
    record["k_rate_batting"] = season_rec.get("k_rate")
    record["bb_rate_batting"] = season_rec.get("bb_rate")

    results = source.team_game_results(team, season)
    record["runs_per_game_last10"] = _rolling_last10(results, game_date)

    record["missing_features"] = [f for f in _FEATURE_FIELDS if record[f] is None]
    _write_feature_cache(features_cache_dir, team, game_date, record)
    return record


def to_team_offense_features(record: dict) -> TeamOffenseFeatures:
    """Convert an ingestion record into the model's TeamOffenseFeatures."""
    return TeamOffenseFeatures(
        team=record.get("team", ""),
        runs_per_game_season=record.get("runs_per_game_season"),
        runs_per_game_last10=record.get("runs_per_game_last10"),
        woba_season=record.get("woba_season"),
        obp_season=record.get("obp_season"),
        slg_season=record.get("slg_season"),
        k_rate_batting=record.get("k_rate_batting"),
        bb_rate_batting=record.get("bb_rate_batting"),
        games_sample=record.get("games_sample"),
        missing_features=list(record.get("missing_features", [])),
    )


def _rolling_last10(results: list[dict] | None, game_date: str) -> float | None:
    """Mean runs over the last 10 completed games strictly before game_date."""
    if not results:
        return None
    cutoff = datetime.strptime(game_date, "%Y-%m-%d").date()
    completed = []
    for entry in results:
        try:
            d = datetime.strptime(str(entry["date"]), "%Y-%m-%d").date()
            runs = float(entry["runs"])
        except (KeyError, TypeError, ValueError):
            continue
        if d < cutoff:  # never include same-day or future games
            completed.append((d, runs))
    if not completed:
        return None
    completed.sort(key=lambda x: x[0])
    last10 = [runs for _, runs in completed[-10:]]
    return round(sum(last10) / len(last10), 3)


# ---------------------------------------------------------------------------
# Derived feature cache (daily)
# ---------------------------------------------------------------------------

def _cache_key(team: str) -> str:
    return team.lower().replace(" ", "_")


def _feature_cache_file(cache_dir: Path, team: str, game_date: str) -> Path:
    return cache_dir / f"offense_{_cache_key(team)}_{game_date}.json"


def _load_feature_cache(
    cache_dir: Path | None, team: str, game_date: str
) -> dict | None:
    if cache_dir is None:
        return None
    path = _feature_cache_file(cache_dir, team, game_date)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("_cached_on") != str(date_cls.today()):  # refresh once daily
        return None
    data.pop("_cached_on", None)
    return data


def _write_feature_cache(
    cache_dir: Path | None, team: str, game_date: str, record: dict
) -> None:
    if cache_dir is None:
        return
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(record)
        payload["_cached_on"] = str(date_cls.today())
        _feature_cache_file(cache_dir, team, game_date).write_text(
            json.dumps(payload), encoding="utf-8"
        )
    except Exception as exc:
        logger.debug("Team offense cache write failed: %s", exc)
