import polars as pl


def zscore_normalize(df: pl.DataFrame, col: str) -> pl.DataFrame:
    mean = df[col].mean()
    std = df[col].std()
    return df.with_columns(
        ((pl.col(col) - mean) / std).alias(f"{col}_z")
    )


def minmax_normalize(df: pl.DataFrame, col: str) -> pl.DataFrame:
    min_val = df[col].min()
    max_val = df[col].max()
    return df.with_columns(
        ((pl.col(col) - min_val) / (max_val - min_val)).alias(f"{col}_norm")
    )
