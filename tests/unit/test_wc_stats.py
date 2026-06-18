"""Tests for alpha/data/ingestion/wc_stats.py."""
from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from alpha.data.ingestion.wc_stats import get_wc_team_stats, _WC_STATS_CACHE, _WC_CACHE_DIR


def test_get_wc_team_stats_loads_pkl(tmp_path, monkeypatch):
    """get_wc_team_stats() loads data from the pkl file and returns correct values."""
    monkeypatch.setattr("alpha.data.ingestion.wc_stats._WC_STATS_CACHE", tmp_path / "wc_stats.pkl")
    monkeypatch.setattr("alpha.data.ingestion.wc_stats._WC_CACHE_DIR", tmp_path)

    fake_stats = {
        "Brazil": {"avg_goals": 2.1, "avg_xG": 1.9, "avg_shots": 14.5, "defense_score": 0.7},
        "built_at": "2026-06-18T12:00:00",
    }
    with open(tmp_path / "wc_stats.pkl", "wb") as f:
        pickle.dump(fake_stats, f)

    result = get_wc_team_stats()
    assert "Brazil" in result
    assert result["Brazil"]["avg_goals"] == pytest.approx(2.1)
    assert result["Brazil"]["avg_xG"] == pytest.approx(1.9)
    assert "built_at" not in result   # popped from output dict


def test_get_wc_team_stats_missing_pkl_raises(tmp_path, monkeypatch):
    """get_wc_team_stats() raises FileNotFoundError with build_wc_priors.py in message."""
    monkeypatch.setattr(
        "alpha.data.ingestion.wc_stats._WC_STATS_CACHE",
        tmp_path / "nonexistent.pkl",
    )
    with pytest.raises(FileNotFoundError, match="build_wc_priors.py"):
        get_wc_team_stats()


def test_wc_stats_output_shape(tmp_path, monkeypatch):
    """get_wc_team_stats() returns exactly {avg_goals, avg_xG, avg_shots, defense_score} per team."""
    monkeypatch.setattr("alpha.data.ingestion.wc_stats._WC_STATS_CACHE", tmp_path / "wc_stats.pkl")
    monkeypatch.setattr("alpha.data.ingestion.wc_stats._WC_CACHE_DIR", tmp_path)

    fake = {
        "Germany": {"avg_goals": 1.8, "avg_xG": 1.7, "avg_shots": 12.0, "defense_score": 0.9},
    }
    with open(tmp_path / "wc_stats.pkl", "wb") as f:
        pickle.dump(fake, f)

    result = get_wc_team_stats()
    team_stats = result["Germany"]
    assert set(team_stats.keys()) == {"avg_goals", "avg_xG", "avg_shots", "defense_score"}


def test_wc_cache_path_isolated():
    """WC cache dir must be data/.wc_cache, NOT data/.soccer_cache."""
    assert "wc_cache" in str(_WC_CACHE_DIR)
    assert "soccer_cache" not in str(_WC_CACHE_DIR)
    assert "wc_stats.pkl" in str(_WC_STATS_CACHE)


def test_wc_stats_team_name_map_applied(tmp_path, monkeypatch):
    """get_wc_team_stats() renames teams according to _TEAM_NAME_MAP."""
    monkeypatch.setattr("alpha.data.ingestion.wc_stats._WC_STATS_CACHE", tmp_path / "wc_stats.pkl")
    monkeypatch.setattr("alpha.data.ingestion.wc_stats._WC_CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        "alpha.data.ingestion.wc_stats._TEAM_NAME_MAP",
        {"United States Men's National Team": "United States"},
    )

    fake = {
        "United States Men's National Team": {
            "avg_goals": 1.5,
            "avg_xG": 1.3,
            "avg_shots": 11.0,
            "defense_score": 1.1,
        },
    }
    with open(tmp_path / "wc_stats.pkl", "wb") as f:
        pickle.dump(fake, f)

    result = get_wc_team_stats()
    assert "United States" in result
    assert "United States Men's National Team" not in result


def test_defense_score_per_game(tmp_path, monkeypatch):
    """defense_score value from pkl is returned as-is (per-game, not total)."""
    monkeypatch.setattr("alpha.data.ingestion.wc_stats._WC_STATS_CACHE", tmp_path / "wc_stats.pkl")
    monkeypatch.setattr("alpha.data.ingestion.wc_stats._WC_CACHE_DIR", tmp_path)

    fake = {
        "Germany": {"avg_goals": 1.8, "avg_xG": 1.7, "avg_shots": 12.0, "defense_score": 0.9},
    }
    with open(tmp_path / "wc_stats.pkl", "wb") as f:
        pickle.dump(fake, f)

    result = get_wc_team_stats()
    assert result["Germany"]["defense_score"] == pytest.approx(0.9)
