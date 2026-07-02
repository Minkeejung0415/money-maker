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
import math
from dataclasses import dataclass
from typing import Mapping

from alpha.data.ingestion.wc_market_odds import WCMarketOdds
from alpha.data.ingestion.wc_stats import get_wc_team_stats
from alpha.engines.sports.ev_calculator import EVCalculator
from alpha.engines.sports.kelly import KellySizer
from alpha.engines.sports.soccer_sgp_builder import ParlayCombination, SGPMode
from alpha.engines.sports.wc_goal_markets import WCScorelineModel

logger = logging.getLogger(__name__)

_EV_CALC = EVCalculator(min_edge=0.0)
_KELLY = KellySizer(kelly_fraction=0.25, max_stake_pct=0.05)


@dataclass(frozen=True)
class WCProbabilityCombination:
    """Probability-only same-game combination with no sportsbook assumptions."""

    legs: list[dict]
    combined_model_prob: float
    fair_decimal_odds: float
    home_team: str
    away_team: str
    redundant: bool = False


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
        team_stats: Mapping[str, Mapping[str, float]] | None = None,
    ) -> None:
        self._bankroll = bankroll
        self._min_edge = min_edge
        self._max_legs = max_legs
        if team_stats is None:
            try:
                team_stats = get_wc_team_stats()
            except FileNotFoundError:
                team_stats = {}
        self._scoreline_model = WCScorelineModel(team_stats)

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

    def build_same_game(
        self,
        games: list[dict],
        market_odds: Mapping[str, WCMarketOdds],
        top_n: int = 5,
    ) -> list[ParlayCombination]:
        """Build 2-3 leg combinations within each individual WC match.

        The model joint is evaluated directly from scoreline cells. Combined
        decimal odds are the product of the supplied standalone market prices;
        callers should replace these with a book's quoted SGP price when one is
        available.
        """
        results: list[ParlayCombination] = []
        for game in games:
            event_key = f"{game.get('home_team', '')}|{game.get('away_team', '')}"
            odds = market_odds.get(event_key)
            if odds is None:
                continue
            distribution_game = game if game.get("tactical_joint_approved") else game.get("tactical_baseline_game", game)
            distribution = self._scoreline_model.build(distribution_game)
            available = dict(odds.prices)
            if not distribution.outcome_available:
                for market in ("home_win", "draw", "away_win"):
                    available.pop(market, None)
            legs = []
            for market, decimal_odds in available.items():
                try:
                    probability = distribution.probability(market)
                except ValueError:
                    continue
                legs.append({
                    "type": "wc_sgp",
                    "market": market,
                    "label": self._market_label(game, market),
                    "model_prob": probability,
                    "decimal_odds": decimal_odds,
                    "event_id": game.get("event_id", event_key),
                    "home_team": game.get("home_team", ""),
                    "away_team": game.get("away_team", ""),
                })
            if len(legs) < 2:
                continue

            max_legs = min(3, self._max_legs, len(legs))
            for leg_count in range(2, max_legs + 1):
                for selected in itertools.combinations(legs, leg_count):
                    markets = [leg["market"] for leg in selected]
                    try:
                        joint_probability = distribution.joint_probability(markets)
                    except ValueError:
                        continue
                    if joint_probability <= 0:
                        continue
                    combined_odds = math.prod(leg["decimal_odds"] for leg in selected)
                    market_probability = _EV_CALC.implied_prob(combined_odds)
                    edge = joint_probability - market_probability
                    if edge < self._min_edge:
                        continue
                    ev = _EV_CALC.expected_value(joint_probability, combined_odds)
                    combo = ParlayCombination(
                        legs=list(selected),
                        mode=SGPMode.MIXED_SGP,
                        combined_model_prob=round(joint_probability, 5),
                        combined_market_prob=round(market_probability, 5),
                        combined_decimal_odds=round(combined_odds, 4),
                        ev=round(ev, 4),
                        edge=round(edge, 4),
                        correlation_note=(
                            "Exact scoreline joint model; displayed odds are the product "
                            "of supplied standalone prices"
                        ),
                    )
                    combo.stake = _KELLY.bet_size(
                        win_prob=joint_probability,
                        decimal_odds=combined_odds,
                        bankroll=self._bankroll,
                    )
                    results.append(combo)
        results.sort(
            key=lambda combo: (combo.ev, combo.combined_model_prob, combo.combined_decimal_odds),
            reverse=True,
        )
        return results[:top_n]

    def build_probability_same_game(
        self,
        games: list[dict],
        top_n: int | None = None,
    ) -> list[WCProbabilityCombination]:
        """Rank every compatible 2-3 leg same-match combination without odds."""
        results: list[WCProbabilityCombination] = []
        for game in games:
            distribution_game = game if game.get("tactical_joint_approved") else game.get("tactical_baseline_game", game)
            distribution = self._scoreline_model.build(distribution_game)
            families = [
                ("over_2_5", "under_2_5"),
                ("btts_yes", "btts_no"),
            ]
            if distribution.outcome_available:
                families.insert(0, ("home_win", "draw", "away_win"))

            available_legs: list[dict] = []
            for family in families:
                for market in family:
                    available_legs.append({
                        "type": "wc_sgp_probability",
                        "market": market,
                        "label": self._market_label(game, market),
                        "model_prob": distribution.probability(market),
                        "event_id": game.get(
                            "event_id",
                            f"{game.get('home_team', '')}|{game.get('away_team', '')}",
                        ),
                        "home_team": game.get("home_team", ""),
                        "away_team": game.get("away_team", ""),
                    })

            for leg_count in range(2, min(3, len(available_legs)) + 1):
                for selected in itertools.combinations(available_legs, leg_count):
                    markets = [leg["market"] for leg in selected]
                    try:
                        probability = distribution.joint_probability(markets)
                    except ValueError:
                        continue
                    if probability <= 0:
                        continue
                    redundant = leg_count > 2 and any(
                        math.isclose(
                            probability,
                            distribution.joint_probability(
                                [leg["market"] for leg in subset]
                            ),
                            abs_tol=1e-10,
                        )
                        for subset in itertools.combinations(selected, leg_count - 1)
                    )
                    results.append(WCProbabilityCombination(
                        legs=list(selected),
                        combined_model_prob=round(probability, 5),
                        fair_decimal_odds=round(1.0 / probability, 3),
                        home_team=str(game.get("home_team", "")),
                        away_team=str(game.get("away_team", "")),
                        redundant=redundant,
                    ))
        results.sort(key=lambda combo: combo.combined_model_prob, reverse=True)
        return results if top_n is None else results[:top_n]

    @staticmethod
    def _market_label(game: Mapping[str, object], market: str) -> str:
        labels = {
            "home_win": f"{game.get('home_team', '')} win (90 min)",
            "draw": "Draw (90 min)",
            "away_win": f"{game.get('away_team', '')} win (90 min)",
            "over_2_5": "Over 2.5 goals",
            "under_2_5": "Under 2.5 goals",
            "btts_yes": "Both teams to score - Yes",
            "btts_no": "Both teams to score - No",
        }
        return labels[market]

    def _best_wc_leg(self, game: dict) -> dict | None:
        """
        Build the best Win/Advance leg dict for a WC game.

        Compares home EV vs away EV and picks whichever has higher expected value
        (mirrors SoccerSGPBuilder._best_ml_leg). This matters when the Elo model
        strongly favors the away team (e.g. Scotland vs Morocco).

        win_prob  = home team W probability (from WCMatchModel.predict)
        loss_prob = away team W probability

        SGP-02: Draw legs are NEVER generated here — not for knockouts
        (invalid), not for group stage (illiquid, excluded by design).
        """
        win_prob = game.get("win_prob", 0.5)    # home team
        loss_prob = game.get("loss_prob", 0.5)  # away team
        home_odds = game.get("home_odds", -110)
        away_odds = game.get("away_odds", -110)
        home_dec = _EV_CALC.american_to_decimal(home_odds)
        away_dec = _EV_CALC.american_to_decimal(away_odds)

        home_ev = _EV_CALC.expected_value(win_prob, home_dec)
        away_ev = _EV_CALC.expected_value(loss_prob, away_dec)

        # Never anchor a parlay on a negative-EV side (mirrors the NBA
        # _best_ml_leg fix): if neither side beats the market, skip the game.
        if max(home_ev, away_ev) <= 0:
            return None

        if home_ev >= away_ev:
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
        return {
            "type": "wc_ml",
            "team": game.get("away_team", ""),
            "model_prob": loss_prob,
            "decimal_odds": away_dec,
            "event_id": game.get("event_id", ""),
            "home_team": game.get("home_team", ""),
            "away_team": game.get("away_team", ""),
            "elo_edge": game.get("elo_edge", False),
            "knockout": game.get("knockout", False),
            "home_elo": game.get("away_elo", 1500),  # use away Elo for display
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
