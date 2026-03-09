"""
Crypto strategy runner — built-in signal strategies with optional
freqtrade strategy delegation.

Built-in strategies:
  - ema_crossover: EMA-9 vs EMA-21 crossover
  - rsi_mean_reversion: RSI oversold/overbought reversals
  - momentum: 5d momentum with volume confirmation
"""
import logging
import polars as pl

logger = logging.getLogger(__name__)

STRATEGIES = ("ema_crossover", "rsi_mean_reversion", "momentum")


class CryptoStrategyRunner:
    def __init__(self, strategy: str = "ema_crossover"):
        if strategy not in STRATEGIES:
            raise ValueError(f"Unknown strategy: {strategy}. Choose from {STRATEGIES}")
        self.strategy = strategy

    def _build_df(self, rows: list[dict]) -> pl.DataFrame:
        df = pl.DataFrame(rows)
        df = df.with_columns([
            pl.col("close").ewm_mean(span=9).alias("ema_9"),
            pl.col("close").ewm_mean(span=21).alias("ema_21"),
            pl.col("close").pct_change().alias("return_1d"),
        ])
        # RSI
        delta = pl.col("close").diff()
        gain = pl.col("close").diff().map_elements(lambda x: x if x > 0 else 0.0, return_dtype=pl.Float64)
        loss = pl.col("close").diff().map_elements(lambda x: -x if x < 0 else 0.0, return_dtype=pl.Float64)
        df = df.with_columns([
            gain.rolling_mean(window_size=14).alias("avg_gain"),
            loss.rolling_mean(window_size=14).alias("avg_loss"),
        ])
        df = df.with_columns([
            (100 - 100 / (1 + pl.col("avg_gain") / (pl.col("avg_loss") + 1e-9))).alias("rsi_14"),
        ])
        return df

    def _ema_crossover(self, df: pl.DataFrame) -> dict:
        last = df.tail(2).to_dicts()
        if len(last) < 2:
            return {"action": "hold", "score": 0.0}
        prev, curr = last[0], last[1]
        prev_cross = (prev.get("ema_9") or 0) - (prev.get("ema_21") or 0)
        curr_cross = (curr.get("ema_9") or 0) - (curr.get("ema_21") or 0)
        if prev_cross < 0 and curr_cross > 0:
            return {"action": "buy", "score": 0.7}
        elif prev_cross > 0 and curr_cross < 0:
            return {"action": "sell", "score": -0.7}
        elif curr_cross > 0:
            return {"action": "buy", "score": 0.3}
        elif curr_cross < 0:
            return {"action": "sell", "score": -0.3}
        return {"action": "hold", "score": 0.0}

    def _rsi_mean_reversion(self, df: pl.DataFrame) -> dict:
        rsi = df["rsi_14"][-1]
        if rsi is None:
            return {"action": "hold", "score": 0.0}
        if rsi < 30:
            score = round((30 - rsi) / 30, 4)
            return {"action": "buy", "score": score}
        elif rsi > 70:
            score = round(-(rsi - 70) / 30, 4)
            return {"action": "sell", "score": score}
        return {"action": "hold", "score": 0.0}

    def _momentum(self, df: pl.DataFrame) -> dict:
        ret = df["return_1d"][-1]
        vol = df["volume"][-1] if "volume" in df.columns else 0
        vol_ma = df["volume"].mean() if "volume" in df.columns else 1
        if ret is None:
            return {"action": "hold", "score": 0.0}
        vol_boost = 1.5 if (vol or 0) > (vol_ma or 1) * 1.5 else 1.0
        score = round(max(-1.0, min(1.0, ret * 20 * vol_boost)), 4)
        if score > 0.2:
            action = "buy"
        elif score < -0.2:
            action = "sell"
        else:
            action = "hold"
        return {"action": action, "score": score}

    def run(self, rows: list[dict]) -> dict:
        symbol = rows[0]["symbol"] if rows else "UNKNOWN"
        df = self._build_df(rows)

        if self.strategy == "ema_crossover":
            result = self._ema_crossover(df)
        elif self.strategy == "rsi_mean_reversion":
            result = self._rsi_mean_reversion(df)
        else:
            result = self._momentum(df)

        return {
            "symbol": symbol,
            "strategy": self.strategy,
            **result,
        }
