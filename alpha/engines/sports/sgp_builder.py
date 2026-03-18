"""
SGPBuilder — generates positive-EV Same-Game Parlay combinations.

Takes scored prop legs (from PropModel), generates all valid combinations
for the chosen mode, applies correlation-adjusted probability, computes EV
vs market, filters to positive edge, and ranks by EV.

ACCURACY SAFEGUARDS (enforced in code):
  1. LOW confidence legs are rejected — both here AND before calling this builder.
  2. Correlation adjustment is a bivariate normal copula approximation.
     For N > 3 legs, treat combined_model_prob as a lower bound.
  3. Classic parlay legs are independent (different games) — no correlation engine.
  4. Category diversity cap: max 2 props of the same stat category per parlay.

Modes:
  PROPS_ONLY   : 2–4 props, same game
  MONEYLINE_SGP: ML + 1–3 props, same game
  MIXED_SGP    : 2–5 any combo, same game
  CLASSIC_PARLAY: 2–4 ML bets, different games
"""
from __future__ import annotations

import itertools
import logging
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from alpha.engines.sports.ev_calculator import EVCalculator
from alpha.engines.sports.kelly import KellySizer

logger = logging.getLogger(__name__)

_EV_CALC = EVCalculator(min_edge=0.0)
_KELLY = KellySizer(kelly_fraction=0.25, max_stake_pct=0.05)

_MAX_SAME_CATEGORY = 2

_MARKET_TO_CATEGORY: dict[str, str] = {
    "player_points": "pts",
    "player_rebounds": "reb",
    "player_assists": "ast",
    "player_threes": "pts",
    "player_steals": "stl",
    "player_blocks": "blk",
}

_MARKET_LABELS: dict[str, str] = {
    "player_points": "pts",
    "player_rebounds": "reb",
    "player_assists": "ast",
    "player_threes": "3pm",
    "player_steals": "stl",
    "player_blocks": "blk",
}


def _market_label(market: str) -> str:
    return _MARKET_LABELS.get(market, market)


def _cap_per_player(
    combos: list, max_per_player: int = 2
) -> list:
    """
    Enforce player diversity: each player can appear in at most max_per_player
    combos in the final output.  Combos are already sorted by EV descending,
    so highest-EV combos for each player are preserved.
    """
    player_counts: Counter = Counter()
    result = []
    for combo in combos:
        players_in_combo: set[str] = set()
        for leg in combo.legs:
            if isinstance(leg, PropLeg):
                players_in_combo.add(leg.player)
        # Accept combo if every player in it is still under the cap
        if all(player_counts[p] < max_per_player for p in players_in_combo):
            result.append(combo)
            for p in players_in_combo:
                player_counts[p] += 1
    return result


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
    player_team: str = ""


@dataclass
class ParlayCombination:
    legs: list              # PropLeg or dict (for ML legs)
    mode: SGPMode
    combined_model_prob: float
    combined_market_prob: float
    combined_decimal_odds: float
    ev: float
    edge: float
    correlation_note: str = ""
    stake: float = 0.0
    confidence_summary: str = ""


