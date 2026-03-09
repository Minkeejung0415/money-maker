"""
Whale / volume anomaly tracker.
Detects unusually large volume candles (potential whale activity)
and infers directional bias from price action.
"""
import polars as pl


class WhaleTracker:
    def __init__(self, zscore_threshold: float = 2.5, lookback: int = 20):
        self.zscore_threshold = zscore_threshold
        self.lookback = lookback

    def compute_volume_features(self, rows: list[dict]) -> pl.DataFrame:
        """Add volume_zscore and rolling stats to OHLCV rows."""
        df = pl.DataFrame(rows)
        mean_vol = pl.col("volume").rolling_mean(window_size=self.lookback)
        std_vol = pl.col("volume").rolling_std(window_size=self.lookback)
        df = df.with_columns([
            mean_vol.alias("volume_ma"),
            std_vol.alias("volume_std"),
            ((pl.col("volume") - mean_vol) / (std_vol + 1e-9)).alias("volume_zscore"),
        ])
        return df

    def is_whale_activity(self, rows: list[dict]) -> bool:
        """Return True if latest candle's volume z-score exceeds threshold."""
        df = self.compute_volume_features(rows)
        last_z = df["volume_zscore"][-1]
        if last_z is None:
            return False
        return float(last_z) >= self.zscore_threshold

    def get_signal(self, rows: list[dict]) -> dict:
        """
        Return whale signal dict:
        {whale_detected, zscore, direction, symbol}
        Direction: bullish if price up on whale volume, bearish if down.
        """
        symbol = rows[0]["symbol"] if rows else "UNKNOWN"
        df = self.compute_volume_features(rows)
        last_z = float(df["volume_zscore"][-1] or 0.0)
        whale_detected = last_z >= self.zscore_threshold

        direction = "neutral"
        if whale_detected and len(rows) >= 2:
            last_close = rows[-1]["close"]
            prev_close = rows[-2]["close"]
            if last_close > prev_close:
                direction = "bullish"
            elif last_close < prev_close:
                direction = "bearish"

        return {
            "symbol": symbol,
            "whale_detected": whale_detected,
            "volume_zscore": round(last_z, 4),
            "direction": direction,
        }
