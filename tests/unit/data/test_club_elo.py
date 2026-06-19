"""
Unit tests for alpha/data/ingestion/club_elo.py

All network calls are mocked — no real HTTP requests.
"""
from __future__ import annotations

import inspect
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_CSV = (
    "Rank,Club,Country,Level,Elo,From,To\n"
    "1,Arsenal,ENG,1,1850.0,2024-01-01,2025-01-01\n"
    "2,Chelsea,ENG,1,1780.5,2024-01-01,2025-01-01\n"
)


class _FakeResponse:
    """Minimal requests.Response stand-in."""

    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoadReturnsDict:
    """load_club_elo_ratings() returns a dict[str, float] on success."""

    def test_load_returns_dict(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import alpha.data.ingestion.club_elo as club_elo

        # Redirect cache to tmp_path so we don't pollute the real cache
        monkeypatch.setattr(club_elo, "_CACHE_DIR", tmp_path)

        with patch("alpha.data.ingestion.club_elo.requests.get") as mock_get:
            mock_get.return_value = _FakeResponse(_VALID_CSV)
            result = club_elo.load_club_elo_ratings("2025-01-15")

        assert isinstance(result, dict)
        assert "Arsenal" in result
        assert result["Arsenal"] == pytest.approx(1850.0)
        assert "Chelsea" in result
        assert result["Chelsea"] == pytest.approx(1780.5)


class TestLoadCacheWrite:
    """After load_club_elo_ratings(), a CSV file is written to _CACHE_DIR."""

    def test_load_cache_write(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import alpha.data.ingestion.club_elo as club_elo

        monkeypatch.setattr(club_elo, "_CACHE_DIR", tmp_path)
        date_str = "2025-01-15"

        with patch("alpha.data.ingestion.club_elo.requests.get") as mock_get:
            mock_get.return_value = _FakeResponse(_VALID_CSV)
            club_elo.load_club_elo_ratings(date_str)

        # A file matching club_elo_<date>.csv should exist
        cache_file = tmp_path / f"club_elo_{date_str}.csv"
        assert cache_file.exists(), f"Cache file not found: {cache_file}"
        assert "Arsenal" in cache_file.read_text(encoding="utf-8")


class TestStaleCacheFallback:
    """On ConnectionError, stale cache (<= 2 days old) is returned."""

    def test_stale_cache_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import alpha.data.ingestion.club_elo as club_elo

        monkeypatch.setattr(club_elo, "_CACHE_DIR", tmp_path)

        # Write a stale cache file dated yesterday
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        stale_file = tmp_path / f"club_elo_{yesterday}.csv"
        stale_file.write_text(_VALID_CSV, encoding="utf-8")

        # Requesting today's date, but network fails
        with patch("alpha.data.ingestion.club_elo.requests.get", side_effect=ConnectionError("down")):
            result = club_elo.load_club_elo_ratings(date.today().isoformat())

        assert isinstance(result, dict)
        assert len(result) > 0
        assert "Arsenal" in result


class TestNoCacheNetworkFail:
    """RuntimeError is raised when network fails and no cache exists."""

    def test_no_cache_network_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import alpha.data.ingestion.club_elo as club_elo

        monkeypatch.setattr(club_elo, "_CACHE_DIR", tmp_path)
        # No cache files in tmp_path

        with patch("alpha.data.ingestion.club_elo.requests.get", side_effect=ConnectionError("down")):
            with pytest.raises(RuntimeError, match="Club Elo unavailable"):
                club_elo.load_club_elo_ratings(date.today().isoformat())


class TestGetRatingAlias:
    """get_club_elo_rating() resolves aliases from _CLUB_ALIASES."""

    def test_get_rating_alias(self) -> None:
        import alpha.data.ingestion.club_elo as club_elo

        ratings = {"Manchester City": 1900.0, "Arsenal": 1850.0}
        # "Man City" -> "Manchester City" via _CLUB_ALIASES
        result = club_elo.get_club_elo_rating("Man City", ratings)
        assert result == pytest.approx(1900.0)


class TestGetRatingMiss:
    """get_club_elo_rating() returns 1500.0 on unknown club."""

    def test_get_rating_miss(self) -> None:
        import alpha.data.ingestion.club_elo as club_elo

        ratings = {"Arsenal": 1850.0}
        result = club_elo.get_club_elo_rating("NonexistentFC", ratings)
        assert result == pytest.approx(1500.0)


class TestCacheNamespace:
    """_CACHE_DIR is exactly Path('data/.soccer_cache')."""

    def test_cache_namespace(self) -> None:
        import alpha.data.ingestion.club_elo as club_elo

        assert club_elo._CACHE_DIR == Path("data/.soccer_cache")


class TestNoWcImports:
    """club_elo module source must not reference wc_elo or wc_stats."""

    def test_no_wc_imports(self) -> None:
        import alpha.data.ingestion.club_elo as club_elo

        src = inspect.getsource(club_elo)
        assert "wc_elo" not in src, "club_elo.py imports or references wc_elo"
        assert "wc_stats" not in src, "club_elo.py imports or references wc_stats"
        assert ".wc_cache" not in src, "club_elo.py references .wc_cache"
