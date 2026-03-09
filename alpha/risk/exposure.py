"""
Exposure limiter — enforces max position sizes and vertical concentration limits.

Prevents over-concentration in any single asset or vertical,
complementing the drawdown circuit breaker.
"""


class ExposureLimiter:
    def __init__(
        self,
        total_capital: float,
        max_single_pct: float = 0.10,
        max_vertical_pct: float = 0.50,
    ):
        """
        Args:
            total_capital: Current total portfolio value.
            max_single_pct: Max allocation to any single asset (default 10%).
            max_vertical_pct: Max allocation to any single vertical (default 50%).
        """
        self.total_capital = total_capital
        self.max_single_pct = max_single_pct
        self.max_vertical_pct = max_vertical_pct

    @property
    def max_single_position(self) -> float:
        return self.total_capital * self.max_single_pct

    @property
    def max_vertical_exposure(self) -> float:
        return self.total_capital * self.max_vertical_pct

    def check_position(self, symbol: str, size: float) -> bool:
        """Return True if position size is within single-asset limit."""
        return size <= self.max_single_position

    def clip_positions(self, positions: dict[str, float]) -> dict[str, float]:
        """Clip all positions to max_single_position."""
        return {
            sym: min(size, self.max_single_position)
            for sym, size in positions.items()
        }

    def total_exposure(self, positions: dict[str, float]) -> float:
        """Sum all positions (total deployed capital in a vertical)."""
        return sum(positions.values())

    def check_vertical_exposure(self, positions: dict[str, float]) -> bool:
        """Return True if total vertical exposure is within limit."""
        return self.total_exposure(positions) <= self.max_vertical_exposure

    def enforce(self, positions: dict[str, float]) -> dict[str, float]:
        """
        Apply all limits: clip individual positions, then scale down
        proportionally if vertical exposure still exceeds limit.
        """
        clipped = self.clip_positions(positions)
        total = self.total_exposure(clipped)
        if total > self.max_vertical_exposure and total > 0:
            scale = self.max_vertical_exposure / total
            clipped = {sym: round(size * scale, 2) for sym, size in clipped.items()}
        return clipped
