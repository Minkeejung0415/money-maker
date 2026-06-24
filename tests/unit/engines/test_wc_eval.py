"""
Tests for data/wc_historical_matches.py and evaluate_model() integration.

These tests cover:
- EVAL-01: Chronological split logic and Elo override usage
- Data integrity: correct counts, no draws in knockout, deep-copy isolation
"""
from __future__ import annotations

import pytest
import numpy as np

from data.wc_historical_matches import (
    WC_HISTORICAL,
    get_matches,
    GROUP_STAGE,
    KNOCKOUT_STAGES,
)
from alpha.engines.sports.wc_calibration import evaluate_model
from alpha.engines.sports.wc_model import WCMatchModel


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def model(monkeypatch):
    """WCMatchModel with a small in-memory Elo dict to avoid loading wc_priors.json."""
    fake_elo = {
        "Brazil": 2100,
        "Germany": 1980,
        "France": 2050,
        "Argentina": 2070,
        "Uruguay": 1950,
        "Croatia": 1900,
    }
    monkeypatch.setattr(
        "alpha.engines.sports.wc_model.load_wc_elo_ratings", lambda: fake_elo
    )
    return WCMatchModel()


# ---------------------------------------------------------------------------
# test_get_matches_year_filter
# ---------------------------------------------------------------------------


def test_get_matches_year_filter():
    """get_matches(year=2018) returns only 2018 records."""
    matches = get_matches(year=2018)
    assert len(matches) > 0
    for m in matches:
        assert m["year"] == 2018, f"Non-2018 record returned: {m}"


def test_get_matches_year_2022():
    """get_matches(year=2022) returns only 2022 records."""
    matches = get_matches(year=2022)
    assert len(matches) > 0
    for m in matches:
        assert m["year"] == 2022, f"Non-2022 record returned: {m}"


# ---------------------------------------------------------------------------
# test_get_matches_returns_copies
# ---------------------------------------------------------------------------


def test_get_matches_returns_copies():
    """Mutating returned dicts does NOT affect WC_HISTORICAL."""
    original_first_outcome = WC_HISTORICAL[0]["outcome"]
    returned = get_matches()
    returned[0]["outcome"] = "MUTATED"
    # WC_HISTORICAL must be unaffected
    assert WC_HISTORICAL[0]["outcome"] == original_first_outcome, (
        "get_matches() returned a reference to the original dict — must return deep copies"
    )


def test_get_matches_independent_calls():
    """Two calls to get_matches() return independent lists."""
    a = get_matches(year=2018)
    b = get_matches(year=2018)
    a[0]["year"] = 9999
    assert b[0]["year"] == 2018, "Second call should be independent of first"


# ---------------------------------------------------------------------------
# test_get_matches_stage_filter
# ---------------------------------------------------------------------------


def test_get_matches_stage_filter():
    """get_matches(stage='GROUP_STAGE') returns no knockout records."""
    matches = get_matches(stage=GROUP_STAGE)
    for m in matches:
        assert m["stage"] == GROUP_STAGE, (
            f"Non-group-stage record returned: stage={m['stage']}"
        )
        assert m["stage"] not in KNOCKOUT_STAGES


def test_get_matches_stage_filter_last_16():
    """get_matches(stage='LAST_16') returns only Round of 16 records."""
    from data.wc_historical_matches import LAST_16
    matches = get_matches(stage=LAST_16)
    assert len(matches) == 16  # 8 from 2018 + 8 from 2022
    for m in matches:
        assert m["stage"] == LAST_16


# ---------------------------------------------------------------------------
# test_evaluate_model_keys
# ---------------------------------------------------------------------------


