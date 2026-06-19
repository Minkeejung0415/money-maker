"""Unit tests for FBref set-piece ingestion."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import alpha.data.ingestion.soccer_fbref as soccer_fbref


@pytest.fixture(autouse=True)
def _isolated_cache(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if request.node.name != "test_cache_namespace":
        monkeypatch.setattr(soccer_fbref, "_CACHE_DIR", tmp_path)


def _frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    index = pd.Index(["Arsenal", "Chelsea"], name="team")
    passing = pd.DataFrame(
        [[38, 210], [38, 190]],
        index=index,
        columns=pd.MultiIndex.from_tuples(
            [("Playing Time", "MP"), ("Corner Kicks", "CK")]
        ),
    )
    misc = pd.DataFrame(
        [[54.2], [51.1]],
        index=index,
        columns=pd.MultiIndex.from_tuples([("Aerial Duels", "Won%")]),
    )
    defense = pd.DataFrame(
        [[480], [510]],
        index=index,
        columns=pd.MultiIndex.from_tuples([("Pressures", "Press")]),
    )
    return passing, misc, defense


def _fake_soccerdata() -> tuple[SimpleNamespace, MagicMock]:
    passing, misc, defense = _frames()
    fbref = MagicMock()
    fbref.read_team_season_stats.side_effect = [passing, misc, defense]
    constructor = MagicMock(return_value=fbref)
    return SimpleNamespace(FBref=constructor), constructor


def test_get_set_pieces_returns_dict():
    module, _ = _fake_soccerdata()
    with patch.dict(sys.modules, {"soccerdata": module}):
        result = soccer_fbref.get_fbref_set_pieces("ENG-Premier League", 2024)

    assert result
    assert result["Arsenal"]["corners_per_game"] == pytest.approx(210 / 38)


def test_team_entry_keys():
    module, _ = _fake_soccerdata()
    with patch.dict(sys.modules, {"soccerdata": module}):
        result = soccer_fbref.get_fbref_set_pieces("ENG-Premier League", 2024)

    assert set(result["Chelsea"]) == {
        "corners_per_game",
        "aerial_won_pct",
        "pressing_proxy",
    }


def test_returns_empty_on_fbref_error():
    module = SimpleNamespace(FBref=MagicMock(side_effect=RuntimeError("blocked")))
    with patch.dict(sys.modules, {"soccerdata": module}):
        assert soccer_fbref.get_fbref_set_pieces() == {}


def test_cache_namespace():
    assert soccer_fbref._CACHE_DIR == Path("data/.soccer_cache")


def test_no_wc_imports():
    source = inspect.getsource(soccer_fbref)
    assert "wc_elo" not in source
    assert "wc_stats" not in source


def test_cache_hit():
    module, constructor = _fake_soccerdata()
    with patch.dict(sys.modules, {"soccerdata": module}):
        first = soccer_fbref.get_fbref_set_pieces("ENG-Premier League", 2024)
        second = soccer_fbref.get_fbref_set_pieces("ENG-Premier League", 2024)

    assert first == second
    constructor.assert_called_once()
