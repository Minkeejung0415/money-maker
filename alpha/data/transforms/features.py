import polars as pl


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
