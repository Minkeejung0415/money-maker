"""
Alpha Factory — computes quantitative alpha factors from OHLCV data.

Uses pure-Python/polars implementation for cross-platform compatibility.
qlib integration is available as an optional enhancement when installed
with MSVC on Windows or on Linux/macOS.
"""
import logging

import polars as pl
from alpha.data.transforms.normalizers import zscore_normalize

logger = logging.getLogger(__name__)


class AlphaFactory:
    """
    Mines alpha factors from price/volume data.
    Factors align with academic literature (Fama-French, AQR).
    """

    def compute_factors(self, df: pl.DataFrame, symbol: str = "") -> pl.DataFrame:
        """
        Compute alpha factors on an OHLCV DataFrame.
        Returns the input DataFrame with added factor columns.

        Args:
            df: OHLCV polars DataFrame.
            symbol: Ticker symbol.  When non-empty and a trained LGBMAlpha
                model exists, blends its prediction 50/50 into alpha_score.
        """
        df = self._momentum_factors(df)
        df = self._volatility_factors(df)
        df = self._volume_factors(df)
        df = self._add_lgbm_alpha(df, symbol)
        df = self._composite_alpha(df)
        return df

    def _momentum_factors(self, df: pl.DataFrame) -> pl.DataFrame:
        """Price momentum over multiple lookbacks."""
        return df.with_columns([
            pl.col("close").pct_change(n=5).alias("momentum_5d"),
            pl.col("close").pct_change(n=20).alias("momentum_20d"),
            pl.col("close").pct_change(n=60).alias("momentum_60d"),
        ])

    def _volatility_factors(self, df: pl.DataFrame) -> pl.DataFrame:
        """Rolling realized volatility (annualized)."""
        return df.with_columns([
            (pl.col("close").pct_change()
             .rolling_std(window_size=20) * (252 ** 0.5))
            .alias("vol_20d"),
        ])

    def _volume_factors(self, df: pl.DataFrame) -> pl.DataFrame:
        """Volume z-score (unusual volume signal)."""
        mean_vol = pl.col("volume").rolling_mean(window_size=20)
        std_vol = pl.col("volume").rolling_std(window_size=20)
        return df.with_columns([
            ((pl.col("volume") - mean_vol) / (std_vol + 1e-9))
            .alias("volume_zscore"),
        ])

    def _add_lgbm_alpha(self, df: pl.DataFrame, symbol: str) -> pl.DataFrame:
        """Optionally add lgbm_alpha column when a trained model exists."""
        if not symbol:
            return df
        try:
            from alpha.engines.stocks.lgbm_alpha import LGBMAlphaModel  # noqa: PLC0415
            lgbm = LGBMAlphaModel()
            if lgbm.is_trained(symbol):
                pred = lgbm.predict(df, symbol)
                lgbm_val = pred if pred != 0.0 else None
                df = df.with_columns(
                    pl.lit(lgbm_val).cast(pl.Float64).alias("lgbm_alpha")
                )
        except Exception as exc:
            logger.debug("LGBMAlpha unavailable for %s: %s", symbol, exc)
        return df

    def _composite_alpha(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Combine factors into a single alpha_score in [-1, 1].

        When lgbm_alpha is present and non-null on the last row, blends
        50 / 50 with momentum alpha.  Otherwise uses momentum alpha alone.
        """
        # Normalize momentum signals
        components = []
        for col in ("momentum_5d", "momentum_20d"):
            if col in df.columns:
                components.append(
                    pl.col(col).clip(-0.1, 0.1) * 10  # scale to [-1, 1]
                )

        momentum_alpha = sum(components) / len(components) if components else pl.lit(0.0)

        if "lgbm_alpha" in df.columns:
            alpha_expr = pl.when(pl.col("lgbm_alpha").is_not_null()).then(
                0.5 * momentum_alpha + 0.5 * pl.col("lgbm_alpha")
            ).otherwise(momentum_alpha)
        else:
            alpha_expr = momentum_alpha

        return df.with_columns(alpha_expr.alias("alpha_score"))

    def top_factors(self, df: pl.DataFrame, n: int = 10) -> pl.DataFrame:
        """Return top-n rows by alpha_score (long candidates)."""
        computed = self.compute_factors(df)
        return (
            computed
            .filter(pl.col("alpha_score").is_not_null())
            .sort("alpha_score", descending=True)
            .head(n)
        )
