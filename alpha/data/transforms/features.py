import logging

import numpy as np
import polars as pl

logger = logging.getLogger(__name__)


def add_returns(df: pl.DataFrame, price_col: str = "close") -> pl.DataFrame:
    return df.with_columns(
        pl.col(price_col).pct_change().alias("return_1d")
    )


def add_moving_averages(df: pl.DataFrame, windows: list[int], price_col: str = "close") -> pl.DataFrame:
    exprs = [
        pl.col(price_col).rolling_mean(window_size=w).alias(f"ma_{w}")
        for w in windows
    ]
    return df.with_columns(exprs)


def add_rsi(df: pl.DataFrame, period: int = 14, price_col: str = "close") -> pl.DataFrame:
    delta = df[price_col].diff()
    gain = delta.map_elements(lambda x: x if x > 0 else 0.0, return_dtype=pl.Float64)
    loss = delta.map_elements(lambda x: -x if x < 0 else 0.0, return_dtype=pl.Float64)
    avg_gain = gain.rolling_mean(window_size=period)
    avg_loss = loss.rolling_mean(window_size=period)
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return df.with_columns(rsi.alias(f"rsi_{period}"))


def build_feature_set(df: pl.DataFrame) -> pl.DataFrame:
    """Standard feature set used across all verticals."""
    df = add_returns(df)
    df = add_moving_averages(df, windows=[5, 10, 20, 50])
    df = add_rsi(df, period=14)
    return df


def build_ta_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Add TA-Lib indicators as new columns to the DataFrame.

    Requires close, high, low columns. If talib is unavailable or columns
    are missing, returns the DataFrame unchanged.

    Added columns: macd_line, macd_signal_line, bb_upper, bb_mid,
    bb_lower, atr_14, adx_14
    """
    try:
        import talib  # noqa: PLC0415
    except ImportError:
        logger.debug("talib not available; skipping TA feature computation")
        return df

    required = {"close", "high", "low"}
    if not required.issubset(set(df.columns)):
        return df

    try:
        close = df["close"].to_numpy().astype(float)
        high = df["high"].to_numpy().astype(float)
        low = df["low"].to_numpy().astype(float)

        macd_line, macd_signal_line, _ = talib.MACD(close, 12, 26, 9)
        bb_upper, bb_mid, bb_lower = talib.BBANDS(close, 20, 2, 2)
        atr_14 = talib.ATR(high, low, close, 14)
        adx_14 = talib.ADX(high, low, close, 14)

        df = df.with_columns([
            pl.Series("macd_line", macd_line),
            pl.Series("macd_signal_line", macd_signal_line),
            pl.Series("bb_upper", bb_upper),
            pl.Series("bb_mid", bb_mid),
            pl.Series("bb_lower", bb_lower),
            pl.Series("atr_14", atr_14),
            pl.Series("adx_14", adx_14),
        ])
    except Exception as exc:
        logger.warning("build_ta_features failed: %s", exc)

    return df
