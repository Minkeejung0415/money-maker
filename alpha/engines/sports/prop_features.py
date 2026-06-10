"""
Shared pregame feature builder for NBA player props.

This module is the SINGLE source of feature engineering for:
  - historical training  (scripts/train_xgb_prop_model.py)
  - backtesting
  - live inference       (alpha/engines/sports/prop_model.py)

so the train and inference pipelines cannot drift apart.

Rules:
  - Features may only use information known BEFORE tipoff.
  - The target game's own minutes/stats must never influence whether the
    row is included or what the features are (no selection bias).
  - Missing optional features are NaN (XGBoost handles missing natively);
    they are NEVER silently filled with constants.  Missingness is tracked
    explicitly in ``FeatureResult.missing``.
  - Missing REQUIRED features fail closed (builder returns None).

Schema notes (FEATURE_SCHEMA_VERSION):
  Implemented core features are listed in REQUIRED_FEATURES and
  OPTIONAL_FEATURES.  The following fields from the target schema are
  intentionally DEFERRED because no leak-free historical source exists in
  this repository yet; they must not be approximated with constants:
    starter_status, spread, game_total, team_implied_total,
    role_change_flag, teammates_out_minutes, vacated_usage_proxy,
    and all market-specific extras (fga_per_min_last10, usage_rate_recent,
    opponent_missed_fg_proxy, primary_ball_handler_flag, ...).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import mean, stdev

FEATURE_SCHEMA_VERSION = "2.0.0"

# Exponential decay factor for rolling averages: weight[i] = DECAY ** i
# (index 0 = most recent game).  Mirrors PropModel.DECAY_LAMBDA.
DECAY: float = 0.85

# Minutes threshold for a HISTORY game to count toward rolling rates.
# This is applied to prior games only — never to the target game.
MIN_MINUTES: float = 20.0
MIN_HISTORY_GAMES: int = 5

MARKET_STAT_COL: dict[str, str] = {
    "player_points":   "PTS",
    "player_rebounds": "REB",
    "player_assists":  "AST",
    "player_threes":   "FG3M",
}

# Features the model cannot run without — fail closed when absent.
REQUIRED_FEATURES: list[str] = [
    "roll5_stat_per_min",
    "roll10_stat_per_min",
    "roll20_stat_per_min",
    "roll5_minutes",
    "roll10_minutes",
    "minutes_std_last10",
    "projected_minutes",
    "is_home",
    "rest_days",
    "back_to_back",
    "games_last_4_days",
]

# Known-before-tipoff context that may be unavailable — NaN when missing.
OPTIONAL_FEATURES: list[str] = [
    "opp_def_rtg",
    "opp_pace",
]

ALL_FEATURES: list[str] = REQUIRED_FEATURES + OPTIONAL_FEATURES


@dataclass
class FeatureResult:
    """Built pregame features plus explicit missingness tracking."""
    features: dict[str, float]
    missing: list[str] = field(default_factory=list)
    feature_schema_version: str = FEATURE_SCHEMA_VERSION


def _weighted_avg(values: list[float]) -> float:
    """Exponential-decay weighted average: weight[i] = DECAY ** i."""
    if not values:
        return 0.0
    total_w = total_v = 0.0
    for i, v in enumerate(values):
        w = DECAY ** i
        total_w += w
        total_v += v * w
    return total_v / total_w if total_w > 0 else 0.0


def _to_date(value) -> date | None:
    """Coerce str/datetime/date to a date.  Returns None when unparseable."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def normalize_history_row(row: dict, stat_col: str) -> dict | None:
    """
    Normalize a raw game-log row (nba_api dict or historical CSV row) into
    the canonical {stat, minutes, game_date} shape used by the builder.

    Accepts either nba_api-style keys (PTS / MIN_float / GAME_DATE) or
    historical-CSV keys (pts / min_float / game_date).
    """
    stat = row.get(stat_col, row.get(stat_col.lower()))
    minutes = row.get("MIN_float", row.get("min_float"))
    game_date = _to_date(row.get("GAME_DATE", row.get("game_date")))
    if stat is None or minutes is None or game_date is None:
        return None
    try:
        return {"stat": float(stat), "minutes": float(minutes), "game_date": game_date}
    except (TypeError, ValueError):
        return None