def test_evaluate_model_keys(model):
    """evaluate_model() result has all expected keys."""
    # Use a small set of group stage matches with Elo overrides to avoid fallback
    matches = [
        {
            "year": 2018,
            "stage": GROUP_STAGE,
            "group": "A",
            "home_team": "Brazil",
            "away_team": "Germany",
            "home_score": 1,
            "away_score": 0,
            "outcome": "W",
            "league": "wc",
        },
        {
            "year": 2018,
            "stage": GROUP_STAGE,
            "group": "B",
            "home_team": "France",
            "away_team": "Argentina",
            "home_score": 1,
            "away_score": 1,
            "outcome": "D",
            "league": "wc",
        },
        {
            "year": 2018,
            "stage": GROUP_STAGE,
            "group": "C",
            "home_team": "Germany",
            "away_team": "Brazil",
            "home_score": 0,
            "away_score": 1,
            "outcome": "L",
            "league": "wc",
        },
    ]
    result = evaluate_model(model, matches)
    for key in ("brier", "log_loss", "accuracy", "a_grade", "n_samples"):
        assert key in result, f"Missing key: {key}"
    assert result["n_samples"] == 3
    assert isinstance(result["a_grade"], dict)
    assert "a_grade_rate" in result["a_grade"]


# ---------------------------------------------------------------------------
# test_elo_override_used
# ---------------------------------------------------------------------------


def test_elo_override_used(model):
    """
    Match with home_elo_override=2000 vs away_elo=1500 -> win_prob > 0.80.

    Confirms that the override field is used instead of the fallback Elo.
    Elo diff = 2000 - 1500 = 500 -> Bradley-Terry p = 1/(1+10^(-500/400)) ≈ 0.856
    After draw suppression on group stage -> win_prob roughly 0.65+
    """
    game = {
        "year": 2022,
        "stage": GROUP_STAGE,
        "group": "A",
        "home_team": "UnknownTeam",      # not in fake_elo -> fallback=1500 without override
        "away_team": "AnotherUnknown",   # not in fake_elo -> fallback=1500 without override
        "home_score": 1,
        "away_score": 0,
        "outcome": "W",
        "league": "wc",
        "home_elo_override": 2000,       # explicit strong team
        "away_elo_override": 1500,       # explicit weak team
    }
    game_copy = dict(game)
    result = model.predict(game_copy)
    assert result["win_prob"] > 0.80, (
        f"Expected win_prob > 0.80 with Elo diff 500, got {result['win_prob']:.4f}. "
        "Check that home_elo_override is being used."
    )


# ---------------------------------------------------------------------------
# test_no_draw_in_knockout_labels
# ---------------------------------------------------------------------------


def test_no_draw_in_knockout_labels():
    """All knockout records in WC_HISTORICAL have outcome in {'W','L'} (no 'D')."""
    knockout_matches = [
        m for m in WC_HISTORICAL if m["stage"] in KNOCKOUT_STAGES
    ]
    assert len(knockout_matches) == 32, (
        f"Expected 32 knockout matches (16+16), got {len(knockout_matches)}"
    )
    for m in knockout_matches:
        assert m["outcome"] in {"W", "L"}, (
            f"Knockout match has invalid outcome={m['outcome']!r}: "
            f"{m['home_team']} vs {m['away_team']} ({m['year']} {m['stage']})"
        )


# ---------------------------------------------------------------------------
# test_historical_data_count
# ---------------------------------------------------------------------------


def test_historical_data_count():
    """len(WC_HISTORICAL) == 128 (64 per tournament)."""
    assert len(WC_HISTORICAL) == 128, (
        f"Expected 128 matches, got {len(WC_HISTORICAL)}. "
        "Check that all WC 2018 and 2022 group + knockout matches are included."
    )


def test_historical_data_count_per_tournament():
    """Each tournament has exactly 64 matches."""
    for year in [2018, 2022]:
        count = len(get_matches(year=year))
        assert count == 64, f"Expected 64 matches for {year}, got {count}"


def test_historical_group_stage_count():
    """Group stage has 96 matches (48 per tournament)."""
    group_matches = get_matches(stage=GROUP_STAGE)
    assert len(group_matches) == 96, (
        f"Expected 96 group stage matches (48 per tournament), got {len(group_matches)}"
    )


# ---------------------------------------------------------------------------
# test_league_field
# ---------------------------------------------------------------------------


def test_all_records_have_league_wc():
    """All records in WC_HISTORICAL have league='wc' (required by WCMatchModel)."""
    for m in WC_HISTORICAL:
        assert m.get("league") == "wc", (
            f"Record missing league='wc': {m['home_team']} vs {m['away_team']}"
        )
