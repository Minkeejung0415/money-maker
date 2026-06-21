"""Tests for normalized World Cup market override data."""
from __future__ import annotations

import json

import pytest

from alpha.data.ingestion.wc_market_odds import load_wc_market_odds


def test_loads_extended_market_prices(tmp_path):
    path = tmp_path / "odds.json"
    path.write_text(json.dumps({
        "Brazil|Germany": {
            "home_decimal": 1.8,
            "draw_decimal": 3.6,
            "away_decimal": 4.5,
            "over_2_5_decimal": 1.9,
            "under_2_5_decimal": 1.95,
            "btts_yes_decimal": 1.85,
            "btts_no_decimal": 2.0,
        }
    }), encoding="utf-8")
    odds = load_wc_market_odds(path)["Brazil|Germany"]
    assert odds.prices["home_win"] == 1.8
    assert odds.prices["over_2_5"] == 1.9
    assert odds.prices["btts_no"] == 2.0


def test_legacy_moneyline_override_remains_supported(tmp_path):
    path = tmp_path / "odds.json"
    path.write_text(json.dumps({
        "Brazil|Germany": {"home_decimal": 1.8, "away_decimal": 4.5}
    }), encoding="utf-8")
    odds = load_wc_market_odds(path)["Brazil|Germany"]
    assert odds.prices == {"home_win": 1.8, "away_win": 4.5}


def test_missing_prices_are_not_filled(tmp_path):
    path = tmp_path / "odds.json"
    path.write_text(json.dumps({"Brazil|Germany": {"home_decimal": 1.8}}), encoding="utf-8")
    odds = load_wc_market_odds(path)["Brazil|Germany"]
    assert "over_2_5" not in odds.prices
    assert "btts_yes" not in odds.prices


def test_invalid_decimal_price_is_rejected(tmp_path):
    path = tmp_path / "odds.json"
    path.write_text(json.dumps({"Brazil|Germany": {"home_decimal": 1.0}}), encoding="utf-8")
    with pytest.raises(ValueError, match="greater than 1.0"):
        load_wc_market_odds(path)

