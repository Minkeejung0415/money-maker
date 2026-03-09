"""
Real-time drawdown monitor with circuit breaker.

The circuit breaker halts all new position-opening when drawdown
exceeds max_drawdown_pct. This protects against sequential bad trades.
"""
import logging

logger = logging.getLogger(__name__)


class DrawdownMonitor:
    def __init__(
        self,
        peak_capital: float,
        max_drawdown_pct: float = 0.20,
    ):
        """
        Args:
            peak_capital: Starting / high-water-mark capital.
            max_drawdown_pct: Halt trading when drawdown exceeds this (0.20 = 20%).
        """
        self.peak_capital = peak_capital
        self.max_drawdown_pct = max_drawdown_pct

    def current_drawdown_pct(self, current_capital: float) -> float:
        """Return current drawdown as a fraction (0 = no drawdown)."""
        if self.peak_capital <= 0:
            return 0.0
        dd = (self.peak_capital - current_capital) / self.peak_capital
        return max(0.0, round(dd, 6))

    def is_breaker_triggered(self, current_capital: float) -> bool:
        """Return True if drawdown exceeds max threshold."""
        return self.current_drawdown_pct(current_capital) > self.max_drawdown_pct

    def update(self, current_capital: float):
        """Update high-water mark if current capital is a new peak."""
        if current_capital > self.peak_capital:
            self.peak_capital = current_capital
            logger.info(f"New peak capital: ${self.peak_capital:,.2f}")

    def get_position_scalar(self, current_capital: float) -> float:
        """
        Return a position scalar based on drawdown severity.
        0.0 = circuit breaker triggered (halt trading)
        1.0 = at or near peak (full deployment)
        Linear reduction between 0% and max_drawdown_pct.
        """
        self.update(current_capital)
        if self.is_breaker_triggered(current_capital):
            logger.warning(
                f"Circuit breaker triggered! Drawdown: "
                f"{self.current_drawdown_pct(current_capital):.1%}"
            )
            return 0.0
        dd = self.current_drawdown_pct(current_capital)
        scalar = 1.0 - (dd / self.max_drawdown_pct)
        return round(max(0.0, min(1.0, scalar)), 4)
