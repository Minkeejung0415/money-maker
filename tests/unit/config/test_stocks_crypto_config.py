"""
Tests for StocksConfig and CryptoConfig (Fix 2 and Fix 3).
"""
import pytest
from alpha.config.settings import StocksConfig, CryptoConfig


# ---------------------------------------------------------------------------
# StocksConfig
# ---------------------------------------------------------------------------

def test_stocks_config_has_watchlist():
    cfg = StocksConfig()
    assert isinstance(cfg.watchlist, list)
    assert len(cfg.watchlist) > 0


def test_stocks_config_watchlist_from_toml():
    """settings.toml defines 15 tickers — verify they are loaded."""
    cfg = StocksConfig()
    assert "AAPL" in cfg.watchlist
    assert "NVDA" in cfg.watchlist
    assert "MSFT" in cfg.watchlist


def test_stocks_config_watchlist_len():
    cfg = StocksConfig()
    assert len(cfg.watchlist) == 15


# ---------------------------------------------------------------------------
# CryptoConfig
# ---------------------------------------------------------------------------

def test_crypto_config_has_pairs():
    cfg = CryptoConfig()
    assert isinstance(cfg.pairs, list)
    assert len(cfg.pairs) > 0


def test_crypto_config_pairs_from_toml():
    """settings.toml defines 5 pairs — verify they are loaded."""
    cfg = CryptoConfig()
    assert "BTC/USDT" in cfg.pairs
    assert "ETH/USDT" in cfg.pairs


def test_crypto_config_pairs_len():
    cfg = CryptoConfig()
    assert len(cfg.pairs) == 5
