"""
MLB pregame feature schema, Statcast helpers, and shrinkage priors.

Feature philosophy (mirrors alpha/engines/sports/prop_features.py):
  - Only information knowable BEFORE first pitch.
  - Missing feature values stay None/NaN and are tracked explicitly —
    never silently filled with constants that pretend to be real data.
  - Features are organized in ablation groups and must be adopted group
    by group, each gated on out-of-sample improvement — never all at once.

Statcast 2026 / ABS schema note:
  plate_x, plate_z, sz_top, sz_bot definitions changed in 2026 to align
  with the ABS (automated ball-strike) system.  Zone coordinates from
  pre-2026 and 2026+ seasons are NOT directly comparable.  Always:
    1. add the ``abs_era`` flag (1 when season >= 2026),
    2. normalize zone features WITHIN each era
       (normalize_zone_features_by_era),
  and never mix raw zone coordinates across the boundary.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MLB_FEATURE_SCHEMA_VERSION = "1.0.0"

# First season where Statcast zone coordinates follow the ABS definitions.
ABS_ERA_FIRST_SEASON = 2026

# Statcast zone-coordinate columns affected by the 2026 ABS change.
ZONE_FEATURES = ["plate_x", "plate_z", "sz_top", "sz_bot"]

# Official Statcast fields used by this vertical (exact source names).
STATCAST_FIELDS = [
    "launch_speed",
    "launch_angle",
    "estimated_woba_using_speedangle",
    "release_speed",
    "release_spin",
    "pitcher_days_since_prev_game",
    "n_thruorder_pitcher",
    "stand",
    "p_throws",
    *ZONE_FEATURES,
]

# ---------------------------------------------------------------------------
# Ablation feature groups — adopt in this order, one validated group at
# a time (see docs).  Group names are stable identifiers for reports.
# ---------------------------------------------------------------------------

FEATURE_GROUPS: dict[str, list[str]] = {
    # 1. Starting pitcher quality (per side)
    "starter": [
        "pitcher_confirmed",
        "starter_xera",
        "starter_xwoba_allowed",
        "starter_throws",                  # 'R'/'L'
        "starter_days_since_prev_game",
        "starter_expected_innings",
    ],
    # 2. Lineup / handedness matchup (per side)
    "lineup": [
        "lineup_confirmed",
        "lineup_woba_vs_rhp",
        "lineup_woba_vs_lhp",
    ],
    # 3. Bullpen fatigue & availability (per side)
    "bullpen": [
        "bullpen_ip_last1",
        "bullpen_ip_last3",
        "high_leverage_available",
        "closer_available",
        "bullpen_xera",
    ],
    # 4. Park & weather (game level)
    "park_weather": [
        "park_factor_runs",
        "park_factor_hr",
        "temperature_f",
        "wind_mph_out",                    # +out to CF, -in
        "roof_status",                     # 'open'/'closed'/'dome'
    ],
    # 5. Market consensus (game level) — benchmark/ensemble, kept separate
    "market": [
        "consensus_no_vig_prob",
        "opening_line",
        "current_line",
        "line_movement",
    ],
    # 6. Advanced Statcast contact/stuff quality (per side)
    "statcast_quality": [
        "lineup_avg_launch_speed",
        "lineup_avg_launch_angle",
        "lineup_xwoba_contact",            # estimated_woba_using_speedangle
        "starter_release_speed",
        "starter_release_spin",
        "starter_n_thruorder_decay",
    ],
}

def mlb_feature_group_ablations() -> dict[str, list[str]]:
    """
    Cumulative ablation configurations in the mandated adoption order:
    each step adds ONE feature group on top of the previous step.  A new
    group is kept only if it improves held-out (chronologically later)
    metrics — never adopt all Statcast fields at once.
    """
    order = list(FEATURE_GROUPS)
    configs: dict[str, list[str]] = {}
    cumulative: list[str] = []
    for group in order:
        cumulative = cumulative + [group]
        configs[f"+{group}"] = list(cumulative)
    return configs


# Without these the model must not emit a paper bet (fail closed).
REQUIRED_FOR_BET = [
    "pitcher_confirmed",
    "starter_xera",
    "lineup_woba_vs_rhp",
    "lineup_woba_vs_lhp",
]

# League baselines (documented anchors for relative features and priors —
# these are PRIORS for shrinkage, never silent replacements for missing
# observations).
LEAGUE = {
    "runs_per_game": 4.5,
    "woba": 0.315,
    "xera": 4.20,
    "era": 4.30,
    "xwoba_allowed": 0.315,
    "starter_innings": 5.2,
}


# ---------------------------------------------------------------------------
# Hierarchical shrinkage
# ---------------------------------------------------------------------------

def shrink(observed: float, n: float, prior: float, k: float) -> float:
    """
    Empirical-Bayes shrinkage: weighted average of an observed rate and a
    prior, with pseudo-count k controlling how fast we trust the data.

        shrunk = (n * observed + k * prior) / (n + k)

    Use for small batter samples (k~200 PA), small pitcher samples
    (k~150 BF), handedness splits (k~250 PA — splits stabilize slowly),
    and short recent-form windows (k >= window size).
    """
    if n < 0 or k < 0:
        raise ValueError("n and k must be non-negative")
    if n + k == 0:
        return prior
    return (n * observed + k * prior) / (n + k)


# Default pseudo-counts per quantity (callers may override).
SHRINKAGE_K = {
    "batter_woba": 220.0,            # PA — wOBA stabilizes slowly
    "pitcher_xera": 150.0,           # batters faced
    "handedness_split_woba": 250.0,  # PA within the split
    "recent_form_runs": 25.0,        # games
    "bullpen_xera": 80.0,            # innings
}


def shrink_handedness_split(
    split_woba: float, split_pa: float,
    overall_woba: float, overall_pa: float,
    league_woba: float = LEAGUE["woba"],
) -> float:
    """
    Two-level shrinkage for platoon splits: the split shrinks toward the
    batter's overall wOBA, which itself shrinks toward league average.
    """
    overall_shrunk = shrink(overall_woba, overall_pa, league_woba,
                            SHRINKAGE_K["batter_woba"])
    return shrink(split_woba, split_pa, overall_shrunk,
                  SHRINKAGE_K["handedness_split_woba"])


# ---------------------------------------------------------------------------
# Statcast era handling (2026 ABS change)
# ---------------------------------------------------------------------------

def abs_era(season: int) -> int:
    """1 for seasons under the ABS zone definitions (>= 2026), else 0."""
    return 1 if season >= ABS_ERA_FIRST_SEASON else 0


def add_abs_era_flag(df, season_col: str = "season"):
    """Add the abs_era column to a Statcast DataFrame."""
    out = df.copy()
    out["abs_era"] = out[season_col].map(abs_era)
    return out


def normalize_zone_features_by_era(df, season_col: str = "season"):
    """
    Z-score the zone coordinate columns WITHIN each era so pre-2026 and
    2026+ rows become comparable.  Adds ``<col>_norm`` columns and the
    abs_era flag; raw columns are left untouched (and must not be fed to
    models when rows span the boundary).
    """
    out = add_abs_era_flag(df, season_col)
    for col in ZONE_FEATURES:
        if col not in out.columns:
            continue
        out[f"{col}_norm"] = float("nan")
        for era_val, group in out.groupby("abs_era"):
            std = group[col].std()
            mean = group[col].mean()
            if std and not math.isnan(std) and std > 0:
                out.loc[group.index, f"{col}_norm"] = (group[col] - mean) / std
            else:
                out.loc[group.index, f"{col}_norm"] = 0.0
    return out


def assert_zone_features_era_safe(df, season_col: str = "season") -> None:
    """
    Guard: raise when raw zone coordinates span the 2026 ABS boundary
    without normalized columns present.  Call before training on any
    Statcast frame that includes zone features.
    """
    if not any(col in df.columns for col in ZONE_FEATURES):
        return
    seasons = set(df[season_col].map(abs_era).unique())
    if len(seasons) > 1:
        missing_norm = [c for c in ZONE_FEATURES
                        if c in df.columns and f"{c}_norm" not in df.columns]
        if missing_norm:
            raise ValueError(
                "Statcast frame mixes pre-2026 and 2026+ (ABS) zone "
                f"coordinates without era normalization: {missing_norm}. "
                "Run normalize_zone_features_by_era() first."
            )


# ---------------------------------------------------------------------------
# Statcast aggregation helpers (operate on official-field DataFrames)
# ---------------------------------------------------------------------------

def pitcher_xwoba_allowed(statcast_df, min_bbe: int = 30) -> float | None:
    """
    Mean estimated_woba_using_speedangle over batted-ball events.
    Returns None (fail closed) below min_bbe — caller applies shrinkage
    or treats as missing.
    """
    col = "estimated_woba_using_speedangle"
    if col not in statcast_df.columns:
        return None
    vals = statcast_df[col].dropna()
    if len(vals) < min_bbe:
        return None
    return float(vals.mean())


def times_through_order_decay(statcast_df) -> float | None:
    """
    xwOBA-allowed degradation per time through the order, from
    n_thruorder_pitcher: slope of mean xwOBA across TTO 1->3.
    None when TTO coverage is insufficient.
    """
    need = {"n_thruorder_pitcher", "estimated_woba_using_speedangle"}
    if not need <= set(statcast_df.columns):
        return None
    sub = statcast_df.dropna(subset=list(need))
    sub = sub[sub["n_thruorder_pitcher"].isin([1, 2, 3])]
    means = sub.groupby("n_thruorder_pitcher")["estimated_woba_using_speedangle"].mean()
    if len(means) < 2:
        return None
    ttos = means.index.to_list()
    return float((means.iloc[-1] - means.iloc[0]) / (ttos[-1] - ttos[0]))


# ---------------------------------------------------------------------------
# Per-side pregame feature container
# ---------------------------------------------------------------------------

@dataclass
class TeamSideFeatures:
    """
    Pregame features for ONE side of an MLB game.  None = missing
    (tracked, never defaulted).  Confirmation flags are explicit because
    bets are gated on them.
    """
    team: str
    # starter group
    pitcher_confirmed: bool = False
    starter_name: str | None = None
    starter_xera: float | None = None
    starter_xwoba_allowed: float | None = None
    starter_throws: str | None = None          # 'R' / 'L'
    starter_days_since_prev_game: float | None = None
    starter_expected_innings: float | None = None
    # lineup group
    lineup_confirmed: bool = False
    lineup_woba_vs_rhp: float | None = None
    lineup_woba_vs_lhp: float | None = None
    # bullpen group
    bullpen_ip_last1: float | None = None
    bullpen_ip_last3: float | None = None
    high_leverage_available: bool | None = None
    closer_available: bool | None = None
    bullpen_xera: float | None = None
    # team base rates
    runs_per_game: float | None = None
    # statcast quality group
    lineup_xwoba_contact: float | None = None
    starter_release_speed: float | None = None
    starter_release_spin: float | None = None
    starter_n_thruorder_decay: float | None = None

    def missing(self, names: list[str]) -> list[str]:
        out = []
        for name in names:
            v = getattr(self, name, None)
            if v is None or (name == "pitcher_confirmed" and not v):
                out.append(name)
        return out


@dataclass
class GameContext:
    """Game-level pregame context (park/weather/market)."""
    park_factor_runs: float | None = None      # 1.0 = neutral
    park_factor_hr: float | None = None
    temperature_f: float | None = None
    wind_mph_out: float | None = None
    roof_status: str | None = None             # 'open' / 'closed' / 'dome'
    consensus_no_vig_prob: float | None = None # home side
    opening_line: float | None = None          # American odds, home
    current_line: float | None = None
    missing_tracked: list[str] = field(default_factory=list)

    @property
    def line_movement(self) -> float | None:
        if self.opening_line is None or self.current_line is None:
            return None
        return self.current_line - self.opening_line
