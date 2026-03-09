"""
Kelly Criterion position sizer for sports betting.

Full Kelly: f* = (bp - q) / b
where:
  b = decimal_odds - 1  (net odds)
  p = win probability
  q = 1 - p

Fractional Kelly reduces variance at the cost of some EV.
"""


class KellySizer:
    def __init__(
        self,
        kelly_fraction: float = 0.25,
        max_stake_pct: float = 0.05,
    ):
        """
        Args:
            kelly_fraction: Multiplier on full Kelly (0.25 = quarter Kelly).
            max_stake_pct: Hard cap on stake as fraction of bankroll.
        """
        self._kelly_multiplier = kelly_fraction
        self.max_stake_pct = max_stake_pct

    def kelly_fraction(self, win_prob: float, decimal_odds: float) -> float:
        """
        Compute full Kelly fraction (not yet scaled by _kelly_multiplier).
        Returns 0 if no edge.
        """
        b = decimal_odds - 1
        p = win_prob
        q = 1 - p
        f = (b * p - q) / b
        return max(0.0, f)

    def bet_size(
        self,
        win_prob: float,
        decimal_odds: float,
        bankroll: float,
    ) -> float:
        """
        Compute actual stake in dollar terms.
        Applies fractional Kelly and hard max_stake_pct cap.
        """
        full_kelly = self.kelly_fraction(win_prob, decimal_odds)
        fractional = full_kelly * self._kelly_multiplier
        capped = min(fractional, self.max_stake_pct)
        return round(capped * bankroll, 2)

    def size_opportunities(
        self,
        opportunities: list[dict],
        bankroll: float,
    ) -> list[dict]:
        """
        Given a list of {model_prob, decimal_odds, ...} dicts,
        return same list with 'stake' added to each.
        """
        sized = []
        for opp in opportunities:
            stake = self.bet_size(
                win_prob=opp["model_prob"],
                decimal_odds=opp["decimal_odds"],
                bankroll=bankroll,
            )
            sized.append({**opp, "stake": stake})
        return sized
