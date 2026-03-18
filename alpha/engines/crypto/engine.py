"""
Crypto Engine — main entry point for the crypto vertical.
Ties together: StrategyRunner → WhaleTracker → allocation.
"""
import logging
from alpha.engines.crypto.strategy_runner import CryptoStrategyRunner
from alpha.engines.crypto.whale_tracker import WhaleTracker

logger = logging.getLogger(__name__)


class CryptoEngine:
    def __init__(
        self,
        strategy: str = "ema_crossover",
        whale_threshold: float = 2.5,
    ):
        self.strategy_runner = CryptoStrategyRunner(strategy=strategy)
        self.whale_tracker = WhaleTracker(zscore_threshold=whale_threshold)

    def _price_confirms(
        self, rows: list[dict], direction: str, lookback: int = 3
    ) -> bool:
        """
        Require multi-bar price confirmation before trusting whale signal.

        Research (2026-03-17): single-bar volume anomalies don't reliably
        predict direction. Requiring the price trend over the last `lookback`
        bars to align with the whale direction filters most false positives.
        """
        if len(rows) < lookback + 1:
            return False
        prices = [r.get("close", 0.0) for r in rows[-(lookback + 1):]]
        trend = prices[-1] - prices[0]
        if direction == "bullish":
            return trend > 0
        if direction == "bearish":
            return trend < 0
        return False

    def analyze_symbol(self, symbol: str, rows: list[dict]) -> dict:
        """Combine strategy signal + whale signal into final action."""
        strategy_sig = self.strategy_runner.run(rows)
        whale_sig = self.whale_tracker.get_signal(rows)

        # Whale confirmation: only boost when multi-bar price action agrees.
        # A whale volume spike alone is noisy (per exchange-inflow research).
        score = strategy_sig["score"]
        if whale_sig["whale_detected"] and self._price_confirms(
            rows, whale_sig["direction"]
        ):
            if whale_sig["direction"] == "bullish" and score > 0:
                score = min(1.0, score * 1.3)
            elif whale_sig["direction"] == "bearish" and score < 0:
                score = max(-1.0, score * 1.3)

        score = round(score, 4)
        if score >= 0.2:
            action = "buy"
        elif score <= -0.2:
            action = "sell"
        else:
            action = "hold"

        return {
            "symbol": symbol,
            "action": action,
            "score": score,
            "whale_detected": whale_sig["whale_detected"],
            "whale_direction": whale_sig["direction"],
        }

    def run_universe(
        self,
        universe_rows: dict[str, list[dict]],
        position_scalar: float = 1.0,
    ) -> dict:
        """
        Run crypto engine on a universe of symbols.

        Returns:
            {signals, weights, regime_scalar}
        """
        signals = {}
        buy_symbols = []

        for symbol, rows in universe_rows.items():
            try:
                sig = self.analyze_symbol(symbol, rows)
                signals[symbol] = sig
                if sig["action"] == "buy":
                    buy_symbols.append((symbol, sig["score"]))
            except Exception as e:
                logger.warning(f"Failed to analyze {symbol}: {e}")

        # Allocate proportional to score among buys
        if buy_symbols:
            total_score = sum(s for _, s in buy_symbols)
            if total_score > 0:
                raw_weights = {sym: score / total_score for sym, score in buy_symbols}
            else:
                n = len(buy_symbols)
                raw_weights = {sym: 1.0 / n for sym, _ in buy_symbols}
        else:
            raw_weights = {}

        weights = {sym: w * position_scalar for sym, w in raw_weights.items()}

        return {
            "signals": signals,
            "weights": weights,
            "regime_scalar": position_scalar,
        }
