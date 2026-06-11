"""
MLB starter feature ingestion — free pybaseball / Baseball Savant data.

Produces one pregame feature record per probable starter:
    pitcher_id, pitcher_name, throws, starts_sample, innings_sample,
    era, xera, fip, whip, k_per9, bb_per9, hr_per9, xwoba_allowed,
    days_rest, velocity_delta_last3, pitch_count_last_start,
    missing_features

Fail-closed rules:
  - Only data dated strictly BEFORE the game date is used (pregame-only
    filtering is enforced in this module, not trusted to the source).
  - Missing values stay None and are listed in ``missing_features`` —
    nothing is ever invented.  Shrinkage toward league priors happens in
    ``mlb_features.StarterFeatures.shrunk`` at model time, never here.

Caching (both FREE, refreshed daily):
  - RAW source pulls:      data/cache/mlb/starters/raw/
  - DERIVED feature dicts: data/cache/mlb/starters/features/
  Raw and derived caches are deliberately separate so derived logic can
  change without re-downloading source data.
"""
from __future__ import annotations

import json
import logging
import pickle
from datetime import date as date_cls
from pathlib import Path
from typing import Any, Protocol

from alpha.engines.sports.mlb_features import StarterFeatures

logger = logging.getLogger(__name__)

_BASE_CACHE = Path(__file__).resolve().parents[3] / "data" / "cache" / "mlb" / "starters"
RAW_CACHE_DIR = _BASE_CACHE / "raw"
FEATURES_CACHE_DIR = _BASE_CACHE / "features"

# Every field the MVP record must carry (besides identifiers + missing list).
_FEATURE_FIELDS = (
    "throws",
    "starts_sample",
    "innings_sample",
    "era",
    "xera",
    "fip",
    "whip",
    "k_per9",
    "bb_per9",
    "hr_per9",
    "xwoba_allowed",
    "days_rest",
    "velocity_delta_last3",
    "pitch_count_last_start",
)

_FASTBALL_TYPES = {"FF", "SI", "FC"}


class StarterDataSource(Protocol):
    """Pluggable free-data source (default: pybaseball)."""

    def season_pitching_record(self, pitcher_id: int, season: int) -> dict | None:
        """Season-to-date aggregates: throws, starts, innings, era, xera,
        fip, whip, k_per9, bb_per9, hr_per9 (any may be absent)."""
        ...

    def statcast_pitch_log(self, pitcher_id: int, season: int) -> Any | None:
        """Per-pitch Statcast DataFrame with at least ``game_date``;
        ideally ``release_speed``, ``pitch_type``,
        ``estimated_woba_using_speedangle``, ``events``."""
        ...


class PybaseballStarterSource:
    """Default source backed by pybaseball (FanGraphs + Baseball Savant)."""

    def __init__(self, raw_cache_dir: Path | None = RAW_CACHE_DIR):
        self._raw_cache_dir = raw_cache_dir

    # -- raw cache helpers (daily) -------------------------------------

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
            logger.debug("Raw starter cache write failed: %s", exc)

    # -- source methods -------------------------------------------------

    def season_pitching_record(self, pitcher_id: int, season: int) -> dict | None:
        key = f"fg_pitching_{season}"
        df = self._raw_cached(key)
        if df is None:
            try:
                import pybaseball as pb  # noqa: PLC0415

                df = pb.pitching_stats(season, qual=0)
                self._raw_save(key, df)
            except Exception as exc:
                logger.warning("FanGraphs pitching stats fetch failed: %s", exc)
                return None
        try:
            import pybaseball as pb  # noqa: PLC0415

            lookup = pb.playerid_reverse_lookup([pitcher_id], key_type="mlbam")
            if lookup is None or lookup.empty:
                return None
            fg_id = lookup.iloc[0].get("key_fangraphs")
            rows = df[df["IDfg"] == fg_id] if "IDfg" in df.columns else df.iloc[0:0]
            if rows.empty:
                return None
            row = rows.iloc[0]

            def _num(col: str) -> float | None:
                try:
                    v = row.get(col)
                    return float(v) if v is not None and v == v else None
                except (TypeError, ValueError):
                    return None

            starts = _num("GS")
            return {
                "throws": None,  # FanGraphs table lacks handedness
                "starts": int(starts) if starts is not None else None,
                "innings": _num("IP"),
                "era": _num("ERA"),
                "xera": _num("xERA"),
                "fip": _num("FIP"),
                "whip": _num("WHIP"),
                "k_per9": _num("K/9"),
                "bb_per9": _num("BB/9"),
                "hr_per9": _num("HR/9"),
            }
        except Exception as exc:
            logger.warning("Season pitching record lookup failed (%s): %s", pitcher_id, exc)
            return None

    def statcast_pitch_log(self, pitcher_id: int, season: int) -> Any | None:
        key = f"statcast_p{pitcher_id}_{season}"
        df = self._raw_cached(key)
        if df is not None:
            return df
        try:
            import pybaseball as pb  # noqa: PLC0415

            df = pb.statcast_pitcher(f"{season}-03-01", f"{season}-11-30", pitcher_id)
            self._raw_save(key, df)
            return df
        except Exception as exc:
            logger.warning("Statcast pitcher log fetch failed (%s): %s", pitcher_id, exc)
            return None


# ---------------------------------------------------------------------------
# Feature builder
# ---------------------------------------------------------------------------

