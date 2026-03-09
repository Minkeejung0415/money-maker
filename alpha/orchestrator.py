"""
Main orchestrator — schedules all engines, routes signals,
applies macro filter + risk layer, and coordinates execution.
"""
import logging
from alpha.config.settings import Settings
from alpha.signals.macro_filter import MacroFilter
from alpha.risk.position_sizer import PositionSizer
from alpha.risk.drawdown import DrawdownMonitor
from alpha.risk.exposure import ExposureLimiter

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        verticals: list[str] | None = None,
        total_capital: float = 100_000.0,
    ):
        self.settings = Settings()
        self.verticals = verticals or self.settings.active_verticals
        self.macro_filter = MacroFilter()
        self.position_sizer = PositionSizer(total_capital=total_capital)
        self.drawdown_monitor = DrawdownMonitor(peak_capital=total_capital)
        self.exposure_limiter = ExposureLimiter(total_capital=total_capital)
        logger.info(f"Orchestrator initialized with verticals: {self.verticals}")

    def get_effective_scalar(self, current_capital: float, macro_scalar: float) -> float:
        """Combine macro + drawdown scalars (take the more conservative)."""
        drawdown_scalar = self.drawdown_monitor.get_position_scalar(current_capital)
        return round(min(macro_scalar, drawdown_scalar), 4)

    def run_cycle(self, current_capital: float | None = None):
        """
        One full cycle: fetch macro regime → risk gate → run active engines.
        Called by scheduler (modal cron or scripts/daily_scan.py).
        """
        from alpha.data.ingestion.fred import FREDClient

        if current_capital is None:
            current_capital = self.position_sizer.total_capital

        logger.info("Starting orchestration cycle")
        try:
            regime = FREDClient().fetch_macro_regime()
            label = self.macro_filter.get_label(regime)
            macro_scalar = self.macro_filter.get_position_scalar(regime)
            logger.info(f"Macro regime: {label} | macro scalar: {macro_scalar}")
        except Exception as e:
            logger.warning(f"Macro fetch failed, assuming risk_on: {e}")
            macro_scalar = 1.0

        scalar = self.get_effective_scalar(current_capital, macro_scalar)
        logger.info(f"Effective position scalar: {scalar}")

        results = {}
        for vertical in self.verticals:
            try:
                result = self._run_vertical(vertical, position_scalar=scalar)
                results[vertical] = result
            except Exception as e:
                logger.error(f"Vertical {vertical} failed: {e}", exc_info=True)

        return results

    def _run_vertical(self, vertical: str, position_scalar: float = 1.0) -> dict:
        """Dispatch to individual engine and apply risk limits."""
        logger.info(f"Running vertical: {vertical} (scalar={position_scalar})")

        if vertical == "stocks":
            return self._run_stocks(position_scalar)
        elif vertical == "crypto":
            return self._run_crypto(position_scalar)
        elif vertical == "sports":
            return self._run_sports(position_scalar)
        return {}

    def _run_stocks(self, position_scalar: float) -> dict:
        """Run stocks engine (data fetching wired in Milestone 6)."""
        logger.info(f"Stocks engine: scalar={position_scalar}")
        return {"vertical": "stocks", "scalar": position_scalar, "positions": {}}

    def _run_crypto(self, position_scalar: float) -> dict:
        """Run crypto engine (data fetching wired in Milestone 6)."""
        logger.info(f"Crypto engine: scalar={position_scalar}")
        return {"vertical": "crypto", "scalar": position_scalar, "positions": {}}

    def _run_sports(self, position_scalar: float) -> dict:
        """Run sports engine (data fetching wired in Milestone 6)."""
        logger.info(f"Sports engine: scalar={position_scalar}")
        return {"vertical": "sports", "scalar": position_scalar, "bets": []}
