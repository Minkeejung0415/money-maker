"""
Cross-asset position sizer.
Allocates total capital across verticals (stocks/crypto/sports)
and converts weight vectors into dollar positions.
"""


class PositionSizer:
    def __init__(
        self,
        total_capital: float = 100_000.0,
        stocks_pct: float = 0.50,
        crypto_pct: float = 0.30,
        sports_pct: float = 0.20,
    ):
        assert abs(stocks_pct + crypto_pct + sports_pct - 1.0) < 1e-9, \
            "Vertical allocations must sum to 1.0"
        self.total_capital = total_capital
        self._pcts = {
            "stocks": stocks_pct,
            "crypto": crypto_pct,
            "sports": sports_pct,
        }

    def vertical_allocations(self) -> dict[str, float]:
        """Return dollar allocation per vertical."""
        return {v: self.total_capital * pct for v, pct in self._pcts.items()}

    def scale_weights(
        self,
        vertical: str,
        weights: dict[str, float],
        position_scalar: float = 1.0,
    ) -> dict[str, float]:
        """
        Convert a normalized weight dict to dollar positions.

        Args:
            vertical: "stocks", "crypto", or "sports"
            weights: {symbol: weight} where weights sum to ~1.0
            position_scalar: macro risk scalar from MacroFilter

        Returns:
            {symbol: dollar_position}
        """
        vertical_capital = self.vertical_allocations().get(vertical, 0.0)
        deployed = vertical_capital * position_scalar
        return {
            sym: round(w * deployed, 2)
            for sym, w in weights.items()
        }

    def update_capital(self, new_capital: float):
        """Update total capital (called after P&L updates)."""
        self.total_capital = new_capital
