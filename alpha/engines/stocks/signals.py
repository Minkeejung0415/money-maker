"""
Stock signal engine — combines price features + macro regime into a
normalized score in [-1, 1]. Positive = bullish, negative = bearish.
"""
import polars as pl
from alpha.data.transforms.features import build_feature_set, build_ta_features
from alpha.data.transforms.normalizers import zscore_normalize

BUY_THRESHOLD = 0.2
SELL_THRESHOLD = -0.2

_TA_COLS = ("macd_line", "macd_signal_line", "bb_upper", "bb_lower", "adx_14")


class StockSignalEngine:
    def __init__(self, av_api_key: str | None = None, fred_api_key: str | None = None):
        self._av_key = av_api_key
        self._fred_key = fred_api_key

    def build_features(self, price_rows: list[dict]) -> pl.DataFrame:
        """Run full feature pipeline on raw OHLCV rows."""
        df = pl.DataFrame(price_rows)
        df = build_feature_set(df)
        df = build_ta_features(df)
        df = zscore_normalize(df, "close")
        return df

    def score(self, df: pl.DataFrame) -> float:
        """
        Compute a score in [-1, 1] from the latest row.

        When TA-Lib columns are present uses: MACD crossover, RSI,
        Bollinger position, filtered by ADX.  Falls back to the original
        3-factor (return_1d + RSI + MA-20 spread) when TA columns are absent.
        """
        last = df.tail(1)
        ta_available = all(c in df.columns for c in _TA_COLS)

        if ta_available:
            return self._score_ta(last)
        return self._score_fallback(last, df)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _score_ta(self, last: pl.DataFrame) -> float:
        """TA-Lib enhanced score (MACD + RSI + Bollinger, ADX filtered)."""
        close = last["close"][0]
        rsi = last["rsi_14"][0] if "rsi_14" in last.columns else None
        macd_line = last["macd_line"][0]
        macd_sig = last["macd_signal_line"][0]
        bb_upper = last["bb_upper"][0]
        bb_lower = last["bb_lower"][0]
        adx = last["adx_14"][0]

        components: list[float] = []

        # MACD crossover: scaled so 0.5 % price spread = ±1
        if (
            macd_line is not None
            and macd_sig is not None
            and close is not None
            and close > 0
        ):
            spread = macd_line - macd_sig
            components.append(max(-1.0, min(1.0, spread / (close * 0.005))))

        # RSI: 50 = neutral, 70 = overbought (−1), 30 = oversold (+1)
        if rsi is not None:
            components.append(max(-1.0, min(1.0, (50 - rsi) / 20)))

        # Bollinger band position: 0 = lower band, 1 = upper band → [−1, 1]
        if (
            bb_upper is not None
            and bb_lower is not None
            and close is not None
        ):
            bb_range = bb_upper - bb_lower
            if bb_range > 0:
                bb_pos = (close - bb_lower) / (bb_range + 1e-9)
                components.append(max(-1.0, min(1.0, bb_pos * 2 - 1)))

        # ADX filter: weak trend → halve all signal confidence
        if adx is not None and adx < 20:
            components = [c * 0.5 for c in components]

        if not components:
            return 0.0
        return round(sum(components) / len(components), 4)

    def _score_fallback(self, last: pl.DataFrame, df: pl.DataFrame) -> float:
        """Original 3-factor score (return_1d + RSI + MA-20 spread)."""
        ret = last["return_1d"][0]
        rsi = last["rsi_14"][0] if "rsi_14" in df.columns else None
        close = last["close"][0]
        ma20 = last["ma_20"][0] if "ma_20" in df.columns else None

        components: list[float] = []

        if ret is not None:
            components.append(max(-1.0, min(1.0, ret * 20)))

        if rsi is not None:
            components.append(max(-1.0, min(1.0, (50 - rsi) / 20)))

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

    def get_signal_with_fundamentals(
        self,
        price_rows: list[dict],
        av_client=None,
    ) -> dict:
        """
        get_signal() with optional fundamental filter on BUY signals.

        If action == 'buy' and av_client is provided, fetches PE ratio,
        EPS, and profit margin.  Downgrades to 'hold' if any metric
        indicates a broken fundamental picture.

        Sell signals bypass the filter.  If fundamentals are unavailable
        (av_client is None or get_fundamentals returns None) the filter
        is marked 'skipped' and the original action is preserved.
        """
        signal = self.get_signal(price_rows)
        signal["fundamental_filter"] = "skipped"

        if signal["action"] == "buy" and av_client is not None:
            symbol = price_rows[0]["symbol"] if price_rows else "UNKNOWN"
            fundamentals = av_client.get_fundamentals(symbol)

            if fundamentals is not None:
                pe = fundamentals.get("pe_ratio")
                eps = fundamentals.get("eps")
                margin = fundamentals.get("profit_margin")

                failed = (
                    (pe is not None and pe > 50)
                    or (eps is not None and eps <= 0)
                    or (margin is not None and margin < 0)
                )

                if failed:
                    signal["action"] = "hold"
                    signal["fundamental_filter"] = "fail"
                else:
                    signal["fundamental_filter"] = "pass"
            # else: fundamentals is None → filter stays "skipped"

        return signal
