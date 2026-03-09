"""
Stock Engine — main entry point for the stocks vertical.
Ties together: AlphaFactory → Screener → SignalEngine → PortfolioOptimizer.
"""
import logging
import polars as pl
from alpha.engines.stocks.alpha_factory import AlphaFactory
from alpha.engines.stocks.screener import StockScreener
from alpha.engines.stocks.signals import StockSignalEngine
from alpha.engines.stocks.portfolio import PortfolioOptimizer

logger = logging.getLogger(__name__)


class StockEngine:
    def __init__(
        self,
        av_api_key: str | None = None,
        fred_api_key: str | None = None,
        portfolio_method: str = "max_sharpe",
        min_volume: float = 1_000_000,
    ):
        self.signal_engine = StockSignalEngine(av_api_key=av_api_key, fred_api_key=fred_api_key)
        self.alpha_factory = AlphaFactory()
        self.screener = StockScreener(min_volume=min_volume)
        self.portfolio = PortfolioOptimizer()
        self.portfolio_method = portfolio_method

    def analyze_symbol(self, symbol: str, price_rows: list[dict]) -> dict:
        """Run full alpha pipeline on a single symbol."""
        return self.signal_engine.get_signal(price_rows)

    def run_universe(
        self,
        universe_rows: dict[str, list[dict]],
        position_scalar: float = 1.0,
    ) -> dict:
        """
        Run stock engine on a universe of symbols.

        Args:
            universe_rows: {symbol: [price_rows]} dict
            position_scalar: from MacroFilter (1.0 = full, 0.25 = risk-off)

        Returns:
            {signals, weights, regime_scalar}
        """
        signals = {}
        screener_inputs = []

        for symbol, rows in universe_rows.items():
            try:
                sig = self.analyze_symbol(symbol, rows)
                signals[symbol] = sig

                # Build screener input from last row + signal score
                last = rows[-1]
                df = self.signal_engine.build_features(rows)
                last_row = df.tail(1).to_dicts()[0]
                screener_inputs.append({
                    "symbol": symbol,
                    "close": last_row.get("close", 0),
                    "ma_20": last_row.get("ma_20"),
                    "rsi_14": last_row.get("rsi_14"),
                    "return_1d": last_row.get("return_1d"),
                    "volume": last.get("volume", 0),
                    "score": sig["score"],
                })
            except Exception as e:
                logger.warning(f"Failed to analyze {symbol}: {e}")

        # Rank and take top candidates
        ranked = self.screener.rank(screener_inputs)
        buy_candidates = [r["symbol"] for r in ranked if signals.get(r["symbol"], {}).get("action") == "buy"]

        # Compute portfolio weights
        if len(buy_candidates) >= 2:
            try:
                returns_data = {}
                for sym in buy_candidates:
                    rows = universe_rows[sym]
                    closes = [r["close"] for r in rows]
                    returns_data[sym] = [
                        (closes[i] - closes[i-1]) / closes[i-1]
                        for i in range(1, len(closes))
                    ]
                min_len = min(len(v) for v in returns_data.values())
                returns_df = pl.DataFrame({k: v[:min_len] for k, v in returns_data.items()})
                raw_weights = self.portfolio.allocate(returns_df, method=self.portfolio_method)
            except Exception as e:
                logger.warning(f"Portfolio optimization failed, using equal weight: {e}")
                raw_weights = self.portfolio.equal_weight(buy_candidates)
        elif len(buy_candidates) == 1:
            raw_weights = {buy_candidates[0]: 1.0}
        else:
            raw_weights = {}

        # Apply position scalar
        weights = {sym: w * position_scalar for sym, w in raw_weights.items()}

        return {
            "signals": signals,
            "weights": weights,
            "regime_scalar": position_scalar,
        }