def build_pregame_features(
    history: list[dict],
    market: str,
    game_date: date,
    is_home: bool,
    opp_def_rtg: float | None = None,
    opp_pace: float | None = None,
) -> FeatureResult | None:
    """
    Build the shared pregame feature dict for one (player, game) snapshot.

    Parameters:
        history:    prior games ONLY, sorted newest-first; each row must be
                    normalized via normalize_history_row() — i.e. dicts of
                    {stat, minutes, game_date}.  The target game must NOT
                    be included.
        market:     prop market key (player_points / _rebounds / _assists /
                    _threes).
        game_date:  actual tipoff date of the target game (used for
                    rest_days, back_to_back, games_last_4_days).
        is_home:    explicit home/away flag for the target game.  Callers
                    must resolve this from the schedule — never default it.
        opp_def_rtg/opp_pace: pregame opponent context when available;
                    NaN + tracked as missing otherwise.

    Returns None (fail closed) when the market is unknown or history has
    fewer than MIN_HISTORY_GAMES qualifying games.
    """
    if market not in MARKET_STAT_COL:
        return None

    rows = [r for r in history if r.get("game_date") is not None]
    # History rows are pregame by contract; drop any same-day-or-later rows
    # defensively so future information can never leak in.
    rows = [r for r in rows if r["game_date"] < game_date]
    rows.sort(key=lambda r: r["game_date"], reverse=True)

    qualifying = [r for r in rows if r["minutes"] >= MIN_MINUTES]
    if len(qualifying) < MIN_HISTORY_GAMES:
        return None

    per_min = [r["stat"] / r["minutes"] for r in qualifying]
    minutes_q = [r["minutes"] for r in qualifying]

    # Schedule-derived features use ALL prior games (a 5-minute stint still
    # counts as a game played for fatigue purposes).
    played_dates = [r["game_date"] for r in rows]
    rest_days = (game_date - played_dates[0]).days - 1
    rest_days = max(0, min(10, rest_days))
    games_last_4_days = sum(1 for d in played_dates if 0 < (game_date - d).days <= 4)

    minutes_all = [r["minutes"] for r in rows[:10]]
    minutes_std = stdev(minutes_all) if len(minutes_all) >= 2 else 0.0

    features: dict[str, float] = {
        "roll5_stat_per_min":  _weighted_avg(per_min[:5]),
        "roll10_stat_per_min": _weighted_avg(per_min[:10]),
        "roll20_stat_per_min": _weighted_avg(per_min[:20]),
        "roll5_minutes":  _weighted_avg(minutes_q[:5]),
        "roll10_minutes": _weighted_avg(minutes_q[:10]),
        "minutes_std_last10": minutes_std,
        "projected_minutes": _weighted_avg(minutes_q[:5]),
        "is_home": 1.0 if is_home else 0.0,
        "rest_days": float(rest_days),
        "back_to_back": 1.0 if rest_days == 0 else 0.0,
        "games_last_4_days": float(games_last_4_days),
    }

    missing: list[str] = []
    for name, value in (("opp_def_rtg", opp_def_rtg), ("opp_pace", opp_pace)):
        if value is None:
            features[name] = math.nan
            missing.append(name)
        else:
            features[name] = float(value)

    return FeatureResult(features=features, missing=missing)


def features_to_vector(features: dict[str, float], feature_names: list[str] | None = None) -> list[float]:
    """
    Order a feature dict into the model's expected vector.

    Raises KeyError when a REQUIRED feature is absent (fail closed); missing
    optional features become NaN.
    """
    names = feature_names if feature_names is not None else ALL_FEATURES
    vector: list[float] = []
    for name in names:
        if name in features:
            vector.append(float(features[name]))
        elif name in OPTIONAL_FEATURES:
            vector.append(math.nan)
        else:
            raise KeyError(f"Missing required feature: {name}")
    return vector
