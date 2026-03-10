"""
Main orchestrator — schedules all engines, routes signals,
applies macro filter + risk layer, and coordinates execution.
"""
import logging
from alpha.config.settings import Settings
from alpha.reporting.audit_log import AuditLog
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
        self.audit_log = AuditLog()
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
        from alpha.engines.stocks.engine import StockEngine
        from alpha.execution.broker import AlpacaBroker

        logger.info(f"Stocks engine: scalar={position_scalar}")

        from alpha.data.ingestion.alpha_vantage import AlphaVantageClient  # noqa: PLC0415
        from alpha.config.settings import StocksConfig  # noqa: PLC0415
        import time  # noqa: PLC0415

        engine = StockEngine(
            av_api_key=self.settings.alpha_vantage_api_key,
            fred_api_key=self.settings.fred_api_key,
        )

        stocks_cfg = StocksConfig()
        client = AlphaVantageClient(api_key=self.settings.alpha_vantage_api_key)
        universe_rows: dict[str, list[dict]] = {}
        for i, symbol in enumerate(stocks_cfg.watchlist):
            try:
                rows = client.fetch_daily(symbol, outputsize="compact")
                if rows:
                    universe_rows[symbol] = rows
            except Exception as e:
                logger.warning(f"Failed to fetch {symbol}: {e}")
            # Alpha Vantage free tier: 25 calls/day. Sleep 12 s between calls.
            if i < len(stocks_cfg.watchlist) - 1:
                time.sleep(12)

        if not universe_rows:
            logger.warning("No stock data fetched — stocks vertical skipped")
            return {
                "vertical": "stocks",
                "scalar": position_scalar,
                "positions": {},
                "orders": [],
            }
        engine_result = engine.run_universe(universe_rows, position_scalar=position_scalar)
        weights = engine_result.get("weights", {})
        positions = self.position_sizer.scale_weights("stocks", weights, position_scalar)

        orders: list[dict] = []
        if self.settings.execution_enabled and positions:
            broker = AlpacaBroker()
            for symbol, dollar_amt in positions.items():
                if dollar_amt > 0:
                    order = broker.submit_order(symbol, dollar_amt, "buy")
                    orders.append(order)
                    try:
                        self.audit_log.append(
                            event_type="order",
                            vertical="stocks",
                            symbol=symbol,
                            details=order,
                        )
                    except Exception:
                        logger.error("Failed to append stock order to audit log", exc_info=True)

        return {
            "vertical": "stocks",
            "scalar": position_scalar,
            "positions": positions,
            "orders": orders,
        }

    def _run_crypto(self, position_scalar: float) -> dict:
        """Run crypto engine (data fetching wired in Milestone 6)."""
        from alpha.engines.crypto.engine import CryptoEngine
        from alpha.execution.exchange import CryptoExecutor

        logger.info(f"Crypto engine: scalar={position_scalar}")

        from alpha.data.ingestion.crypto_feeds import fetch_ohlcv  # noqa: PLC0415
        from alpha.config.settings import CryptoConfig  # noqa: PLC0415

        engine = CryptoEngine()
        crypto_cfg = CryptoConfig()
        universe_rows: dict[str, list[dict]] = {}
        for pair in crypto_cfg.pairs:
            try:
                rows = fetch_ohlcv(pair, exchange_id="binance", timeframe="1d", limit=100)
                if rows:
                    universe_rows[pair] = rows
            except Exception as e:
                logger.warning(f"Failed to fetch {pair}: {e}")

        if not universe_rows:
            logger.warning("No crypto data fetched — crypto vertical skipped")
            return {
                "vertical": "crypto",
                "scalar": position_scalar,
                "positions": {},
                "orders": [],
            }
        engine_result = engine.run_universe(universe_rows, position_scalar=position_scalar)
        weights = engine_result.get("weights", {})
        positions = self.position_sizer.scale_weights("crypto", weights, position_scalar)

        orders: list[dict] = []
        if self.settings.execution_enabled and positions:
            executor = CryptoExecutor()
            for symbol, dollar_amt in positions.items():
                if dollar_amt > 0:
                    order = executor.submit_order(symbol, "buy", dollar_amt)
                    orders.append(order)
                    try:
                        self.audit_log.append(
                            event_type="order",
                            vertical="crypto",
                            symbol=symbol,
                            details=order,
                        )
                    except Exception:
                        logger.error("Failed to append crypto order to audit log", exc_info=True)

        return {
            "vertical": "crypto",
            "scalar": position_scalar,
            "positions": positions,
            "orders": orders,
        }

    def _run_sports(self, position_scalar: float) -> dict:
        """Run sports engine (data fetching wired in Milestone 6)."""
        from alpha.engines.sports.engine import SportsEngine
        from alpha.execution.sportsbook import SportsbookExecutor

        logger.info(f"Sports engine: scalar={position_scalar}")

        from alpha.data.ingestion.odds_api import OddsAPIClient  # noqa: PLC0415

        engine = SportsEngine()
        client = OddsAPIClient(api_key=self.settings.odds_api_key)
        games = client.fetch_nba_games()
        if not games:
            logger.warning("No NBA games fetched — sports vertical skipped")
            return {
                "vertical": "sports",
                "scalar": position_scalar,
                "bets": [],
                "orders": [],
            }
        engine_result = engine.run(games, position_scalar=position_scalar)
        bets = engine_result.get("bets", [])

        placed_bets: list[dict] = []
        if self.settings.execution_enabled and bets:
            sportsbook = SportsbookExecutor(paper=self.settings.paper_mode)
            for bet in bets:
                stake = float(bet.get("stake", 0.0))
                if stake <= 0:
                    continue
                event_id = str(bet.get("event_id", ""))
                selection = str(bet.get("bet_side", ""))
                odds = int(bet.get("american_odds", 0))
                placed = sportsbook.place_bet(
                    event_id=event_id,
                    selection=selection,
                    stake_usd=stake,
                    odds=odds,
                )
                placed_bets.append(placed)
                try:
                    self.audit_log.append(
                        event_type="bet",
                        vertical="sports",
                        symbol=event_id,
                        details=placed,
                    )
                except Exception:
                    logger.error("Failed to append sports bet to audit log", exc_info=True)

        return {
            "vertical": "sports",
            "scalar": position_scalar,
            "bets": bets,
            "orders": placed_bets,
        }
