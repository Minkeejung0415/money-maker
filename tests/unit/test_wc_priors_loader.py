"""Tests for alpha/data/ingestion/wc_elo.py — Elo loader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from alpha.data.ingestion.wc_elo import load_wc_elo_ratings, get_elo_rating, _ELO_FALLBACK, _WC_PRIORS_PATH


def test_load_wc_priors_returns_dict(tmp_path, monkeypatch):
    """load_wc_elo_ratings() reads JSON and returns dict with correct values."""
    priors_file = tmp_path / "wc_priors.json"
    priors_file.write_text(json.dumps({"Brazil": 2100, "Germany": 1980}), encoding="utf-8")
    monkeypatch.setattr("alpha.data.ingestion.wc_elo._WC_PRIORS_PATH", priors_file)

    result = load_wc_elo_ratings()
    assert isinstance(result, dict)
    assert len(result) >= 1
    assert result["Brazil"] == 2100
    assert result["Germany"] == 1980


def test_elo_fallback_1500():
    """get_elo_rating() returns 1500 for unknown teams and correct value for known teams."""
    ratings = {"Brazil": 2100}
    assert get_elo_rating("Zimbabwe", ratings) == _ELO_FALLBACK
    assert get_elo_rating("Zimbabwe", ratings) == 1500
    assert get_elo_rating("Brazil", ratings) == 2100


def test_missing_priors_raises(tmp_path, monkeypatch):
    """load_wc_elo_ratings() raises FileNotFoundError with build_wc_priors.py in message."""
    monkeypatch.setattr(
        "alpha.data.ingestion.wc_elo._WC_PRIORS_PATH",
        tmp_path / "nonexistent.json",
    )
    with pytest.raises(FileNotFoundError, match="build_wc_priors.py"):
        load_wc_elo_ratings()


def test_load_wc_priors_elo_fallback_constant():
    """_ELO_FALLBACK must equal 1500 (FIFA world average)."""
    assert _ELO_FALLBACK == 1500


def test_load_wc_priors_path_is_data_dir():
    """_WC_PRIORS_PATH must point to wc_priors.json."""
    assert "wc_priors.json" in str(_WC_PRIORS_PATH)


def test_load_wc_priors_multiple_teams(tmp_path, monkeypatch):
    """load_wc_elo_ratings() returns all teams in the JSON file."""
    data = {"Brazil": 2100, "Germany": 1980, "France": 2050, "Argentina": 2070}
    priors_file = tmp_path / "wc_priors.json"
    priors_file.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("alpha.data.ingestion.wc_elo._WC_PRIORS_PATH", priors_file)

    result = load_wc_elo_ratings()
    assert len(result) == 4
    assert result["France"] == 2050
    assert result["Argentina"] == 2070


def test_get_elo_rating_exact_match():
    """get_elo_rating() returns the exact rating value from the dict, not the fallback."""
    ratings = {"Brazil": 2100, "England": 1850}
    assert get_elo_rating("England", ratings) == 1850
    assert get_elo_rating("Brazil", ratings) == 2100
