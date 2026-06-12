"""
ParlayConstructor — sophisticated betting intelligence layer.

Understands parlay mathematics, correlation, optimal leg counts,
Kelly criterion sizing, and bet type recommendations.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from alpha.engines.sports.ev_calculator import EVCalculator
from alpha.engines.sports.kelly import KellySizer

logger = logging.getLogger(__name__)

_EV_CALC = EVCalculator(min_edge=0.0)

# Displayed messages — exported so output code and tests stay in sync.
RESEARCH_ONLY_FALLBACK_MSG = (
    "RESEARCH ONLY — fallback model is not eligible for real-money recommendations"
)
RESEARCH_ONLY_UNVALIDATED_MSG = "RESEARCH ONLY — model validation incomplete"
DIAGNOSTIC_EDGE_LABEL = "Diagnostic edge only"

# Above this recent low-minute share a pick is not recommendation-eligible.
# Fixed policy constant — never tuned on the current slate.
MAX_LOW_MINUTES_RISK = 0.30


def assess_pick_eligibility(pick: dict) -> tuple[bool, list[str]]:
    """
    Decide whether a standalone prop pick may be presented as an actionable
    wager.  FAIL SAFE: a pick missing safety fields is treated as
    research-only, never as eligible.

    Refusal reasons (stable identifiers):
      fallback_model              source != "xgb"
      model_metadata_missing      model lacks feature-schema metadata, or an
                                  xgb pick arrived without model-side
                                  eligibility info (cannot verify)
      calibration_missing         no held-out validation metrics
      required_features_missing   required live features unavailable
      projected_minutes_unreliable  projected minutes absent or <= 0
      low_minutes_risk_too_high   recent low-minute share above policy max
    """
    reasons: list[str] = []

    def _add(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    source = pick.get("source", "rule_fallback")
    if source != "xgb":
        _add("fallback_model")

    # Model-side verdict travels with the pick.
    for reason in pick.get("refusal_reasons") or []:
        _add(reason)

    # An xgb pick without any model-side eligibility info cannot be
    # verified — refuse rather than trust.
    if source == "xgb" and pick.get("recommendation_eligible") is None:
        _add("model_metadata_missing")

    projected_minutes = pick.get("projected_minutes")
    if projected_minutes is None or projected_minutes <= 0:
        _add("projected_minutes_unreliable")

    low_risk = pick.get("low_minutes_risk")
    if low_risk is not None and low_risk > MAX_LOW_MINUTES_RISK:
        _add("low_minutes_risk_too_high")

    return (not reasons), reasons


def research_banner(refusal_reasons: list[str]) -> str:
    """The banner to display for a non-eligible pick."""
    if "fallback_model" in refusal_reasons:
        return RESEARCH_ONLY_FALLBACK_MSG
    return RESEARCH_ONLY_UNVALIDATED_MSG


@dataclass
class BetRecommendation:
    """A single scored bet (straight or parlay)."""
    bet_type: str                  # "single", "2-leg parlay", "3-leg parlay", etc.
    legs: list[dict]
    combined_win_prob: float
    combined_decimal_odds: float
    ev_per_100: float
    edge: float
    kelly_pct: float
    kelly_stake: float
    implied_prob: float
    correlation_adjusted: bool = False
    warnings: list[str] = field(default_factory=list)


_KELLY_DISPLAY_CAP = 0.05


@dataclass
class PickOutput:
    """Rich output format for a single prop or ML pick."""
    player: str
    description: str               # e.g. "Over 24.5 pts"
    model_confidence: float
    implied_odds_prob: float
    edge: float
    ev_per_100: float
    kelly_pct: float               # raw (uncapped) Kelly fraction
    kelly_stake: float
    flags: dict = field(default_factory=dict)
    # Real-money gating: fail safe — a pick is research-only unless
    # explicitly proven eligible.
    source: str = "rule_fallback"
    recommendation_eligible: bool = False
    refusal_reasons: list = field(default_factory=lambda: ["fallback_model"])

    def format(self, bankroll: float = 10_000.0) -> str:
        lines = [
            f"  {self.player} {self.description}",
            f"    Model confidence:   {self.model_confidence:.1%}",
            f"    Implied odds prob:  {self.implied_odds_prob:.1%}",
        ]

        if not self.recommendation_eligible:
            # Research visibility only: projection/edge shown as
            # diagnostics, no stake, no bet-size, no actionable labels.
            lines.append(
                f"    Edge:               {self.edge:+.1%} ({DIAGNOSTIC_EDGE_LABEL})"
            )
            lines.append(f"    {research_banner(self.refusal_reasons)}")
            if self.refusal_reasons:
                lines.append(f"    Refusal reasons:    {', '.join(self.refusal_reasons)}")
        else:
            display_kelly_pct = min(self.kelly_pct, _KELLY_DISPLAY_CAP)
            display_kelly_dollars = display_kelly_pct * bankroll
            cap_note = ""
            if self.kelly_pct > _KELLY_DISPLAY_CAP:
                cap_note = f"  [capped from {self.kelly_pct:.1%}]"
            lines.append(f"    Edge:               {self.edge:+.1%}")
            lines.append(f"    EV per $100:        ${self.ev_per_100:+.2f}")
            lines.append(
                f"    Kelly stake:        {display_kelly_pct:.1%} of bankroll "
                f"(${display_kelly_dollars:.2f}){cap_note}"
            )

        if self.flags:
            flag_parts = [f"{k}: {v:+.1%}" if isinstance(v, float) else f"{k}: {v}"
                          for k, v in self.flags.items()
                          if v and v != 0 and v != "NONE"]
            if flag_parts:
                lines.append(f"    Flags: [{', '.join(flag_parts)}]")
        return "\n".join(lines)


class ParlayConstructor:
    """
    Builds optimally-sized parlays with full EV/Kelly analysis.
    """

    MIN_COMBINED_WIN_PROB = 0.15
    DEFAULT_MAX_LEGS = 4
    HIGH_CONFIDENCE_THRESHOLD = 0.68

    def __init__(
        self,
        bankroll: float = 10_000.0,
        kelly_fraction: float = 0.25,
        max_legs: int = 4,
        min_edge: float = 0.04,
    ):
        self._bankroll = bankroll
        self._kelly = KellySizer(kelly_fraction=kelly_fraction, max_stake_pct=0.05)
        self._kelly_fraction = kelly_fraction
        self._max_legs = max_legs
        self._min_edge = min_edge

    # ------------------------------------------------------------------
    # Core EV / probability calculations
    # ------------------------------------------------------------------

    @staticmethod
    def true_combined_probability(leg_probs: list[float]) -> float:
        """Product of independent win probabilities."""
        result = 1.0
        for p in leg_probs:
            result *= p
        return result

    @staticmethod
    def combined_decimal_odds(leg_odds: list[float]) -> float:
        """Product of individual decimal odds."""
        result = 1.0
        for o in leg_odds:
            result *= o
        return result

    @staticmethod
    def expected_value(win_prob: float, decimal_odds: float) -> float:
        """EV = (win_prob × payout) - (loss_prob × stake), per $1 stake."""
        return win_prob * (decimal_odds - 1) - (1 - win_prob)

    @staticmethod
    def ev_per_100(win_prob: float, decimal_odds: float) -> float:
        """EV scaled to $100 stake."""
        return ParlayConstructor.expected_value(win_prob, decimal_odds) * 100

    def kelly_fraction_calc(self, win_prob: float, decimal_odds: float) -> float:
        """Full Kelly fraction: f = (bp - q) / b"""
        b = decimal_odds - 1
        p = win_prob
        q = 1 - p
        if b <= 0:
            return 0.0
        f = (b * p - q) / b
        return max(0.0, f) * self._kelly_fraction

    def kelly_stake(self, win_prob: float, decimal_odds: float) -> float:
        return self._kelly.bet_size(win_prob, decimal_odds, self._bankroll)

    # ------------------------------------------------------------------
    # Leg count advisor
    # ------------------------------------------------------------------

    def leg_count_table(self, per_leg_prob: float) -> dict[int, float]:
        """
        Show combined win probability for 1–9 leg parlays at a given
        per-leg confidence level.
        """
        table = {}
        for n in range(1, 10):
            table[n] = round(per_leg_prob ** n, 4)
        return table

    def recommend_max_legs(self, leg_probs: list[float]) -> int:
        """
        Recommend max parlay size based on individual leg confidence.
        Default max = 4 unless all legs > 68% confidence.
        """
        if not leg_probs:
            return 2

        all_high = all(p >= self.HIGH_CONFIDENCE_THRESHOLD for p in leg_probs)
        if all_high and len(leg_probs) > self.DEFAULT_MAX_LEGS:
            return min(len(leg_probs), 6)

        return min(len(leg_probs), self._max_legs)

    def should_split_parlay(
        self, legs: list[dict], max_per_parlay: int = 3
    ) -> list[list[dict]]:
        """
        If >max_per_parlay strong legs, split into separate parlays.
        Returns list of leg groups.
        """
        if len(legs) <= max_per_parlay:
            return [legs]

        sorted_legs = sorted(legs, key=lambda l: l.get("model_prob", 0), reverse=True)
        groups = []
        for i in range(0, len(sorted_legs), max_per_parlay):
            chunk = sorted_legs[i:i + max_per_parlay]
            if len(chunk) >= 2:
                groups.append(chunk)
        return groups

    # ------------------------------------------------------------------
    # Bet type recommendations
    # ------------------------------------------------------------------

    def recommend_bet_types(
        self,
        scored_picks: list[dict],
        correlation_engine=None,
    ) -> list[BetRecommendation]:
        """
        For a set of scored picks, output ranked recommendations:
        1. Best single bet
        2. Best 2-leg parlay
        3. Best 3-leg parlay
        With EV, win probability, and Kelly stake for each.
        """
        if not scored_picks:
            return []

        recommendations: list[BetRecommendation] = []

        # Recommendations are actionable wagers: only recommendation-
        # eligible picks may enter.  Research-only/fallback picks are
        # excluded entirely (no top-N backfill from ineligible picks).
        actionable = [p for p in scored_picks if assess_pick_eligibility(p)[0]]
        if not actionable:
            logger.info(
                "recommend_bet_types: 0/%d picks recommendation-eligible — "
                "no bet recommendations emitted", len(scored_picks),
            )
            return []

        eligible = [p for p in actionable if p.get("edge", 0) >= self._min_edge]
        if not eligible:
            eligible = sorted(actionable, key=lambda p: p.get("ev", 0), reverse=True)[:5]

        # 1. Best single bet
        best_single = max(eligible, key=lambda p: p.get("ev", 0))
        dec_odds = _EV_CALC.american_to_decimal(best_single.get("over_odds", -110))
        win_prob = best_single.get("adjusted_prob", best_single.get("model_prob", 0.5))
        ev = self.ev_per_100(win_prob, dec_odds)
        kelly_pct = self.kelly_fraction_calc(win_prob, dec_odds)

        recommendations.append(BetRecommendation(
            bet_type="single",
            legs=[best_single],
            combined_win_prob=win_prob,
            combined_decimal_odds=dec_odds,
            ev_per_100=round(ev, 2),
            edge=round(win_prob - _EV_CALC.implied_prob(dec_odds), 4),
            kelly_pct=round(kelly_pct, 4),
            kelly_stake=round(kelly_pct * self._bankroll, 2),
            implied_prob=round(_EV_CALC.implied_prob(dec_odds), 4),
        ))

        # 2-leg and 3-leg parlays
        sorted_picks = sorted(eligible, key=lambda p: p.get("ev", 0), reverse=True)

        for n_legs in [2, 3]:
            if len(sorted_picks) < n_legs:
                continue

            best_combo = sorted_picks[:n_legs]
            combo_probs = [
                p.get("adjusted_prob", p.get("model_prob", 0.5)) for p in best_combo
            ]
            combo_odds = [
                _EV_CALC.american_to_decimal(p.get("over_odds", -110)) for p in best_combo
            ]

            if correlation_engine:
                from alpha.engines.sports.sgp_builder import PropLeg
                leg_tuples = [
                    (p.get("adjusted_prob", p.get("model_prob", 0.5)),
                     p.get("player", ""),
                     p.get("market", ""))
                    for p in best_combo
                ]
                combined_prob = correlation_engine.adjust_multi_leg_prob(leg_tuples)
                corr_adjusted = True
            else:
                combined_prob = self.true_combined_probability(combo_probs)
                corr_adjusted = False

            combined_odds_val = self.combined_decimal_odds(combo_odds)
            ev = self.ev_per_100(combined_prob, combined_odds_val)
            kelly_pct = self.kelly_fraction_calc(combined_prob, combined_odds_val)
            implied = _EV_CALC.implied_prob(combined_odds_val)

            warnings = []
            if combined_prob < self.MIN_COMBINED_WIN_PROB:
                warnings.append(
                    f"Combined win probability {combined_prob:.1%} is below 15% — "
                    "unlikely to hit regardless of individual leg quality"
                )

            recommendations.append(BetRecommendation(
                bet_type=f"{n_legs}-leg parlay",
                legs=best_combo,
                combined_win_prob=round(combined_prob, 4),
                combined_decimal_odds=round(combined_odds_val, 4),
                ev_per_100=round(ev, 2),
                edge=round(combined_prob - implied, 4),
                kelly_pct=round(kelly_pct, 4),
                kelly_stake=round(kelly_pct * self._bankroll, 2),
                implied_prob=round(implied, 4),
                correlation_adjusted=corr_adjusted,
                warnings=warnings,
            ))

        # Flag when single bet has higher EV than parlay
        if len(recommendations) >= 2:
            single_ev = recommendations[0].ev_per_100
            for rec in recommendations[1:]:
                if single_ev > rec.ev_per_100:
                    rec.warnings.append(
                        f"Single bet EV (${single_ev:+.2f}) is higher than "
                        f"this parlay (${rec.ev_per_100:+.2f}) — "
                        "straight bet may be better"
                    )

        recommendations.sort(key=lambda r: r.ev_per_100, reverse=True)
        return recommendations

    # ------------------------------------------------------------------
    # Correlated parlay EV
    # ------------------------------------------------------------------

    def correlated_parlay_ev(
        self,
        legs: list[dict],
        correlation_engine=None,
        direction: str = "same",
    ) -> dict:
        """
        Calculate EV for correlated legs (same game, same team).
        direction: "same" = both benefit from team scoring well,
                   "opposite" = one benefits when other doesn't.
        """
        probs = [l.get("model_prob", 0.5) for l in legs]
        odds = [_EV_CALC.american_to_decimal(l.get("over_odds", -110)) for l in legs]

        if correlation_engine:
            leg_tuples = [
                (l.get("model_prob", 0.5), l.get("player", ""), l.get("market", ""))
                for l in legs
            ]
            combined_prob = correlation_engine.adjust_multi_leg_prob(leg_tuples)
        else:
            combined_prob = self.true_combined_probability(probs)

        combined_odds_val = self.combined_decimal_odds(odds)
        ev = self.ev_per_100(combined_prob, combined_odds_val)
        implied = _EV_CALC.implied_prob(combined_odds_val)

        return {
            "combined_prob": round(combined_prob, 4),
            "combined_odds": round(combined_odds_val, 4),
            "ev_per_100": round(ev, 2),
            "edge": round(combined_prob - implied, 4),
            "implied_prob": round(implied, 4),
        }

    # ------------------------------------------------------------------
    # Output formatting
    # ------------------------------------------------------------------

    def format_pick(
        self,
        prop: dict,
        bankroll: float | None = None,
    ) -> str:
        """Format a single prop into the rich output specification."""
        bankroll = bankroll or self._bankroll
        over_odds = prop.get("over_odds", -110)
        dec_odds = _EV_CALC.american_to_decimal(over_odds)
        win_prob = prop.get("adjusted_prob", prop.get("model_prob", 0.5))
        implied = _EV_CALC.implied_prob(dec_odds)
        edge = win_prob - implied
        ev = self.ev_per_100(win_prob, dec_odds)
        kelly_pct = self.kelly_fraction_calc(win_prob, dec_odds)
        kelly_dollars = kelly_pct * bankroll

        market_labels = {
            "player_points": "pts", "player_rebounds": "reb",
            "player_assists": "ast", "player_threes": "3pm",
            "player_steals": "stl", "player_blocks": "blk",
        }
        market_label = market_labels.get(prop.get("market", ""), prop.get("market", ""))
        desc = f"Over {prop.get('line', 0)} {market_label}"

        eligible, refusal_reasons = assess_pick_eligibility(prop)
        if not eligible:
            kelly_pct = 0.0
            kelly_dollars = 0.0

        pick = PickOutput(
            player=prop.get("player", "Unknown"),
            description=desc,
            model_confidence=win_prob,
            implied_odds_prob=implied,
            edge=edge,
            ev_per_100=ev,
            kelly_pct=kelly_pct,
            kelly_stake=kelly_dollars,
            flags=prop.get("flags", {}),
            source=prop.get("source", "rule_fallback"),
            recommendation_eligible=eligible,
            refusal_reasons=refusal_reasons,
        )
        return pick.format(bankroll=bankroll)

    def format_recommendation(self, rec: BetRecommendation) -> str:
        """Format a BetRecommendation for display."""
        display_kelly_pct = min(rec.kelly_pct, _KELLY_DISPLAY_CAP)
        display_kelly_dollars = display_kelly_pct * self._bankroll
        cap_note = ""
        if rec.kelly_pct > _KELLY_DISPLAY_CAP:
            cap_note = f"  [capped from {rec.kelly_pct:.1%}]"

        lines = [
            f"  [{rec.bet_type.upper()}]",
            f"    Win probability:  {rec.combined_win_prob:.1%}",
            f"    Decimal odds:     {rec.combined_decimal_odds:.2f}x",
            f"    EV per $100:      ${rec.ev_per_100:+.2f}",
            f"    Edge:             {rec.edge:+.1%}",
            f"    Kelly stake:      {display_kelly_pct:.1%} of bankroll "
            f"(${display_kelly_dollars:.2f}){cap_note}",
        ]
        for w in rec.warnings:
            lines.append(f"    WARNING: {w}")
        return "\n".join(lines)

    def format_leg_count_table(self, per_leg_prob: float) -> str:
        """Format the leg count probability table for display."""
        table = self.leg_count_table(per_leg_prob)
        lines = [f"  Leg count probability table (per-leg: {per_leg_prob:.0%}):"]
        for n, prob in table.items():
            marker = " <-- recommended max" if n == self.DEFAULT_MAX_LEGS else ""
            lines.append(f"    {n}-leg = {prob:.1%}{marker}")
        return "\n".join(lines)
