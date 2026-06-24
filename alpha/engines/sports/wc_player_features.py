"""
wc_player_features.py — Position-specific player feature extraction with
hierarchical shrinkage for WC 2026 model.

Provides:
    - RawPlayerStats: input stats for one data source (club or NT)
    - PlayerFeatureStore: computes blended, shrinkage-adjusted features
      per player-role from club and national-team data

Feature sets per requirement:
    PLAYER-01 CB:     aerial_duel_win_rate, interceptions_p90, errors_to_shot_p90
    PLAYER-02 DM:     ball_recoveries_p90, interceptions_p90, press_resistance, foul_card_rate
    PLAYER-03 CM:     possession_value_added, progressive_passes_p90,
                      progressive_carries_p90, chances_created_p90
    PLAYER-04 Winger: np_xg_p90, xa_p90, key_passes_p90, box_entries_p90, cutbacks_p90
    PLAYER-05 ST:     np_xg_p90, shot_volume_p90, finishing_delta

Hierarchical shrinkage (PLAYER-06, PLAYER-07):
    - NT data shrunk toward club-based prior; sparse NT → mostly club stats
    - nat_weight = (nat_matches / (nat_matches + threshold)) * max_nat_weight
    - Default: threshold=10, max_nat_weight=0.70
    - Result at 0 NT caps = pure club stats (club IS the prior)
    - Result at saturation ≈ 70% NT data, 30% club (configurable)
    - Finishing delta additionally shrunk toward positional mean (0) via
      James-Stein: shrunk = raw * n / (n + finishing_shrinkage_prior)
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Position→feature mapping
# ---------------------------------------------------------------------------

POSITION_FEATURES: dict[str, list[str]] = {
    "CB": [
        "aerial_duel_win_rate",
        "interceptions_p90",
        "errors_to_shot_p90",
    ],
    "DM": [
        "ball_recoveries_p90",
        "interceptions_p90",
        "press_resistance",
        "foul_card_rate",
    ],
    "CM": [
        "possession_value_added",
        "progressive_passes_p90",
        "progressive_carries_p90",
        "chances_created_p90",
    ],
    "W": [
        "np_xg_p90",
        "xa_p90",
        "key_passes_p90",
        "box_entries_p90",
        "cutbacks_p90",
    ],
    "ST": [
        "np_xg_p90",
        "shot_volume_p90",
        "finishing_delta",
    ],
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RawPlayerStats:
    """
    Raw stats for a player from one data source (club season or NT campaign).

    All per-90 stats default to 0. Set only the fields relevant to the
    player's position — `PlayerFeatureStore` will extract position-appropriate
    features automatically.

    Attributes
    ----------
    position : str
        Player role: "CB", "DM", "CM", "W", or "ST".
    matches : int
        Number of matches in this dataset (used for shrinkage weighting).
    aerial_duel_win_rate : float
        Fraction of aerial duels won (CB — 0–1).
    interceptions_p90 : float
        Interceptions per 90 min (CB, DM).
    errors_to_shot_p90 : float
        Defensive errors leading to shots per 90 min (CB — lower is better).
    ball_recoveries_p90 : float
        Ball recoveries per 90 min (DM).
    press_resistance : float
        Proxy for withstanding high press (0–1; DM).
    foul_card_rate : float
        Fouls/cards per 90 min (DM).
    possession_value_added : float
        Net possession value added (CM; in xG-equivalent units).
    progressive_passes_p90 : float
        Progressive passes per 90 min (CM).
    progressive_carries_p90 : float
        Progressive carries per 90 min (CM).
    chances_created_p90 : float
        Chances created per 90 min (CM).
    np_xg_p90 : float
        Non-penalty expected goals per 90 min (W, ST).
    xa_p90 : float
        Expected assists per 90 min (W).
    key_passes_p90 : float
        Key passes per 90 min (W).
    box_entries_p90 : float
        Box entries per 90 min (W).
    cutbacks_p90 : float
        Cutbacks per 90 min (W).
    shot_volume_p90 : float
        Total shots per 90 min (ST).
    finishing_delta : float
        xGOT minus xG per shot (ST) — positive = overperforming xG.
        Shrunk toward 0 by PlayerFeatureStore before output.
    """
    position: str = "CB"
    matches: int = 0
    # CB
    aerial_duel_win_rate: float = 0.0
    interceptions_p90: float = 0.0
    errors_to_shot_p90: float = 0.0
    # DM
    ball_recoveries_p90: float = 0.0
    press_resistance: float = 0.0
    foul_card_rate: float = 0.0
    # CM
    possession_value_added: float = 0.0
    progressive_passes_p90: float = 0.0
    progressive_carries_p90: float = 0.0
    chances_created_p90: float = 0.0
    # Winger
    np_xg_p90: float = 0.0
    xa_p90: float = 0.0
    key_passes_p90: float = 0.0
    box_entries_p90: float = 0.0
    cutbacks_p90: float = 0.0
    # Striker
    shot_volume_p90: float = 0.0
    finishing_delta: float = 0.0


# ---------------------------------------------------------------------------
# Player feature store
# ---------------------------------------------------------------------------

class PlayerFeatureStore:
    """
    Compute blended, shrinkage-adjusted position-specific features.

    Hierarchical shrinkage (PLAYER-06):
        At 0 NT caps, result == club stats (club data IS the prior).
        As NT caps accumulate, NT data gains weight up to max_nat_weight.
        Finishing and shot-stopping shrunk toward positional mean (0).

    Parameters
    ----------
    nat_caps_threshold : int
        NT appearances at which nat_weight reaches ~50% of max_nat_weight.
        Higher values = slower trust build-up. Default 10.
    max_nat_weight : float
        Maximum fraction of NT data in final blend at full saturation.
        Default 0.70 (70% NT / 30% club at ≥ ~40 caps).
        Configurable for backtesting (PLAYER-07).
    finishing_shrinkage_prior : int
        James-Stein prior count for finishing delta shrinkage toward 0.
        Default 10 (= 5 observed matches contributes ~33% of raw delta).
    """

    def __init__(
        self,
        nat_caps_threshold: int = 10,
        max_nat_weight: float = 0.70,
        finishing_shrinkage_prior: int = 10,
    ) -> None:
        self._threshold = nat_caps_threshold
        self._max_nat = max_nat_weight
        self._fin_prior = finishing_shrinkage_prior

    def compute(
        self,
        club_stats: RawPlayerStats,
        nat_stats: RawPlayerStats | None = None,
        nat_matches: int = 0,
    ) -> dict[str, float]:
        """
        Compute blended position-specific features for a player.

        Parameters
        ----------
        club_stats : RawPlayerStats
            Club-season stats (baseline prior). `position` field determines
            which feature set is computed.
        nat_stats : RawPlayerStats, optional
            National-team stats. If None or nat_matches=0, pure club stats used.
        nat_matches : int
            Number of NT appearances (caps) for weighting. 0 = no NT data.

        Returns
        -------
        dict[str, float]
            Position-specific feature dict. Keys match POSITION_FEATURES[position].
        """
        position = club_stats.position
        feature_keys = POSITION_FEATURES.get(position, [])

        nat_weight = self._nat_weight(nat_matches)
        club_weight = 1.0 - nat_weight

        result: dict[str, float] = {}
        for key in feature_keys:
            club_val = getattr(club_stats, key, 0.0)

            # Finishing delta: apply shrinkage toward 0 on the club side
            if key == "finishing_delta":
                club_val = self._shrink_finishing(club_val, club_stats.matches)

            if nat_weight > 0 and nat_stats is not None:
                nat_val = getattr(nat_stats, key, 0.0)
                if key == "finishing_delta":
                    nat_val = self._shrink_finishing(nat_val, nat_matches)
                result[key] = club_weight * club_val + nat_weight * nat_val
            else:
                result[key] = club_val

        return result

    def supported_positions(self) -> list[str]:
        """Return list of supported player positions."""
        return list(POSITION_FEATURES.keys())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _nat_weight(self, nat_matches: int) -> float:
        """
        Bayesian nat-team weight.

        Starts at 0 (no NT data), asymptotes toward max_nat_weight as
        nat_matches grows. Formula: (n / (n + threshold)) * max_nat_weight.

        At n=0:         0.0
        At n=threshold: max_nat_weight / 2
        As n→∞:        max_nat_weight
        """
        if nat_matches == 0:
            return 0.0
        raw = nat_matches / (nat_matches + self._threshold)
        return raw * self._max_nat

    def _shrink_finishing(self, delta: float, n_matches: int) -> float:
        """
        James-Stein shrinkage of finishing delta toward 0 (positional mean).

        shrunk = delta * n / (n + prior)

        With prior=10 and n=5: shrunk = delta * 0.333.
        A raw delta of +0.3 over 5 games → shrunk ≈ +0.10 (much closer to 0).
        """
        if n_matches <= 0:
            return 0.0
        shrink_factor = n_matches / (n_matches + self._fin_prior)
        return delta * shrink_factor
