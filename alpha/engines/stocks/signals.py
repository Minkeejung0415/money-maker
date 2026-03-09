"""
Stock signal engine — combines price features + macro regime into a
normalized score in [-1, 1]. Positive = bullish, negative = bearish.
"""
import polars as pl
from alpha.data.transforms.features import build_feature_set
from alpha.data.transforms.normalizers import zscore_normalize

BUY_THRESHOLD = 0.2
SELL_THRESHOLD = -0.2


class StockSignalEngine:
    def __init__(self, av_api_key: str | None = None, fred_api_key: str | None = None):
        self._av_key = av_api_key
        self._fred_key = fred_api_key

    def build_features(self, price_rows: list[dict]) -> pl.DataFrame:
        """Run full feature pipeline on raw OHLCV rows."""
        df = pl.DataFrame(price_rows)
        df = build_feature_set(df)
        df = zscore_normalize(df, "close")
        return df

    def score(self, df: pl.DataFrame) -> float:
        """
        Compute a momentum-based score in [-1, 1] from the latest row.
        Uses: return_1d, RSI, close vs MA-20 spread.
        """
        last = df.tail(1)

        ret = last["return_1d"][0]
        rsi = last["rsi_14"][0] if "rsi_14" in df.columns else None
        close = last["close"][0]
        ma20 = last["ma_20"][0] if "ma_20" in df.columns else None

        components = []

        # Momentum: return_1d clipped to [-5%, +5%] → [-1, 1]
        if ret is not None:
            components.append(max(-1.0, min(1.0, ret * 20)))

        # RSI: 50 = neutral, 70 = overbought (-1), 30 = oversold (+1)
        if rsi is not None:
            components.append(max(-1.0, min(1.0, (50 - rsi) / 20)))

        # Price vs MA20
        if ma20 is not None and ma20 > 0:
            spread = (close - ma20) / ma20
            components.append(max(-1.0, min(1.0, spread * 10)))

        if not components:
            return 0.0
        return round(sum(components) / len(components), 4)

    def get_signal(self, price_rows: list[dict]) -> dict:
        """Full pipeline: rows → features → score → action."""
        symbol = price_rows[0]["symbol"] if price_rows else "UNKNOWN"
        df = self.build_features(price_rows)
        s = self.score(df)
        if s >= BUY_THRESHOLD:
            action = "buy"
        elif s <= SELL_THRESHOLD:
            action = "sell"
        else:
            action = "hold"
        return {"symbol": symbol, "score": s, "action": action}
