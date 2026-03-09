"""
Expected Value (EV) calculator for sports betting markets.

EV formula: EV = p * (odds - 1) - (1 - p)
where p = model's estimated win probability, odds = decimal odds.

Positive EV = edge over the book.
"""


class EVCalculator:
    def __init__(self, min_edge: float = 0.03):
        """
        Args:
            min_edge: Minimum EV required to flag a bet (default 3%).
        """
        self.min_edge = min_edge

    def expected_value(self, model_prob: float, decimal_odds: float) -> float:
        """
        Calculate expected value of a bet.

        Args:
            model_prob: Our estimated probability of winning [0, 1].
            decimal_odds: Decimal odds offered by the book (e.g., 2.0 = even money).

        Returns:
            EV as a fraction of stake. Positive = profitable long-term.
        """
        return model_prob * (decimal_odds - 1) - (1 - model_prob)

    def implied_prob(self, decimal_odds: float) -> float:
        """Convert decimal odds to implied probability."""
        return 1.0 / decimal_odds

    def american_to_decimal(self, american_odds: int | float) -> float:
        """Convert American odds to decimal odds."""
        if american_odds > 0:
            return 1 + american_odds / 100
        else:
            return 1 + 100 / abs(american_odds)

    def has_edge(self, model_prob: float, decimal_odds: float) -> bool:
        """Return True if EV exceeds minimum edge threshold."""
        ev = self.expected_value(model_prob, decimal_odds)
        return ev >= self.min_edge

    def score_opportunity(
        self,
        model_prob: float,
        decimal_odds: float,
        market: str = "",
        book: str = "",
    ) -> dict:
        """Full opportunity assessment for a single market line."""
        ev = self.expected_value(model_prob, decimal_odds)
        return {
            "market": market,
            "book": book,
            "model_prob": round(model_prob, 4),
            "implied_prob": round(self.implied_prob(decimal_odds), 4),
            "decimal_odds": decimal_odds,
            "ev": round(ev, 4),
            "edge": round(ev, 4),
            "bet": self.has_edge(model_prob, decimal_odds),
        }
