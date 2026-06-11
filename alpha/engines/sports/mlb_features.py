"""
MLB feature schema for the run model: typed pregame inputs per team side.

Design rules (fail-closed):
  - Never invent a value.  A feature that cannot be sourced stays None and
    its name is recorded in ``missing_features``.
  - Hierarchical shrinkage pulls small-sample rates toward league priors;
    it is only applied when a real observed value exists.
  - All features must be knowable BEFORE first pitch.

FEATURE_SCHEMA_VERSION must be bumped whenever field semantics change so
that logged predictions remain interpretable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FEATURE_SCHEMA_VERSION = "mlb_features_v1"

# ---------------------------------------------------------------------------
# League priors (2023-2025 MLB environment, rounded).  Used ONLY as shrinkage
# targets and neutral factors — never reported as observed values.
# ---------------------------------------------------------------------------
LEAGUE_RUNS_PER_GAME = 4.55
LEAGUE_ERA = 4.30
LEAGUE_XERA = 4.30
LEAGUE_FIP = 4.25
LEAGUE_WHIP = 1.30
LEAGUE_K_PER9 = 8.6
LEAGUE_BB_PER9 = 3.2
LEAGUE_HR_PER9 = 1.20
LEAGUE_XWOBA = 0.320
LEAGUE_WOBA = 0.318
LEAGUE_OBP = 0.317
LEAGUE_SLG = 0.406
LEAGUE_K_RATE = 0.222
LEAGUE_BB_RATE = 0.083

# Shrinkage strength: pseudo-observations of the league prior.  A starter
# with ``k`` innings of track record is weighted 50/50 vs the prior.
DEFAULT_SHRINK_INNINGS = 40.0
DEFAULT_SHRINK_GAMES = 20.0


def shrink_to_prior(
    value: float | None,
    sample_size: float | None,
    prior: float,
    shrink_k: float,
) -> float | None:
    """
    Hierarchical (empirical-Bayes style) shrinkage of an observed rate
    toward a league prior:  (value*n + prior*k) / (n + k).

    Returns None when ``value`` is None — shrinkage never invents data.
    A missing/zero sample size collapses fully to the prior only when an
    observed value exists (value present but unweighted is suspicious, so
    we return the prior rather than trusting it).
    """
    if value is None:
        return None
    n = float(sample_size) if sample_size is not None else 0.0
    if n < 0:
        n = 0.0
    return (float(value) * n + prior * shrink_k) / (n + shrink_k)


@dataclass
class StarterFeatures:
    """Pregame features for one probable starting pitcher."""
    pitcher_id: int | None = None
    pitcher_name: str | None = None
    throws: str | None = None  # "L" / "R"
    starts_sample: int | None = None
    innings_sample: float | None = None
    era: float | None = None
    xera: float | None = None
    fip: float | None = None
    whip: float | None = None
    k_per9: float | None = None
    bb_per9: float | None = None
    hr_per9: float | None = None
    xwoba_allowed: float | None = None
    days_rest: int | None = None
    velocity_delta_last3: float | None = None
    pitch_count_last_start: int | None = None
    missing_features: list[str] = field(default_factory=list)

    _RATE_FIELDS = (
        ("era", LEAGUE_ERA),
        ("xera", LEAGUE_XERA),
        ("fip", LEAGUE_FIP),
        ("whip", LEAGUE_WHIP),
        ("k_per9", LEAGUE_K_PER9),
        ("bb_per9", LEAGUE_BB_PER9),
        ("hr_per9", LEAGUE_HR_PER9),
        ("xwoba_allowed", LEAGUE_XWOBA),
    )

    def shrunk(self, field_name: str) -> float | None:
        """Innings-weighted shrinkage of a rate field toward its league prior."""
        priors = dict(self._RATE_FIELDS)
        if field_name not in priors:
            raise KeyError(f"No shrinkage prior for field {field_name!r}")
        return shrink_to_prior(
            getattr(self, field_name),
            self.innings_sample,
            priors[field_name],
            DEFAULT_SHRINK_INNINGS,
        )


@dataclass
class TeamOffenseFeatures:
    """Pregame team-level offense baseline (lineup-agnostic MVP)."""
    team: str = ""
    runs_per_game_season: float | None = None
    runs_per_game_last10: float | None = None
    woba_season: float | None = None
    obp_season: float | None = None
    slg_season: float | None = None
    k_rate_batting: float | None = None
    bb_rate_batting: float | None = None
    games_sample: int | None = None
    missing_features: list[str] = field(default_factory=list)


@dataclass
class TeamSideFeatures:
    """Everything the run model knows about one side of a game."""
    team: str
    starter: StarterFeatures | None = None
    offense: TeamOffenseFeatures | None = None
    # MVP placeholders — intentionally unsourced for now.  The paper-bet
    # gate must see these in missing features until real feeds exist.
    lineup_confirmed: bool = False
    bullpen_xera: float | None = None

    def all_missing_features(self) -> list[str]:
        """Aggregate missing-feature names with side-component prefixes."""
        missing: list[str] = []
        if self.starter is None:
            missing.append("starter")
        else:
            missing.extend(f"starter.{m}" for m in self.starter.missing_features)
        if self.offense is None:
            missing.append("offense")
        else:
            missing.extend(f"offense.{m}" for m in self.offense.missing_features)
        if not self.lineup_confirmed:
            missing.append("lineup_confirmed")
        if self.bullpen_xera is None:
            missing.append("bullpen_xera")
        return missing


@dataclass
class GameContext:
    """Game-level context shared by both sides."""
    event_id: str
    game_date: str  # YYYY-MM-DD (official date)
    commence_time_utc: str
    home_team: str
    away_team: str
    venue: str | None = None
    doubleheader_flag: bool = False
    probable_pitchers_confirmed: bool = False
    park_factor: float | None = None  # None => neutral, recorded as missing
    weather: dict | None = None  # None => unsourced, recorded as missing

    def missing_context_features(self) -> list[str]:
        missing: list[str] = []
        if self.park_factor is None:
            missing.append("park_factor")
        if self.weather is None:
            missing.append("weather")
        if not self.probable_pitchers_confirmed:
            missing.append("probable_pitchers_confirmed")
        return missing
