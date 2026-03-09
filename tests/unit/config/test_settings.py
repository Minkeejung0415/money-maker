import pytest
from alpha.config.settings import Settings, RiskConfig, SportsConfig


def test_settings_loads_defaults():
    s = Settings()
    assert s.paper_mode is True
    assert s.active_verticals == ["stocks", "crypto", "sports"]


def test_risk_config_has_limits():
    r = RiskConfig()
    assert 0 < r.max_drawdown_pct <= 1.0
    assert 0 < r.kelly_fraction <= 1.0
    assert r.max_cross_asset_exposure_pct <= 1.0


def test_sports_config_has_books():
    sc = SportsConfig()
    assert len(sc.books) > 0
    assert len(sc.sports) > 0
