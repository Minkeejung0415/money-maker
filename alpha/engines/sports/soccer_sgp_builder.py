"""
SoccerSGPBuilder — generates positive-EV Same-Game Parlay combinations
for soccer (EPL + UCL).

Mirrors SGPBuilder exactly with soccer-specific:
  - Static correlation table for common soccer market pairs
  - LOW confidence guard: skip any leg with model_prob < 0.52
  - 4 modes: PROPS_ONLY, MONEYLINE_SGP, MIXED_SGP, CLASSIC_PARLAY

Static correlation table:
  same_team_goals + same_team_shots   → r=0.65
  same_team_goals + opponent_goals    → r=-0.10
  anytime_scorer  + team_win          → r=0.40

(Empirical correlation from FBRef will be added in a later milestone.)
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from alpha.engines.sports.ev_calculator import EVCalculator
from alpha.engines.sports.kelly import KellySizer

logger = logging.getLogger(__name__)

_EV_CALC = EVCalculator(min_edge=0.0)
_KELLY = KellySizer(kelly_fraction=0.25, max_stake_pct=0.05)

# LOW confidence guard
_MIN_MODEL_PROB: float = 0.52

# Static soccer correlation table: (market_a, market_b) -> r
# Keys are (sorted) tuples of market strings.
_STATIC_CORR: dict[tuple[str, str], float] = {
    # Same team: goals and shots positively correlated
    ("player_goals", "player_shots"): 0.65,
    # Goals for both teams (over/under same game) slightly negatively correlated
    ("player_goals", "player_goals"): -0.10,
    # Anytime scorer and team win positively correlated
    ("player_goals", "team_win"): 0.40,
    # Default for same-team assists / goals
    ("player_assists", "player_goals"): 0.30,
    ("player_assists", "player_shots"): 0.25,
}


class SGPMode(Enum):
    PROPS_ONLY     = "props"
    MONEYLINE_SGP  = "ml_sgp"
    MIXED_SGP      = "mixed"
    CLASSIC_PARLAY = "parlay"


@dataclass
class PropLeg:
    player: str
    market: str
    line: float
    model_prob: float
    over_odds: int
    event_id: str
    home_team: str
    away_team: str
    confidence: str       # "HIGH" / "MEDIUM" / "LOW"
    direction: str = "over"


@dataclass
class ParlayCombination:
    legs: list
    mode: SGPMode
    combined_model_prob: float
    combined_market_prob: float
    combined_decimal_odds: float
    ev: float
    edge: float
    correlation_note: str = ""
    stake: float = 0.0
    confidence_summary: str = ""


class SoccerSGPBuilder:
    def __init__(
        self,
        bankroll: float = 10_000.0,
        min_edge: float = 0.05,
        max_legs: int = 4,
    ):
        self._bankroll = bankroll
        self._min_edge = min_edge
        self._max_legs = max_legs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        prop_legs: list[PropLeg],
        ml_games: list[dict] | None = None,
        mode: SGPMode = SGPMode.PROPS_ONLY,
        top_n: int = 5,
    ) -> list[ParlayCombination]:
        """
        Generate, score, and rank parlay combinations.

        LOW confidence guard applied: legs with model_prob < 0.52 or
        confidence == "LOW" are rejected.
        """
        valid_legs = [
            leg for leg in prop_legs
            if leg.confidence != "LOW" and leg.model_prob >= _MIN_MODEL_PROB
        ]
        ml_games = ml_games or []

        if mode == SGPMode.PROPS_ONLY:
            combos = self._build_props_only(valid_legs)
        elif mode == SGPMode.MONEYLINE_SGP:
            combos = self._build_ml_sgp(valid_legs, ml_games)
        elif mode == SGPMode.MIXED_SGP:
            combos = self._build_mixed(valid_legs, ml_games)
        elif mode == SGPMode.CLASSIC_PARLAY:
            combos = self._build_classic_parlay(ml_games)
        else:
            combos = []

        for combo in combos:
            combo.stake = _KELLY.bet_size(
                win_prob=combo.combined_model_prob,
                decimal_odds=combo.combined_decimal_odds,
                bankroll=self._bankroll,
            )

        positive = [c for c in combos if c.edge >= self._min_edge]
        positive.sort(key=lambda c: c.ev, reverse=True)
        return positive[:top_n]

    # ------------------------------------------------------------------
    # Mode builders
    # ------------------------------------------------------------------

    def _build_props_only(self, legs: list[PropLeg]) -> list[ParlayCombination]:
        if len(legs) < 2:
            return []
        results: list[ParlayCombination] = []
        for n_legs in range(2, min(self._max_legs, 4) + 1):
            for combo_legs in itertools.combinations(legs, n_legs):
                event_ids = {leg.event_id for leg in combo_legs}
                if len(event_ids) > 1:
                    continue
                combo = self._score_prop_combo(list(combo_legs), SGPMode.PROPS_ONLY)
                if combo is not None:
                    results.append(combo)
        return results

    def _build_ml_sgp(
        self, prop_legs: list[PropLeg], ml_games: list[dict]
    ) -> list[ParlayCombination]:
        results: list[ParlayCombination] = []
        for game in ml_games:
            event_id = game.get("event_id", "")
            game_legs = [leg for leg in prop_legs if leg.event_id == event_id]
            for n_prop_legs in range(1, min(self._max_legs - 1, 3) + 1):
                for prop_combo in itertools.combinations(game_legs, n_prop_legs):
                    ml_leg = self._best_ml_leg(game)
                    if ml_leg is None:
                        continue
                    all_legs: list[Any] = [ml_leg] + list(prop_combo)
                    combo = self._score_mixed_combo(all_legs, game, SGPMode.MONEYLINE_SGP)
                    if combo is not None:
                        results.append(combo)
        return results

    def _build_mixed(
        self, prop_legs: list[PropLeg], ml_games: list[dict]
    ) -> list[ParlayCombination]:
        results: list[ParlayCombination] = []
        by_event: dict[str, list[PropLeg]] = {}
        for leg in prop_legs:
            by_event.setdefault(leg.event_id, []).append(leg)

        for game in ml_games:
            event_id = game.get("event_id", "")
            game_legs = by_event.get(event_id, [])
            ml_leg = self._best_ml_leg(game)

            for n in range(2, min(self._max_legs, 5) + 1):
                for prop_combo in itertools.combinations(game_legs, n):
                    combo = self._score_prop_combo(list(prop_combo), SGPMode.MIXED_SGP)
                    if combo is not None:
                        results.append(combo)

            if ml_leg is not None:
                for n_prop in range(1, min(self._max_legs - 1, 4) + 1):
                    for prop_combo in itertools.combinations(game_legs, n_prop):
                        all_legs: list[Any] = [ml_leg] + list(prop_combo)
                        combo = self._score_mixed_combo(all_legs, game, SGPMode.MIXED_SGP)
                        if combo is not None:
                            results.append(combo)
        return results

    def _build_classic_parlay(self, ml_games: list[dict]) -> list[ParlayCombination]:
        if len(ml_games) < 2:
            return []
        ml_legs = [self._best_ml_leg(g) for g in ml_games]
        ml_legs = [leg for leg in ml_legs if leg is not None]

        draw_legs = self._build_draw_legs(ml_games)
        all_legs = ml_legs + draw_legs

        results: list[ParlayCombination] = []
        for n in range(2, min(self._max_legs, 4) + 1):
            for combo in itertools.combinations(all_legs, n):
                # Same-game guard: skip combos that pair draw + win from the same game
                event_ids_by_type: dict[str, set[str]] = {}
                for leg in combo:
                    leg_type = leg.get("type", "ml")
                    eid = leg.get("event_id", "")
                    event_ids_by_type.setdefault(leg_type, set()).add(eid)
                draw_eids = event_ids_by_type.get("draw", set())
                ml_eids = event_ids_by_type.get("ml", set())
                if draw_eids & ml_eids:
                    continue  # same game contributes draw + win — illogical

                combined_model = 1.0
                combined_market = 1.0
                combined_odds = 1.0
                for leg in combo:
                    dec_odds = leg["decimal_odds"]
                    combined_model  *= leg["model_prob"]
                    combined_market *= _EV_CALC.implied_prob(dec_odds)
                    combined_odds   *= dec_odds

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

    def _build_draw_legs(self, ml_games: list[dict]) -> list[dict]:
        """
        Build draw-market legs for games that pass the D-11 gate:
          1. model_name must not be None or "market_implied"
          2. draw_prob must be > 0
          3. draw EV (using draw_odds) must be > 0.05

        Returns a list of leg dicts with is_draw=True for scanner annotation.
        """
        draw_legs: list[dict] = []
        for game in ml_games:
            # Gate 1: model must be a real predictive model (D-11)
            model_name = game.get("model_name")
            if model_name in (None, "market_implied"):
                continue

            # Gate 2: draw probability must be present and positive
            draw_prob = game.get("draw_prob")
            if draw_prob is None or draw_prob <= 0:
                continue

            # Gate 3: EV must exceed 5% threshold
            draw_odds_raw = game.get("draw_odds", 300)  # default +300 american
            draw_dec = _EV_CALC.american_to_decimal(draw_odds_raw)
            draw_ev = _EV_CALC.expected_value(draw_prob, draw_dec)
            if draw_ev <= 0.05:
                continue

            draw_legs.append({
                "type": "draw",
                "team": "Draw",
                "model_prob": draw_prob,
                "decimal_odds": draw_dec,
                "event_id": game.get("event_id", ""),
                "home_team": game.get("home_team", ""),
                "away_team": game.get("away_team", ""),
                "is_draw": True,
            })
        return draw_legs

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    def _score_prop_combo(
        self, legs: list[PropLeg], mode: SGPMode
    ) -> ParlayCombination | None:
        if len(legs) < 2:
            return None

        combined_model = 1.0
        for i, leg in enumerate(legs):
            combined_model *= leg.model_prob
            # Apply pairwise correlation adjustment
            for j in range(i + 1, len(legs)):
                r = self._get_correlation(leg, legs[j])
                if r != 0.0:
                    # Simple Gaussian copula approximation: multiply by (1 + r * adj)
                    adj_factor = 1.0 + r * 0.05  # conservative dampening
                    combined_model *= adj_factor

        combined_model = max(0.0001, min(combined_model, 0.9999))

        combined_market = 1.0
        combined_odds = 1.0
        for leg in legs:
            dec = _EV_CALC.american_to_decimal(leg.over_odds)
            combined_market *= _EV_CALC.implied_prob(dec)
            combined_odds   *= dec

        ev   = _EV_CALC.expected_value(combined_model, combined_odds)
        edge = combined_model - combined_market
        corr_note = self._build_corr_note(legs)
        conf_str = self._confidence_summary(legs)

        return ParlayCombination(
            legs=legs,
            mode=mode,
            combined_model_prob=round(combined_model, 5),
            combined_market_prob=round(combined_market, 5),
            combined_decimal_odds=round(combined_odds, 4),
            ev=round(ev, 4),
            edge=round(edge, 4),
            correlation_note=corr_note,
            confidence_summary=conf_str,
        )

    def _score_mixed_combo(
        self, all_legs: list[Any], game: dict, mode: SGPMode
    ) -> ParlayCombination | None:
        combined_model = 1.0
        combined_market = 1.0
        combined_odds = 1.0

        prop_legs_only: list[PropLeg] = []
        ml_legs_only: list[dict] = []

        for leg in all_legs:
            if isinstance(leg, PropLeg):
                dec = _EV_CALC.american_to_decimal(leg.over_odds)
                combined_market *= _EV_CALC.implied_prob(dec)
                combined_odds   *= dec
                prop_legs_only.append(leg)
            else:
                model_p = leg.get("model_prob", 0.5)
                dec_odds = leg.get("decimal_odds", 2.0)
                combined_model  *= model_p
                combined_market *= _EV_CALC.implied_prob(dec_odds)
                combined_odds   *= dec_odds
                ml_legs_only.append(leg)

        if prop_legs_only:
            prop_joint = 1.0
            for leg in prop_legs_only:
                prop_joint *= leg.model_prob
            combined_model *= prop_joint

        corr_note_parts: list[str] = []
        for ml_leg in ml_legs_only:
            team = ml_leg.get("team", "")
            if team:
                for pl in prop_legs_only:
                    if pl.home_team == team or pl.away_team == team:
                        corr_note_parts.append(
                            "ML+player same team: positively correlated"
                        )
                        break

        ev   = _EV_CALC.expected_value(combined_model, combined_odds)
        edge = combined_model - combined_market
        conf_str = self._confidence_summary(prop_legs_only)

        return ParlayCombination(
            legs=all_legs,
            mode=mode,
            combined_model_prob=round(combined_model, 5),
            combined_market_prob=round(combined_market, 5),
            combined_decimal_odds=round(combined_odds, 4),
            ev=round(ev, 4),
            edge=round(edge, 4),
            correlation_note=" ".join(set(corr_note_parts)),
            confidence_summary=conf_str,
        )

    def _best_ml_leg(self, game: dict) -> dict | None:
        home_odds = game.get("home_odds", -110)
        away_odds = game.get("away_odds", -110)
        home_dec = _EV_CALC.american_to_decimal(home_odds)
        away_dec = _EV_CALC.american_to_decimal(away_odds)

        home_prob = game.get("home_model_prob") or _EV_CALC.implied_prob(home_dec)
        away_prob = game.get("away_model_prob") or _EV_CALC.implied_prob(away_dec)

        home_ev = _EV_CALC.expected_value(home_prob, home_dec)
        away_ev = _EV_CALC.expected_value(away_prob, away_dec)

        if home_ev >= away_ev:
            return {
                "type": "ml",
                "team": game.get("home_team", ""),
                "model_prob": home_prob,
                "decimal_odds": home_dec,
                "event_id": game.get("event_id", ""),
                "home_team": game.get("home_team", ""),
                "away_team": game.get("away_team", ""),
            }
        return {
            "type": "ml",
            "team": game.get("away_team", ""),
            "model_prob": away_prob,
            "decimal_odds": away_dec,
            "event_id": game.get("event_id", ""),
            "home_team": game.get("home_team", ""),
            "away_team": game.get("away_team", ""),
        }

    def _get_correlation(self, leg_a: PropLeg, leg_b: PropLeg) -> float:
        """Look up static correlation for a pair of soccer prop legs."""
        key = tuple(sorted([leg_a.market, leg_b.market]))
        return _STATIC_CORR.get(key, 0.0)

    def _build_corr_note(self, legs: list[PropLeg]) -> str:
        if len(legs) < 2:
            return ""
        parts: list[str] = []
        for i in range(len(legs)):
            for j in range(i + 1, len(legs)):
                la, lb = legs[i], legs[j]
                r = self._get_correlation(la, lb)
                if r != 0.0:
                    parts.append(
                        f"{la.player} vs {lb.player}: r={r:.2f}"
                    )
        return "; ".join(parts)

    @staticmethod
    def _confidence_summary(legs: list[PropLeg]) -> str:
        if not legs:
            return ""
        from collections import Counter
        counts = Counter(leg.confidence for leg in legs)
        parts = [f"{v}x {k}" for k, v in sorted(counts.items())]
        return ", ".join(parts)
