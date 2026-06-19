"""
WC 2026 same-game parlay builder. Uses WCMatchModel predict() output fields directly.

In v1.1, only CLASSIC_PARLAY mode is supported (no player prop legs for WC).
SGP-02: Draw legs are never included in any parlay combination — WC knockout rounds
have no Draw outcome, and even in group stage Draw legs are excluded (illiquid market).

Reuses ParlayCombination and SGPMode from soccer_sgp_builder to avoid duplication.
"""
from __future__ import annotations

import itertools
import logging

from alpha.engines.sports.ev_calculator import EVCalculator
from alpha.engines.sports.kelly import KellySizer
from alpha.engines.sports.soccer_sgp_builder import ParlayCombination, SGPMode

logger = logging.getLogger(__name__)

_EV_CALC = EVCalculator(min_edge=0.0)
_KELLY = KellySizer(kelly_fraction=0.25, max_stake_pct=0.05)


class WCSGPBuilder:
    """
    Classic parlay builder for WC 2026 match outcome bets.

    Consumes enriched game dicts from WCMatchModel.predict().
    Only Win/Advance legs are generated — no Draw legs in any stage.
    """

    def __init__(
        self,
        bankroll: float = 10_000.0,
        min_edge: float = 0.05,
        max_legs: int = 4,
    ) -> None:
        self._bankroll = bankroll
        self._min_edge = min_edge
        self._max_legs = max_legs

    def build(self, ml_games: list[dict], top_n: int = 5) -> list[ParlayCombination]:
        """
        Generate, score, and rank classic parlay combinations from enriched WC game dicts.

        Args:
            ml_games: List of game dicts already enriched by WCMatchModel.predict().
                      Must contain win_prob, home_odds, elo_edge, knockout fields.
            top_n:    Maximum number of combinations to return.

        Returns:
            Sorted list of ParlayCombination objects with edge >= min_edge.
        """
        combos = self._build_classic_parlay(ml_games)
        for combo in combos:
            combo.stake = _KELLY.bet_size(
                win_prob=combo.combined_model_prob,
                decimal_odds=combo.combined_decimal_odds,
                bankroll=self._bankroll,
            )
        positive = [c for c in combos if c.edge >= self._min_edge]
        positive.sort(key=lambda c: c.ev, reverse=True)
        return positive[:top_n]

    def _best_wc_leg(self, game: dict) -> dict | None:
        """
        Build the best Win/Advance leg dict for a WC game.

        Uses game["win_prob"] (home team Win-to-Advance in knockouts, or
        home team Win probability in group stage).

        SGP-02: Draw legs are NEVER generated here — not for knockouts
        (invalid), not for group stage (illiquid, excluded by design).
        """
        win_prob = game.get("win_prob", 0.5)
        if win_prob <= 0.0:
            return None
        home_odds = game.get("home_odds", -110)
        home_dec = _EV_CALC.american_to_decimal(home_odds)
        return {
            "type": "wc_ml",
            "team": game.get("home_team", ""),
            "model_prob": win_prob,
            "decimal_odds": home_dec,
            "event_id": game.get("event_id", ""),
            "home_team": game.get("home_team", ""),
            "away_team": game.get("away_team", ""),
            "elo_edge": game.get("elo_edge", False),
            "knockout": game.get("knockout", False),
            "home_elo": game.get("home_elo", 1500),
        }

    def _build_classic_parlay(self, ml_games: list[dict]) -> list[ParlayCombination]:
        """Build all valid n-leg classic parlay combinations from WC games."""
        if len(ml_games) < 2:
            return []

        ml_legs = [self._best_wc_leg(g) for g in ml_games]
        ml_legs = [leg for leg in ml_legs if leg is not None]

        if len(ml_legs) < 2:
            return []

        results: list[ParlayCombination] = []
        for n in range(2, min(self._max_legs, len(ml_legs)) + 1):
            for combo in itertools.combinations(ml_legs, n):
                combined_model = 1.0
                combined_market = 1.0
                combined_odds = 1.0
                for leg in combo:
                    dec_odds = leg["decimal_odds"]
                    combined_model *= leg["model_prob"]
                    combined_market *= _EV_CALC.implied_prob(dec_odds)
                    combined_odds *= dec_odds

                ev = _EV_CALC.expected_value(combined_model, combined_odds)
                edge = combined_model - combined_market
                results.append(ParlayCombination(
                    legs=list(combo),
                    mode=SGPMode.CLASSIC_PARLAY,
                    combined_model_prob=round(combined_model, 5),
                    combined_market_prob=round(combined_market, 5),
                    combined_decimal_odds=round(combined_odds, 4),
                    ev=round(ev, 4),
                    edge=round(edge, 4),
                ))
        return results