def get_starter_features(
    pitcher_id: int | None,
    pitcher_name: str | None,
    game_date: str,
    season: int | None = None,
    source: StarterDataSource | None = None,
    features_cache_dir: Path | None = FEATURES_CACHE_DIR,
) -> dict:
    """
    Build the pregame starter feature record for one probable pitcher.

    A missing ``pitcher_id`` returns an all-missing record immediately —
    we never guess which pitcher is starting.
    """
    record = _empty_record(pitcher_id, pitcher_name)
    if pitcher_id is None:
        record["missing_features"] = ["pitcher_id", *list(_FEATURE_FIELDS)]
        return record

    cached = _load_feature_cache(features_cache_dir, pitcher_id, game_date)
    if cached is not None:
        return cached

    season = season or int(game_date[:4])
    source = source or PybaseballStarterSource()

    season_rec = source.season_pitching_record(pitcher_id, season) or {}
    record["throws"] = season_rec.get("throws")
    record["starts_sample"] = season_rec.get("starts")
    record["innings_sample"] = season_rec.get("innings")
    for field in ("era", "xera", "fip", "whip", "k_per9", "bb_per9", "hr_per9"):
        record[field] = season_rec.get(field)

    pitch_log = source.statcast_pitch_log(pitcher_id, season)
    statcast = _derive_statcast_features(pitch_log, game_date)
    record.update(statcast)

    record["missing_features"] = [f for f in _FEATURE_FIELDS if record[f] is None]
    _write_feature_cache(features_cache_dir, pitcher_id, game_date, record)
    return record


def to_starter_features(record: dict) -> StarterFeatures:
    """Convert an ingestion record into the model's StarterFeatures schema."""
    return StarterFeatures(
        pitcher_id=record.get("pitcher_id"),
        pitcher_name=record.get("pitcher_name"),
        throws=record.get("throws"),
        starts_sample=record.get("starts_sample"),
        innings_sample=record.get("innings_sample"),
        era=record.get("era"),
        xera=record.get("xera"),
        fip=record.get("fip"),
        whip=record.get("whip"),
        k_per9=record.get("k_per9"),
        bb_per9=record.get("bb_per9"),
        hr_per9=record.get("hr_per9"),
        xwoba_allowed=record.get("xwoba_allowed"),
        days_rest=record.get("days_rest"),
        velocity_delta_last3=record.get("velocity_delta_last3"),
        pitch_count_last_start=record.get("pitch_count_last_start"),
        missing_features=list(record.get("missing_features", [])),
    )


def _empty_record(pitcher_id: int | None, pitcher_name: str | None) -> dict:
    record: dict = {"pitcher_id": pitcher_id, "pitcher_name": pitcher_name}
    record.update({f: None for f in _FEATURE_FIELDS})
    record["missing_features"] = list(_FEATURE_FIELDS)
    return record


def _derive_statcast_features(pitch_log: Any, game_date: str) -> dict:
    """
    Statcast-derived workload features.  PREGAME-ONLY: every row dated on
    or after ``game_date`` is dropped before any aggregation, so a feed
    that leaks same-day or future pitches cannot contaminate features.
    """
    out: dict = {
        "xwoba_allowed": None,
        "days_rest": None,
        "velocity_delta_last3": None,
        "pitch_count_last_start": None,
    }
    if pitch_log is None or getattr(pitch_log, "empty", True):
        return out
    if "game_date" not in pitch_log.columns:
        return out

    try:
        import pandas as pd  # noqa: PLC0415

        df = pitch_log.copy()
        df["game_date"] = pd.to_datetime(df["game_date"])
        cutoff = pd.Timestamp(game_date)
        df = df[df["game_date"] < cutoff]  # strictly before first pitch
        if df.empty:
            return out

        game_dates = sorted(df["game_date"].unique())
        last_game = game_dates[-1]
        out["days_rest"] = int((cutoff - last_game).days)
        out["pitch_count_last_start"] = int((df["game_date"] == last_game).sum())

        if "estimated_woba_using_speedangle" in df.columns:
            xwoba = df["estimated_woba_using_speedangle"].dropna()
            if len(xwoba) > 0:
                out["xwoba_allowed"] = round(float(xwoba.mean()), 4)

        if "release_speed" in df.columns and "pitch_type" in df.columns:
            fb = df[df["pitch_type"].isin(_FASTBALL_TYPES)].dropna(
                subset=["release_speed"]
            )
            if len(fb) > 0:
                season_velo = float(fb["release_speed"].mean())
                last3 = fb[fb["game_date"].isin(game_dates[-3:])]
                if len(last3) > 0:
                    out["velocity_delta_last3"] = round(
                        float(last3["release_speed"].mean()) - season_velo, 3
                    )
    except Exception as exc:
        logger.warning("Statcast feature derivation failed: %s", exc)
    return out


# ---------------------------------------------------------------------------
# Derived feature cache (daily, separate from raw source cache)
# ---------------------------------------------------------------------------

def _feature_cache_file(cache_dir: Path, pitcher_id: int, game_date: str) -> Path:
    return cache_dir / f"starter_{pitcher_id}_{game_date}.json"


def _load_feature_cache(
    cache_dir: Path | None, pitcher_id: int, game_date: str
) -> dict | None:
    if cache_dir is None:
        return None
    path = _feature_cache_file(cache_dir, pitcher_id, game_date)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    # Only honour caches written today: probables and stats move daily.
    if data.get("_cached_on") != str(date_cls.today()):
        return None
    data.pop("_cached_on", None)
    return data


def _write_feature_cache(
    cache_dir: Path | None, pitcher_id: int, game_date: str, record: dict
) -> None:
    if cache_dir is None:
        return
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(record)
        payload["_cached_on"] = str(date_cls.today())
        _feature_cache_file(cache_dir, pitcher_id, game_date).write_text(
            json.dumps(payload), encoding="utf-8"
        )
    except Exception as exc:
        logger.debug("Starter feature cache write failed: %s", exc)
