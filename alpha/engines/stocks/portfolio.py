"""
Portfolio optimizer wrapping PyPortfolioOpt.
Supports: max Sharpe, min volatility, equal weight fallback.
"""
import polars as pl


class PortfolioOptimizer:
    def __init__(self, risk_free_rate: float = 0.05):
        self.risk_free_rate = risk_free_rate

    def _to_pandas(self, df: pl.DataFrame):
        return df.to_pandas()

    def max_sharpe(self, returns_df: pl.DataFrame) -> dict[str, float]:
        """
        Maximize Sharpe ratio given a DataFrame of daily returns
        (columns = symbols, rows = days).
        """
        from pypfopt import EfficientFrontier, risk_models, expected_returns

        pd_df = self._to_pandas(returns_df)
        mu = expected_returns.mean_historical_return(pd_df, returns_data=True)
        S = risk_models.sample_cov(pd_df, returns_data=True)
        ef = EfficientFrontier(mu, S)
        ef.max_sharpe(risk_free_rate=self.risk_free_rate)
        weights = ef.clean_weights()
        return dict(weights)

    def min_volatility(self, returns_df: pl.DataFrame) -> dict[str, float]:
        """Minimize portfolio volatility."""
        from pypfopt import EfficientFrontier, risk_models, expected_returns

        pd_df = self._to_pandas(returns_df)
        mu = expected_returns.mean_historical_return(pd_df, returns_data=True)
        S = risk_models.sample_cov(pd_df, returns_data=True)
        ef = EfficientFrontier(mu, S)
        ef.min_volatility()
        weights = ef.clean_weights()
        return dict(weights)

    def equal_weight(self, symbols: list[str]) -> dict[str, float]:
        """Equal weight fallback — used when optimization fails."""
        w = 1.0 / len(symbols)
        return {s: w for s in symbols}

    def signal_weighted(
        self,
        returns_df: pl.DataFrame,
        signals: dict[str, float],
        min_signal_strength: float = 0.2,
    ) -> dict[str, float]:
        """
        ML-signal-aware allocation (research upgrade 2026-03-17).

        Uses ML scores as expected-return priors for constrained max-Sharpe.
        Falls back to equal weight when max signal is below threshold — per
        DeMiguel et al. (2009), optimization only beats 1/N when alpha signals
        are genuinely informative.

        Weight bounds (5%–40%) act as an implicit turnover penalty by
        preventing extreme concentration.
        """
        from pypfopt import EfficientFrontier, risk_models  # noqa: PLC0415
        import pandas as pd  # noqa: PLC0415

        symbols = list(returns_df.columns)
        max_sig = max(abs(signals.get(s, 0.0)) for s in symbols)

        if max_sig < min_signal_strength:
            return self.equal_weight(symbols)

        try:
            pd_df = self._to_pandas(returns_df)
            # Scale ML scores to approximate daily return magnitudes
            mu = pd.Series({s: signals.get(s, 0.0) * 0.01 for s in symbols})
            S = risk_models.sample_cov(pd_df, returns_data=True)
            ef = EfficientFrontier(mu, S, weight_bounds=(0.05, 0.40))
            ef.max_sharpe(risk_free_rate=self.risk_free_rate)
            return dict(ef.clean_weights())
        except Exception:
            return self.equal_weight(symbols)

    def allocate(
        self,
        returns_df: pl.DataFrame,
        method: str = "max_sharpe",
        signals: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """
        Main entry: returns cleaned weights dict.
        Falls back to equal weight if optimization fails.

        Pass signals dict to use ML-signal-aware allocation.
        """
        symbols = list(returns_df.columns)
        try:
            if signals is not None:
                return self.signal_weighted(returns_df, signals)
            elif method == "max_sharpe":
                return self.max_sharpe(returns_df)
            elif method == "min_volatility":
                return self.min_volatility(returns_df)
            else:
                return self.equal_weight(symbols)
        except Exception:
            return self.equal_weight(symbols)
