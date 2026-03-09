"""
Main orchestrator — schedules all engines, routes signals,
applies macro filter, and coordinates execution.
"""
import logging
from alpha.config.settings import Settings
from alpha.signals.macro_filter import MacroFilter

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, verticals: list[str] | None = None):
        self.settings = Settings()
        self.verticals = verticals or self.settings.active_verticals
        self.macro_filter = MacroFilter()
        logger.info(f"Orchestrator initialized with verticals: {self.verticals}")

    def run_cycle(self):
        """
        One full cycle: fetch macro regime → gate → run active engines.
        Called by scheduler (modal cron or scripts/daily_scan.py).
        """
        from alpha.data.ingestion.fred import FREDClient

        logger.info("Starting orchestration cycle")
        regime = {}
        try:
            regime = FREDClient().fetch_macro_regime()
            label = self.macro_filter.get_label(regime)
            scalar = self.macro_filter.get_position_scalar(regime)
            logger.info(f"Macro regime: {label} | position scalar: {scalar}")
        except Exception as e:
            logger.warning(f"Macro fetch failed, assuming risk_on: {e}")
            scalar = 1.0

        for vertical in self.verticals:
            try:
                self._run_vertical(vertical, position_scalar=scalar)
            except Exception as e:
                logger.error(f"Vertical {vertical} failed: {e}", exc_info=True)

    def _run_vertical(self, vertical: str, position_scalar: float = 1.0):
        """Dispatch to individual engine. Engines added in Milestone 2."""
        logger.info(f"Running vertical: {vertical} (scalar={position_scalar})")
        # TODO: wire engines in Milestone 2
