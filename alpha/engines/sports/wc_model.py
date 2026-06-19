"""
Elo-logistic match model for WC 2026. Standalone — never routes through SoccerModel.

Reads from the Phase 5 data layer:
  - wc_elo.py   : Elo ratings per national team (wc_priors.json)
  - wc_stats.py : StatsBomb xG aggregates (wc_stats.pkl)

Produces calibrated W/D/L probabilities for group stage, or Win-to-Advance
probabilities for knockout rounds, with a market divergence flag.
"""
from __future__ import annotations

import logging
import math

from alpha.engines.sports.ev_calculator import EVCalculator
from alpha.data.ingestion.wc_elo import load_wc_elo_ratings, get_elo_rating
from alpha.data.ingestion.wc_stats import get_wc_team_stats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_WC_BASE_DRAW: float = 0.32
"""Maximum draw probability at Elo difference = 0 (historical WC group-stage peak)."""

_WC_MIN_DRAW: float = 0.05
"""Floor draw probability for extreme mismatches on group-stage games."""

_WC_DRAW_SCALE: float = 500.0
"""Elo-points scale factor for exponential decay (500 points yields about 12%)."""

_XG_ELO_SCALE: float = 35.0
"""Elo points per 1 xG/game advantage (StatsBomb modifier)."""

_XG_ADJ_CAP: float = 200.0
"""Cap on StatsBomb xG adjustment (± Elo points)."""

KNOCKOUT_STAGES: frozenset[str] = frozenset({
    "LAST_16",
    "QUARTER_FINALS",
    "SEMI_FINALS",
    "THIRD_PLACE",
    "FINAL",
})
"""Stages where draws are impossible (extra time / penalties decide)."""


def _draw_prob(elo_adj: float) -> float:
    """Return the calibrated group-stage draw probability for an adjusted Elo gap."""
    return max(
        _WC_MIN_DRAW,
        _WC_BASE_DRAW * math.exp(-abs(elo_adj) / _WC_DRAW_SCALE),
    )


# ---------------------------------------------------------------------------
# Model class
# ---------------------------------------------------------------------------

class WCMatchModel:
    """
    Elo-logistic W/D/L model for WC 2026 matches.

    Neutral-venue formula: no +100 home-field boost.
    Optional StatsBomb xG modifier adjusts Elo diff by up to ±200 points.
    Draw suppressed in knockout rounds (stage in KNOCKOUT_STAGES).
    """

    def __init__(self, min_edge: float = 0.04) -> None:
        self.ev_calc = EVCalculator(min_edge=min_edge)
        self._elo_ratings: dict[str, int] = load_wc_elo_ratings()
        # FileNotFoundError propagates — no silent fallback for Elo ratings
        try:
            self._wc_stats: dict[str, dict] = get_wc_team_stats()
        except FileNotFoundError:
            logger.warning("WC stats cache not found — running Elo-only mode")
            self._wc_stats = {}
        logger.info(
            "WCMatchModel loaded %d Elo ratings, %d team stats",
            len(self._elo_ratings),
            len(self._wc_stats),
        )

    def predict(self, game: dict) -> dict:
        """
        Run the Elo-logistic model on a WC game dict.

        Appends model output fields to the input dict (mutates in place) and
        returns it. Raises ValueError if game["league"] != "wc".

        Output fields added:
            win_prob   (float) — home team W probability (or Win-to-Advance)
            draw_prob  (float) — 0.0 in knockout rounds
            loss_prob  (float) — away team W probability
            elo_edge   (bool)  — |win_prob - market_implied| > 0.05
            knockout   (bool)  — True if stage in KNOCKOUT_STAGES
            model_name (str)   — "wc_elo_logistic"
            elo_diff   (float) — adjusted Elo diff used in formula
            home_elo   (int)   — home team raw Elo rating (debug)
            away_elo   (int)   — away team raw Elo rating (debug)
        """
        if game.get("league") != "wc":
            raise ValueError(
                "WC model only accepts WC game dicts (league='wc'). "
                f"Got league={game.get('league')!r}"
            )

        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")

        # 1. Elo ratings (neutral venue — NO +100 home-field boost)
        elo_home = get_elo_rating(home_team, self._elo_ratings)
        elo_away = get_elo_rating(away_team, self._elo_ratings)
        elo_diff = elo_home - elo_away

        # 2. StatsBomb xG modifier (only when both teams present)
        if home_team in self._wc_stats and away_team in self._wc_stats:
            xg_diff = self._wc_stats[home_team]["avg_xG"] - self._wc_stats[away_team]["avg_xG"]
            elo_adj = elo_diff + xg_diff * _XG_ELO_SCALE
            elo_adj = max(-_XG_ADJ_CAP, min(_XG_ADJ_CAP, elo_adj))
        else:
            elo_adj = float(elo_diff)

        # 3. 2-way Elo-logistic probability (Bradley-Terry)
        p_home_2way = 1.0 / (1.0 + 10.0 ** (-elo_adj / 400.0))

        # 4. Stage detection
        stage = game.get("stage", "GROUP_STAGE")
        knockout = stage in KNOCKOUT_STAGES

        # 5. W/D/L decomposition
        if knockout:
            p_draw = 0.0
            p_home = p_home_2way
            p_away = 1.0 - p_home_2way
        else:
            p_draw = _draw_prob(elo_adj)
            p_home = p_home_2way * (1.0 - p_draw)
            p_away = (1.0 - p_home_2way) * (1.0 - p_draw)

        # 6. Market divergence flag (MODEL-04)
        home_odds = game.get("home_odds", -110)
        market_implied = self.ev_calc.implied_prob(
            self.ev_calc.american_to_decimal(home_odds)
        )
        elo_edge = abs(p_home - market_implied) > 0.05

        # 7. Append fields to game dict (mutate input per spec)
        game["win_prob"] = round(p_home, 4)
        game["draw_prob"] = round(p_draw, 4)
        game["loss_prob"] = round(p_away, 4)
        game["elo_edge"] = elo_edge
        game["knockout"] = knockout
        game["model_name"] = "wc_elo_logistic"
        game["elo_diff"] = round(elo_adj, 2)
        game["home_elo"] = elo_home
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
