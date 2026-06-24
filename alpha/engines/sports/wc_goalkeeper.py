"""
GoalkeeperModule — dedicated GK submodel for WC match evaluation.

Stored and evaluated separately from generic team defense (xg_defense in
WCTeamRatings). Can be added or removed from the feature set independently.

Features:
  GK-01: Goals prevented vs xGOT, save subtype distribution
  GK-02: Cross claims, crosses-not-claimed, sweeper action counts
  GK-03: GK-CB continuity modifier (fires when pairing differs from last match)
  GK-04: Stored as dedicated submodel, separate from WCTeamRatings.xg_defense

No live data. Phase 30 populates real stats; this module defines the
interface and computes from provided stat dicts.
"""
from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class GKStats:
    """Per-GK performance stats (provided by caller — Phase 30 will use real data)."""

    goals_prevented: float = 0.0
    """goals_prevented = xGOT_faced - goals_conceded. Positive = above-average GK."""

    save_high: float = 0.0
    """Saves on high shots (above-bar line). Higher = better aerial command."""

    save_low: float = 0.0
    """Saves on low shots (low corners). Higher = better reaction saves."""

    save_medium: float = 0.0
    """Saves on medium-height shots."""

    cross_claims: float = 0.0
    """Crosses collected cleanly per 90 min."""

    crosses_not_claimed: float = 0.0
    """Crosses that entered danger zone but GK did not claim."""

    sweeper_actions: float = 0.0
    """Sweeper keeper actions per 90 min (out-of-box interceptions)."""


@dataclass
class GKFeatures:
    """Output of GoalkeeperModule.compute() — features independent of xg_defense."""

    gk_strength: float
    """Composite GK quality score. Positive = above-average; 0 = average; negative = below."""

    goals_prevented_component: float
    """Goals prevented contribution to gk_strength (can be negative)."""

    save_distribution_score: float
    """Weighted save subtype score: high=1.2x, medium=1.0x, low=0.9x (harder to save low)."""

    cross_command_score: float
    """cross_claims / (cross_claims + crosses_not_claimed); 0 if no crosses."""

    sweeper_score: float
    """Normalized sweeper actions (0–1 scale, capped at 5 actions/90)."""

    continuity_modifier: float
    """0.0 if GK and CB1/CB2 unchanged vs last match; −0.1 per change."""


# ---------------------------------------------------------------------------
# GoalkeeperModule
# ---------------------------------------------------------------------------

_MAX_SWEEPER: float = 5.0  # cap for normalization
_GOALS_PREVENTED_SCALE: float = 3.0  # ±1 goal prevented = ±3 strength points
_SAVE_WEIGHTS: dict[str, float] = {"high": 1.2, "medium": 1.0, "low": 0.9}
_CROSS_COMMAND_WEIGHT: float = 10.0
_SWEEPER_WEIGHT: float = 5.0


class GoalkeeperModule:
    """
    Dedicated GK submodel — independent of WCTeamRatings.xg_defense.

    Parameters
    ----------
    last_gk : str | None
        GK name from the last match. Used for continuity check.
    last_cbs : set[str] | None
        CB names from the last match. Used for continuity check.
    """

    def __init__(
        self,
        last_gk: str | None = None,
        last_cbs: set[str] | None = None,
    ) -> None:
        self._last_gk = last_gk
        self._last_cbs: set[str] = last_cbs or set()

    def compute(
        self,
        gk_name: str,
        stats: GKStats,
        cb_names: set[str] | None = None,
    ) -> GKFeatures:
        """
        Compute GK features from provided stats.

        Parameters
        ----------
        gk_name : str
            Starting GK name (for continuity check).
        stats : GKStats
            GK performance stats (real data from Phase 30, or test fixtures).
        cb_names : set[str] | None
            Starting CB names (for continuity check). None = skip.

        Returns
        -------
        GKFeatures
            Dedicated GK feature dict, independent of xg_defense.
        """
        # GK-01: Goals prevented component
        goals_prevented_component = stats.goals_prevented * _GOALS_PREVENTED_SCALE

        # GK-01: Save subtype distribution score (weighted by difficulty)
        total_saves = stats.save_high + stats.save_medium + stats.save_low
        if total_saves > 0:
            save_distribution_score = (
                (stats.save_high * _SAVE_WEIGHTS["high"]
                 + stats.save_medium * _SAVE_WEIGHTS["medium"]
                 + stats.save_low * _SAVE_WEIGHTS["low"])
                / total_saves
                * 10.0  # scale to 0–12 range
            )
        else:
            save_distribution_score = 0.0

        # GK-02: Cross command score
        total_crosses = stats.cross_claims + stats.crosses_not_claimed
        cross_command_score = (
            stats.cross_claims / total_crosses if total_crosses > 0 else 0.0
        ) * _CROSS_COMMAND_WEIGHT

        # GK-02: Sweeper score (capped and normalized)
        sweeper_score = min(stats.sweeper_actions / _MAX_SWEEPER, 1.0) * _SWEEPER_WEIGHT

        # GK-03: Continuity modifier
        continuity_modifier = 0.0
        if self._last_gk is not None:
            if gk_name != self._last_gk:
                continuity_modifier -= 0.1
        if cb_names is not None and self._last_cbs:
            changed_cbs = len(cb_names - self._last_cbs)
            continuity_modifier -= 0.1 * changed_cbs

        # Composite GK strength
        gk_strength = (
            goals_prevented_component
            + save_distribution_score
            + cross_command_score
            + sweeper_score
        )

        return GKFeatures(
            gk_strength=gk_strength,
            goals_prevented_component=goals_prevented_component,
            save_distribution_score=save_distribution_score,
            cross_command_score=cross_command_score,
            sweeper_score=sweeper_score,
            continuity_modifier=continuity_modifier,
        )

    def can_remove_independently(self) -> bool:
        """GK-04: confirm this module is independent of xg_defense."""
        return True
