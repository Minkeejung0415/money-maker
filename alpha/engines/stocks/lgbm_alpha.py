"""
LightGBM Alpha Model — predicts 5-day forward return using Alpha158-inspired
features derived from OHLCV data with polars + numpy + talib.

The model supplements the hand-crafted alpha_score produced by AlphaFactory.
Training data and predictions are persisted to data/lgbm_alpha_{symbol}.pkl.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import polars as pl

logger = logging.getLogger(__name__)

_DATA_DIR = Path("data")
_MIN_ROWS = 60
_TARGET_WINDOW = 5          # 5-day forward return
_LGBM_PARAMS = dict(
    n_estimators=200,
    learning_rate=0.05,
    max_depth=6,
    num_leaves=31,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
)

# All feature column names produced by build_features()
_FEATURE_COLS = [
    "ret_1d", "ret_5d", "ret_10d", "ret_20d", "ret_60d",
    "vol_5d", "vol_20d",
    "vol_ratio_5_20", "vol_zscore_20",
    "mean_rev_20", "mean_rev_60",
    "drawdown_252",
    "rsi_norm",
]


class LGBMAlphaModel:
    """
    Alpha158-inspired LightGBM predictor for 5-day forward return.

    Usage::

        model = LGBMAlphaModel()
        model.train(df, "AAPL")          # trains + saves pkl
        score = model.predict(df, "AAPL")  # float in roughly [-0.1, 0.1]
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_features(self, df: pl.DataFrame) -> "pd.DataFrame":
        """
        Compute Alpha158-inspired features from an OHLCV polars DataFrame.

        Returns a pandas DataFrame with NaN rows dropped.
        Does NOT include the target column.
        """
        import pandas as pd  # noqa: PLC0415

        close = df["close"].to_numpy().astype(float)
        volume = df["volume"].to_numpy().astype(float)
        n = len(close)

        # --- returns -------------------------------------------------------
        def _pct(arr: np.ndarray, k: int) -> np.ndarray:
            out = np.full(n, np.nan)
            out[k:] = (arr[k:] - arr[:-k]) / (arr[:-k] + 1e-12)
            return out

        ret_1d = _pct(close, 1)
        ret_5d = _pct(close, 5)
        ret_10d = _pct(close, 10)
        ret_20d = _pct(close, 20)
        ret_60d = _pct(close, 60)

        # --- volatility (annualised rolling std of daily returns) -----------
        def _rolling_std(arr: np.ndarray, w: int) -> np.ndarray:
            out = np.full(n, np.nan)
            for i in range(w - 1, n):
                out[i] = arr[i - w + 1 : i + 1].std(ddof=1)
            return out * (252 ** 0.5)

        vol_5d = _rolling_std(ret_1d, 5)
        vol_20d = _rolling_std(ret_1d, 20)

        # --- volume features -----------------------------------------------
        def _rolling_mean(arr: np.ndarray, w: int) -> np.ndarray:
            out = np.full(n, np.nan)
            for i in range(w - 1, n):
                out[i] = arr[i - w + 1 : i + 1].mean()
            return out

        vol_ma5 = _rolling_mean(volume, 5)
        vol_ma20 = _rolling_mean(volume, 20)
        vol_std20 = np.array([
            (volume[max(0, i - 19): i + 1].std(ddof=1) if i >= 19 else np.nan)
            for i in range(n)
        ])

        vol_ratio_5_20 = np.where(vol_ma20 > 1e-9, vol_ma5 / vol_ma20, np.nan)
        vol_zscore_20 = np.where(
            vol_std20 > 1e-9,
            (volume - vol_ma20) / vol_std20,
            np.nan,
        )

        # --- mean reversion (close vs MA) ----------------------------------
        ma20 = _rolling_mean(close, 20)
        ma60 = _rolling_mean(close, 60)
        mean_rev_20 = np.where(ma20 > 1e-9, (close - ma20) / ma20, np.nan)
        mean_rev_60 = np.where(ma60 > 1e-9, (close - ma60) / ma60, np.nan)

        # --- 52-week drawdown from high ------------------------------------
        def _rolling_max(arr: np.ndarray, w: int) -> np.ndarray:
            # Start from index 0; window is capped at available data.
            out = np.empty(n)
            for i in range(n):
                out[i] = arr[max(0, i - w + 1): i + 1].max()
            return out

        high_252 = _rolling_max(close, 252)
        drawdown_252 = np.where(
            high_252 > 1e-9, (close - high_252) / high_252, np.nan
        )

        # --- RSI (talib when available, otherwise skip) --------------------
        rsi_norm = np.full(n, np.nan)
        try:
            import talib  # noqa: PLC0415
            rsi_raw = talib.RSI(close, 14)
            rsi_norm = np.where(
                np.isfinite(rsi_raw), (rsi_raw - 50.0) / 50.0, np.nan
            )
        except Exception:
            pass

        feat = pd.DataFrame({
            "ret_1d": ret_1d,
            "ret_5d": ret_5d,
            "ret_10d": ret_10d,
            "ret_20d": ret_20d,
            "ret_60d": ret_60d,
            "vol_5d": vol_5d,
            "vol_20d": vol_20d,
            "vol_ratio_5_20": vol_ratio_5_20,
            "vol_zscore_20": vol_zscore_20,
            "mean_rev_20": mean_rev_20,
            "mean_rev_60": mean_rev_60,
            "drawdown_252": drawdown_252,
            "rsi_norm": rsi_norm,
        })

        # Drop rows where any feature is NaN
        return feat.dropna().reset_index(drop=True)

    def train(self, df: pl.DataFrame, symbol: str) -> None:
        """
        Build features + 5-day forward return target, then train and save
        a LGBMRegressor.  Skips (with a warning) if fewer than _MIN_ROWS
        clean rows remain after NaN removal.
        """
        import pandas as pd  # noqa: PLC0415
        try:
            from lightgbm import LGBMRegressor  # noqa: PLC0415
            import joblib  # noqa: PLC0415
        except ImportError as exc:
            logger.warning("lightgbm/joblib not available — skipping train: %s", exc)
            return

        feat = self.build_features(df)

        # 5-day forward return target aligned with feature rows
        close = df["close"].to_numpy().astype(float)
        n = len(close)
        target_full = np.full(n, np.nan)
        target_full[: n - _TARGET_WINDOW] = (
            close[_TARGET_WINDOW:] - close[: n - _TARGET_WINDOW]
        ) / (close[: n - _TARGET_WINDOW] + 1e-12)

        # build_features drops NaN rows; we need to re-align the target
        feat_raw = self._build_features_with_index(df)
        feat_raw["target"] = target_full[feat_raw.index]
        feat_raw = feat_raw.dropna(subset=["target"])

        # Align features with surviving rows
        X = feat_raw[_FEATURE_COLS]
        y = feat_raw["target"]

        if len(X) < _MIN_ROWS:
            logger.warning(
                "LGBMAlphaModel: only %d clean rows for %s — need %d, skipping train",
                len(X), symbol, _MIN_ROWS,
            )
            return

        model = LGBMRegressor(**_LGBM_PARAMS)
        model.fit(X, y)

        _DATA_DIR.mkdir(exist_ok=True)
        pkl_path = _DATA_DIR / f"lgbm_alpha_{symbol}.pkl"
        joblib.dump(model, pkl_path)
        logger.info("LGBMAlphaModel saved: %s (%d rows)", pkl_path, len(X))

    def predict(self, df: pl.DataFrame, symbol: str) -> float:
        """
        Load the trained model for *symbol* and return the predicted 5-day
        forward return for the last row of *df*.

        Returns 0.0 if no model file exists or prediction fails.
        """
        try:
            import joblib  # noqa: PLC0415
        except ImportError:
            return 0.0

        pkl_path = _DATA_DIR / f"lgbm_alpha_{symbol}.pkl"
        if not pkl_path.exists():
            return 0.0

        try:
            model = joblib.load(pkl_path)
            feat = self._build_features_with_index(df)
            feat_clean = feat[_FEATURE_COLS].dropna()
            if feat_clean.empty:
                return 0.0
            last_row = feat_clean.tail(1)
            pred = float(model.predict(last_row)[0])
            return pred
        except Exception as exc:
            logger.warning("LGBMAlphaModel.predict failed for %s: %s", symbol, exc)
            return 0.0

    def is_trained(self, symbol: str) -> bool:
        """Return True if a saved model file exists for *symbol*."""
        return (_DATA_DIR / f"lgbm_alpha_{symbol}.pkl").exists()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_features_with_index(self, df: pl.DataFrame) -> "pd.DataFrame":
        """
        Same as build_features() but preserves the original row index so
        we can align the target column.
        """
        import pandas as pd  # noqa: PLC0415

        close = df["close"].to_numpy().astype(float)
        volume = df["volume"].to_numpy().astype(float)
        n = len(close)

        def _pct(arr: np.ndarray, k: int) -> np.ndarray:
            out = np.full(n, np.nan)
            out[k:] = (arr[k:] - arr[:-k]) / (arr[:-k] + 1e-12)
            return out

        def _rolling_std(arr: np.ndarray, w: int) -> np.ndarray:
            out = np.full(n, np.nan)
            for i in range(w - 1, n):
                out[i] = arr[i - w + 1 : i + 1].std(ddof=1)
            return out * (252 ** 0.5)

        def _rolling_mean(arr: np.ndarray, w: int) -> np.ndarray:
            out = np.full(n, np.nan)
            for i in range(w - 1, n):
                out[i] = arr[i - w + 1 : i + 1].mean()
            return out

        ret_1d = _pct(close, 1)
        vol_ma5 = _rolling_mean(volume, 5)
        vol_ma20 = _rolling_mean(volume, 20)
        vol_std20 = np.array([
            (volume[max(0, i - 19): i + 1].std(ddof=1) if i >= 19 else np.nan)
            for i in range(n)
        ])
        vol_ratio_5_20 = np.where(vol_ma20 > 1e-9, vol_ma5 / vol_ma20, np.nan)
        vol_zscore_20 = np.where(
            vol_std20 > 1e-9, (volume - vol_ma20) / vol_std20, np.nan
        )
        ma20 = _rolling_mean(close, 20)
        ma60 = _rolling_mean(close, 60)

        def _rolling_max(arr: np.ndarray, w: int) -> np.ndarray:
            out = np.empty(n)
            for i in range(n):
                out[i] = arr[max(0, i - w + 1): i + 1].max()
            return out

        high_252 = _rolling_max(close, 252)

        rsi_norm = np.full(n, np.nan)
        try:
            import talib  # noqa: PLC0415
            rsi_raw = talib.RSI(close, 14)
            rsi_norm = np.where(np.isfinite(rsi_raw), (rsi_raw - 50.0) / 50.0, np.nan)
        except Exception:
            pass

        feat = pd.DataFrame({
            "ret_1d": _pct(close, 1),
            "ret_5d": _pct(close, 5),
            "ret_10d": _pct(close, 10),
            "ret_20d": _pct(close, 20),
            "ret_60d": _pct(close, 60),
            "vol_5d": _rolling_std(ret_1d, 5),
            "vol_20d": _rolling_std(ret_1d, 20),
            "vol_ratio_5_20": vol_ratio_5_20,
            "vol_zscore_20": vol_zscore_20,
            "mean_rev_20": np.where(ma20 > 1e-9, (close - ma20) / ma20, np.nan),
            "mean_rev_60": np.where(ma60 > 1e-9, (close - ma60) / ma60, np.nan),
            "drawdown_252": np.where(
                high_252 > 1e-9, (close - high_252) / high_252, np.nan
            ),
            "rsi_norm": rsi_norm,
        })

        # Drop rows where all-feature NaN but keep index for alignment
        return feat.dropna(subset=_FEATURE_COLS)
