"""
Elo-logistic match model for UCL. Mirrors WCMatchModel. Uses Club Elo ratings.
No pkl artifact — runtime-computed.

Reads from Phase 12 data layer:
  - club_elo.py : Club Elo ratings from clubelo.com (cached daily)

Produces calibrated W/D/L probabilities with a market divergence flag.
UCL always has a draw possibility (no knockout-suppression for the club model).
"""
from __future__ import annotations

import logging
import math

from alpha.engines.sports.ev_calculator import EVCalculator
from alpha.data.ingestion.club_elo import load_club_elo_ratings, get_club_elo_rating

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_UCL_BASE_DRAW: float = 0.28
"""Maximum draw probability at Elo difference = 0 (UCL base draw rate per D-09)."""

_UCL_MIN_DRAW: float = 0.05
"""Floor draw probability for extreme mismatches."""

_UCL_DRAW_SCALE: float = 500.0
"""Elo-points scale factor for exponential decay (same as WCMatchModel)."""

_UCL_HOME_ADVANTAGE: float = 40.0
"""Elo points added for home team (half of standard 80pt per D-09 — UCL venues)."""


def _draw_prob(elo_adj: float) -> float:
    """Return the calibrated draw probability for an adjusted Elo gap."""
    return max(
        _UCL_MIN_DRAW,
        _UCL_BASE_DRAW * math.exp(-abs(elo_adj) / _UCL_DRAW_SCALE),
    )


# ---------------------------------------------------------------------------
# Model class
# ---------------------------------------------------------------------------

class UCLEloModel:
    """
    Elo-logistic W/D/L model for UEFA Champions League matches.

    Uses Club Elo ratings from clubelo.com with a +40 Elo home advantage.
    Mirrors WCMatchModel exactly, but with UCL-specific constants and Club Elo.
    Draw is always possible (UCL group stage and knockout legs included in scanner).
    """

    def __init__(self, min_edge: float = 0.04) -> None:
        self.ev_calc = EVCalculator(min_edge=min_edge)
        self._elo_ratings: dict[str, float] = load_club_elo_ratings()
        # RuntimeError from load_club_elo_ratings propagates — no silent fallback
        logger.info("UCLEloModel loaded %d Club Elo ratings", len(self._elo_ratings))

    def predict(self, game: dict) -> dict:
        """
        Run the Elo-logistic model on a UCL game dict.

        Appends model output fields to the input dict (mutates in place) and
        returns it. Raises ValueError if game["league"] != "ucl".

        Output fields added:
            win_prob   (float) — home team W probability
            draw_prob  (float) — draw probability (UCL base 0.28 decayed by Elo gap)
            loss_prob  (float) — away team W probability
            elo_edge   (bool)  — |win_prob - market_implied| > 0.05
            model_name (str)   — "ucl_elo_logistic"
            elo_diff   (float) — adjusted Elo diff used in formula (includes +40 home boost)
            home_elo   (float) — home team raw Elo rating (before +40 adjustment)
            away_elo   (float) — away team raw Elo rating
        """
        if game.get("league") != "ucl":
            raise ValueError(
                "UCL model only accepts UCL game dicts (league='ucl'). "
                f"Got league={game.get('league')!r}"
            )

        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")

        # 1. Club Elo ratings (raw, before adjustment)
        elo_home = get_club_elo_rating(home_team, self._elo_ratings)
        elo_away = get_club_elo_rating(away_team, self._elo_ratings)
        elo_diff = elo_home - elo_away

        # 2. Apply +40 Elo home advantage (per D-09)
        elo_adj = float(elo_diff) + _UCL_HOME_ADVANTAGE

        # 3. Bradley-Terry 2-way probability (identical formula to WCMatchModel)
        p_home_2way = 1.0 / (1.0 + 10.0 ** (-elo_adj / 400.0))

        # 4. W/D/L decomposition (no knockout suppression — always 3-way for UCL)
        p_draw = _draw_prob(elo_adj)
        p_home = p_home_2way * (1.0 - p_draw)
        p_away = (1.0 - p_home_2way) * (1.0 - p_draw)

        # 5. Market divergence flag (mirrors WCMatchModel)
        home_odds = game.get("home_odds", -110)
        market_implied = self.ev_calc.implied_prob(
            self.ev_calc.american_to_decimal(home_odds)
        )
        elo_edge = abs(p_home - market_implied) > 0.05

        # 6. Mutate game dict and return (same pattern as WCMatchModel)
        game["win_prob"] = round(p_home, 4)
        game["draw_prob"] = round(p_draw, 4)
        game["loss_prob"] = round(p_away, 4)
        game["elo_edge"] = elo_edge
        game["model_name"] = "ucl_elo_logistic"
        game["elo_diff"] = round(elo_adj, 2)
        game["home_elo"] = elo_home   # raw, before +40 adjustment
        game["away_elo"] = elo_away
        return game

    def evaluate_bet(self, game: dict) -> dict | None:
        """
        Return the enriched game dict if win_prob has positive EV vs market odds,
        else return None.
        """
        game = self.predict(game)
        home_odds = game.get("home_odds", -110)
        home_dec = self.ev_calc.american_to_decimal(home_odds)
        if self.ev_calc.has_edge(game["win_prob"], home_dec):
            return game
        return None

    def evaluate_batch(self, games: list[dict]) -> list[dict | None]:
        """Run evaluate_bet on a list of game dicts."""
        return [self.evaluate_bet(g) for g in games]