class SGPBuilder:
    def __init__(
        self,
        correlation_engine=None,
        bankroll: float = 10_000.0,
        min_edge: float = 0.05,
        max_legs: int = 4,
        min_legs: int = 3,
    ):
        self._corr = correlation_engine
        self._bankroll = bankroll
        self._min_edge = min_edge
        self._max_legs = max_legs
        self._min_legs = min_legs

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
        Generate, score, and rank parlay combinations for the given mode.

        Returns top_n combinations sorted by EV descending.
        Always filters out LOW confidence legs before combining.
        Enforces category diversity: max 2 props of the same stat category.
        """
        # Enforce LOW-confidence guard (belt-and-suspenders)
        valid_legs = [leg for leg in prop_legs if leg.confidence != "LOW"]
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

        # Attach Kelly stakes
        for combo in combos:
            combo.stake = _KELLY.bet_size(
                win_prob=combo.combined_model_prob,
                decimal_odds=combo.combined_decimal_odds,
                bankroll=self._bankroll,
            )

        # Filter to positive edge and sort
        positive = [c for c in combos if c.edge >= self._min_edge]
        positive.sort(key=lambda c: c.ev, reverse=True)

        # Apply player diversity cap: max 2 SGPs featuring any single player
        diverse = _cap_per_player(positive, max_per_player=2)

        if top_n and top_n > 0:
            return diverse[:top_n]
        return diverse

    # ------------------------------------------------------------------
    # Category diversity enforcement
    # ------------------------------------------------------------------

    @staticmethod
    def _passes_category_diversity(legs: list[PropLeg]) -> bool:
        """Return True if no stat category appears more than _MAX_SAME_CATEGORY times."""
        cats = [_MARKET_TO_CATEGORY.get(leg.market, leg.market) for leg in legs]
        counts = Counter(cats)
        return all(v <= _MAX_SAME_CATEGORY for v in counts.values())

    @staticmethod
    def _enforce_category_diversity(legs: list[PropLeg]) -> list[PropLeg]:
        """
        Drop the weakest legs in over-represented categories until each
        category has at most _MAX_SAME_CATEGORY legs.
        Preserves diversity across categories.
        """
        by_cat: dict[str, list[PropLeg]] = {}
        for leg in legs:
            cat = _MARKET_TO_CATEGORY.get(leg.market, leg.market)
            by_cat.setdefault(cat, []).append(leg)

        kept: list[PropLeg] = []
        for cat, cat_legs in by_cat.items():
            sorted_legs = sorted(cat_legs, key=lambda l: l.model_prob, reverse=True)
            kept.extend(sorted_legs[:_MAX_SAME_CATEGORY])

        return kept

    # ------------------------------------------------------------------
    # Mode builders
    # ------------------------------------------------------------------

    def _build_props_only(self, legs: list[PropLeg]) -> list[ParlayCombination]:
        """min_legs–4 prop legs from the same game, with category diversity enforced."""
        legs = self._enforce_category_diversity(legs)
        if len(legs) < self._min_legs:
            return []

        results: list[ParlayCombination] = []
        for n_legs in range(self._min_legs, min(self._max_legs, 4) + 1):
            for combo_legs in itertools.combinations(legs, n_legs):
                event_ids = {leg.event_id for leg in combo_legs}
                if len(event_ids) > 1:
                    continue
                if not self._passes_category_diversity(list(combo_legs)):
                    continue
                combo = self._score_prop_combo(list(combo_legs), SGPMode.PROPS_ONLY)
                if combo is not None:
                    results.append(combo)
        return results

    def _build_ml_sgp(
        self, prop_legs: list[PropLeg], ml_games: list[dict]
    ) -> list[ParlayCombination]:
        """ML leg + 1–3 prop legs from the same game, category diversity enforced."""
        results: list[ParlayCombination] = []
        for game in ml_games:
            event_id = game.get("event_id", "")
            game_legs = self._enforce_category_diversity(
                [leg for leg in prop_legs if leg.event_id == event_id]
            )

            for n_prop_legs in range(max(1, self._min_legs - 1), min(self._max_legs - 1, 3) + 1):
                for prop_combo in itertools.combinations(game_legs, n_prop_legs):
                    if not self._passes_category_diversity(list(prop_combo)):
                        continue
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
        """2–5 legs any combo (ML and/or props) from the same game, category diversity enforced."""
        results: list[ParlayCombination] = []
        by_event: dict[str, list[PropLeg]] = {}
        for leg in prop_legs:
            by_event.setdefault(leg.event_id, []).append(leg)

        for game in ml_games:
            event_id = game.get("event_id", "")
            game_legs = self._enforce_category_diversity(by_event.get(event_id, []))
            ml_leg = self._best_ml_leg(game)

            for n in range(self._min_legs, min(self._max_legs, 5) + 1):
                for prop_combo in itertools.combinations(game_legs, n):
                    if not self._passes_category_diversity(list(prop_combo)):
                        continue
                    combo = self._score_prop_combo(list(prop_combo), SGPMode.MIXED_SGP)
                    if combo is not None:
                        results.append(combo)

            if ml_leg is not None:
                for n_prop in range(max(1, self._min_legs - 1), min(self._max_legs - 1, 4) + 1):
                    for prop_combo in itertools.combinations(game_legs, n_prop):
                        if not self._passes_category_diversity(list(prop_combo)):
                            continue
                        all_legs: list[Any] = [ml_leg] + list(prop_combo)
                        combo = self._score_mixed_combo(all_legs, game, SGPMode.MIXED_SGP)
                        if combo is not None:
                            results.append(combo)
        return results

    def _build_classic_parlay(self, ml_games: list[dict]) -> list[ParlayCombination]:
        """2–4 ML bets from different games (independent legs)."""
        if len(ml_games) < 2:
            return []

        ml_legs = [self._best_ml_leg(g) for g in ml_games]
        ml_legs = [leg for leg in ml_legs if leg is not None]

        results: list[ParlayCombination] = []
        for n in range(2, min(self._max_legs, 4) + 1):
            for combo in itertools.combinations(ml_legs, n):
                # Different games → independent, no correlation engine
                # leg["decimal_odds"] is already a decimal value — use directly
                combined_model = 1.0
                combined_market = 1.0
                combined_odds = 1.0
                for leg in combo:
                    dec_odds = leg["decimal_odds"]  # already decimal
                    combined_model  *= leg["model_prob"]
                    combined_market *= _EV_CALC.implied_prob(dec_odds)
                    combined_odds   *= dec_odds

                ev = _EV_CALC.expected_value(combined_model, combined_odds)
                edge = combined_model - combined_market

                conf_str = self._confidence_summary([])  # all ML legs
                result = ParlayCombination(
                    legs=list(combo),
                    mode=SGPMode.CLASSIC_PARLAY,
                    combined_model_prob=round(combined_model, 5),
                    combined_market_prob=round(combined_market, 5),
                    combined_decimal_odds=round(combined_odds, 4),
                    ev=round(ev, 4),
                    edge=round(edge, 4),
                    confidence_summary=conf_str,
                )
                results.append(result)
        return results

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    def _score_prop_combo(
        self, legs: list[PropLeg], mode: SGPMode
    ) -> ParlayCombination | None:
        """Score a combination of prop legs only."""
        if len(legs) < 2:
            return None

        if self._corr is not None:
            leg_tuples = [(leg.model_prob, leg.player, leg.market) for leg in legs]
            combined_model = self._corr.adjust_multi_leg_prob(leg_tuples)
        else:
            combined_model = 1.0
            for leg in legs:
                combined_model *= leg.model_prob

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
        """Score a mix of ML dict legs and PropLeg objects."""
        combined_model = 1.0
        combined_market = 1.0
        combined_odds = 1.0

        prop_legs_only: list[PropLeg] = []
        ml_legs_only: list[dict] = []

        # First pass: separate and accumulate market/odds products
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

        # Apply correlation-adjusted joint prob for prop legs
        if prop_legs_only:
            if self._corr is not None:
                leg_tuples = [(leg.model_prob, leg.player, leg.market) for leg in prop_legs_only]
                prop_joint = self._corr.adjust_multi_leg_prob(leg_tuples)
            else:
                prop_joint = 1.0
                for leg in prop_legs_only:
                    prop_joint *= leg.model_prob
            combined_model *= prop_joint

        # Second pass: build correlation note after all legs collected
        corr_note_parts: list[str] = []
        for ml_leg in ml_legs_only:
            team = ml_leg.get("team", "")
            if team:
                for pl in prop_legs_only:
                    if pl.player_team == team:
                        corr_note_parts.append(
                            "⚠ ML+player same team: positively correlated"
                        )
                        break
                    elif pl.player_team and pl.player_team != team:
                        corr_note_parts.append(
                            "⚠ ML+opposing player: negatively correlated if ML team wins big"
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
        """Return the better side (home/away) of a game as an ML dict leg, or None if no positive EV."""
        home_odds = game.get("home_odds", -110)
        away_odds = game.get("away_odds", -110)
        home_dec = _EV_CALC.american_to_decimal(home_odds)
        away_dec = _EV_CALC.american_to_decimal(away_odds)

        home_prob = game.get("home_model_prob") or _EV_CALC.implied_prob(home_dec)
        away_prob = game.get("away_model_prob") or _EV_CALC.implied_prob(away_dec)

        home_ev = _EV_CALC.expected_value(home_prob, home_dec)
        away_ev = _EV_CALC.expected_value(away_prob, away_dec)

        best_ev = max(home_ev, away_ev)
        if best_ev <= 0:
            return None

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

    def _build_corr_note(self, legs: list[PropLeg]) -> str:
        """Build a human-readable correlation note for prop leg pairs."""
        if self._corr is None or len(legs) < 2:
            return ""
        parts: list[str] = []
        for i in range(len(legs)):
            for j in range(i + 1, len(legs)):
                la, lb = legs[i], legs[j]
                if la.player == lb.player:
                    parts.append(
                        f"{la.player} ({_market_label(la.market)} + "
                        f"{_market_label(lb.market)}): same player — r=0.65 (positive)"
                    )
                    continue
                r = self._corr.get_correlation(la.player, la.market, lb.player, lb.market)
                ct = self._corr.classify(r)
                parts.append(
                    f"{la.player} vs {lb.player}: r={r:.2f} ({ct.value})"
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
