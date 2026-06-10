"""Integration tests for the training dataset builder (scripts/train_xgb_prop_model)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "train_xgb_prop_model.py"


@pytest.fixture(scope="module")
def trainer():
    spec = importlib.util.spec_from_file_location("train_xgb_prop_model", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["train_xgb_prop_model"] = mod
    spec.loader.exec_module(mod)
    return mod


def _player_df(n_games: int = 12, target_minutes: float | None = None) -> pd.DataFrame:
    """One player-season, games every 2 days; optionally one low-minute game."""
    rows = []
    for i in range(n_games):
        minutes = 32.0
        if target_minutes is not None and i == n_games - 1:
            minutes = target_minutes
        rows.append({
            "season": "2024-25",
            "player_id": 1,
            "player_name": "Test Player",
            "game_date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=2 * i),
            "matchup": "LAL vs. BOS" if i % 2 == 0 else "LAL @ BOS",
            "min_float": minutes,
            "pts": 25.0,
            "reb": 6.0,
            "ast": 4.0,
            "fg3m": 2.0,
            "opp_team": "BOS",
        })
    return pd.DataFrame(rows)


def test_target_game_minutes_do_not_affect_row_inclusion(trainer):
    """
    A target game where the player only played 6 minutes must still be a
    training row (the old pipeline dropped it — selection bias).
    """
    full = trainer.build_dataset(_player_df(target_minutes=32.0), "pts")
    short = trainer.build_dataset(_player_df(target_minutes=6.0), "pts")
    assert len(full) == len(short)
    assert len(short) > 0
    # The low-minute target keeps its real value as the label.
    last = short.sort_values("_game_date").iloc[-1]
    assert last["_target"] == 25.0


def test_is_home_from_matchup(trainer):
    data = trainer.build_dataset(_player_df(), "pts").sort_values("_game_date")
    # Games alternate vs./@ — feature rows must alternate is_home 1/0.
    homes = data["is_home"].tolist()
    assert set(homes) == {0.0, 1.0}


def test_rest_days_uses_actual_dates(trainer):
    data = trainer.build_dataset(_player_df(), "pts")
    # Games are exactly 2 days apart → rest_days == 1 everywhere.
    assert set(data["rest_days"].tolist()) == {1.0}


def test_opp_context_is_nan_not_constant(trainer):
    """No leak-free historical opponent ratings → NaN, never 112/100."""
    data = trainer.build_dataset(_player_df(), "pts")
    assert data["opp_def_rtg"].isna().all()
    assert data["opp_pace"].isna().all()


def test_training_features_match_live_builder(trainer):
    """The trainer's feature row equals a direct shared-builder call."""
    from alpha.engines.sports.prop_features import (
        ALL_FEATURES, build_pregame_features, normalize_history_row,
    )

    df = _player_df()
    data = trainer.build_dataset(df, "pts").sort_values("_game_date")
    last_row = data.iloc[-1]

    records = df.to_dict("records")
    history = [normalize_history_row(r, "pts") for r in records[:-1]]
    target = records[-1]
    direct = build_pregame_features(
        history=list(reversed(history)),
        market="player_points",
        game_date=pd.Timestamp(target["game_date"]).date(),
        is_home="vs." in target["matchup"],
    )
    for name in ALL_FEATURES:
        if pd.isna(direct.features[name]):
            assert pd.isna(last_row[name])
        else:
            assert last_row[name] == pytest.approx(direct.features[name])
