"""
WCHybridModel — wraps WCMatchModel with WCTeamRatings composite Elo injection.

wc_scanner.py can opt into this model with --model hybrid. The default scanner
path remains --model elo for conservative production compatibility.

Design pattern:
    1. WCTeamRatings.get_features() computes composite_home_elo and composite_away_elo
    2. These are injected as home_elo_override / away_elo_override into the game dict
    3. WCMatchModel.predict() uses overrides when present (existing logic unchanged)
    4. model_name is overwritten to "wc_hybrid_baseline" for traceability
"""
from __future__ import annotations

from alpha.engines.sports.wc_model import WCMatchModel
from alpha.engines.sports.wc_ratings import WCTeamRatings


class WCHybridModel:
    """
    Wraps WCMatchModel with hybrid composite Elo injection.

    Uses WCTeamRatings to compute composite Elo per matchup, injects as
    home_elo_override / away_elo_override, then delegates to WCMatchModel.predict().

    The scanner default remains WCMatchModel, but --model hybrid uses this class
    and prints model_name="wc_hybrid_baseline" for traceability.

    Parameters
    ----------
    k_factor : float
        Elo K factor passed to WCTeamRatings. Default 30.0 (WC standard).
    xg_half_life : int
        EWMA half-life for xG states in WCTeamRatings. Default 5 matches.
    min_edge : float
        Minimum edge threshold passed to WCMatchModel. Default 0.04.
    """

    def __init__(
        self,
        k_factor: float = 30.0,
        xg_half_life: int = 5,
        min_edge: float = 0.04,
    ) -> None:
        self._ratings = WCTeamRatings(k_factor=k_factor, xg_half_life=xg_half_life)
        self._base = WCMatchModel(min_edge=min_edge)

    def predict(self, game: dict) -> dict:
        """
        Inject composite Elo overrides, then delegate to WCMatchModel.predict().

        A shallow copy of game is used for injection — the original dict is
        NOT mutated (deviation from WCMatchModel which mutates in place).

        Parameters
        ----------
        game : dict
            WC game dict with at minimum:
                home_team (str), away_team (str), league="wc"

        Returns
        -------
        dict
            Enriched game dict with win_prob, draw_prob, loss_prob, model_name,
            elo_edge, knockout, elo_diff, home_elo, away_elo.
            model_name is always "wc_hybrid_baseline".
        """
        feats = self._ratings.get_features(
            game.get("home_team", ""),
            game.get("away_team", ""),
        )

        # Build fresh copy — do not mutate original
        g = dict(game)
        g["home_elo_override"] = int(round(feats["composite_home_elo"]))
        g["away_elo_override"] = int(round(feats["composite_away_elo"]))

        result = self._base.predict(g)

        # Override model_name for traceability
        result["model_name"] = "wc_hybrid_baseline"
        return result

    def predict_90_minute(self, game: dict) -> dict:
        """
        Inject composite Elo overrides, then delegate to the base 90-minute model.

        This keeps knockout regulation-time W/D/L separate from advance
        probabilities while preserving the hybrid model trace label.
        """
        feats = self._ratings.get_features(
            game.get("home_team", ""),
            game.get("away_team", ""),
        )

        g = dict(game)
        g["home_elo_override"] = int(round(feats["composite_home_elo"]))
        g["away_elo_override"] = int(round(feats["composite_away_elo"]))

        result = self._base.predict_90_minute(g)
        result["model_name"] = "wc_hybrid_baseline"
        return result
