"""Tests for the MLB run model, feature schema, and fail-closed paper gate."""
from __future__ import annotations

import pytest

from alpha.engines.sports.mlb_features import (
    GameContext,
    StarterFeatures,
    TeamOffenseFeatures,
    TeamSideFeatures,
    shrink_to_prior,
)
from alpha.engines.sports.mlb_run_model import (
    MIN_CALIBRATION_SAMPLES,
    MLBRunModel,
    can_fit_calibrator,
)


def _context(**overrides) -> GameContext:
    base = dict(
        event_id="mlb-statsapi-1",
        game_date="2026-06-11",
        commence_time_utc="2026-06-11T23:05:00Z",
        home_team="New York Yankees",
        away_team="Toronto Blue Jays",
        venue="Yankee Stadium",
    )
    base.update(overrides)
    return GameContext(**base)


def _full_side(team: str, era: float = 4.30) -> TeamSideFeatures:
    return TeamSideFeatures(
        team=team,
        starter=StarterFeatures(
            pitcher_id=1, pitcher_name="A Pitcher", throws="R",
            starts_sample=15, innings_sample=90.0,
            era=era, xera=era, fip=era, whip=1.25,
            k_per9=9.0, bb_per9=2.8, hr_per9=1.1, xwoba_allowed=0.310,
            days_rest=5, velocity_delta_last3=0.1, pitch_count_last_start=95,
        ),
        offense=TeamOffenseFeatures(
            team=team, runs_per_game_season=4.6, runs_per_game_last10=4.8,
            woba_season=0.320, obp_season=0.320, slg_season=0.410,
            k_rate_batting=0.22, bb_rate_batting=0.085, games_sample=60,
        ),
        lineup_confirmed=True,
        bullpen_xera=4.2,
    )


# ---------------------------------------------------------------------------
# Shrinkage
# ---------------------------------------------------------------------------

def test_shrinkage_pulls_small_samples_toward_prior():
    small = shrink_to_prior(2.00, 10, 4.30, 40.0)
    large = shrink_to_prior(2.00, 200, 4.30, 40.0)
    assert small is not None and large is not None
    assert small > large  # small sample sits closer to the 4.30 prior
    assert 2.0 < small < 4.30
    assert abs(large - 2.0) < abs(small - 2.0)


def test_shrinkage_never_invents_values():
    assert shrink_to_prior(None, 100, 4.30, 40.0) is None


def test_zero_sample_collapses_to_prior():
    assert shrink_to_prior(1.00, 0, 4.30, 40.0) == pytest.approx(4.30)


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------

def test_probabilities_sum_to_one_and_home_edge_with_equal_inputs():
    model = MLBRunModel()
    pred = model.predict(_full_side("NYY"), _full_side("TOR"), _context())
    assert pred.home_win_prob + pred.away_win_prob == pytest.approx(1.0, abs=1e-6)
    assert pred.home_win_prob > 0.5  # structural home advantage only


def test_better_starter_lowers_opponent_expected_runs():
    model = MLBRunModel()
    ctx = _context()
    baseline = model.predict(_full_side("NYY"), _full_side("TOR"), ctx)
    ace_home = model.predict(_full_side("NYY", era=2.50), _full_side("TOR"), ctx)
    assert ace_home.expected_runs_away < baseline.expected_runs_away
    assert ace_home.home_win_prob > baseline.home_win_prob


def test_missing_sides_use_neutral_factors_and_record_them():
    model = MLBRunModel()
    empty = TeamSideFeatures(team="NYY")
    pred = model.predict(empty, TeamSideFeatures(team="TOR"), _context())
    assert 0.4 < pred.home_win_prob < 0.6  # neutral inputs => near coin flip
    assert any("offense" in n for n in pred.neutral_factors_used)
    assert any("starter" in n for n in pred.neutral_factors_used)
    assert "home.starter" in pred.missing_features
    assert "context.weather" in pred.missing_features


def test_mvp_placeholders_always_reported_missing():
    pred = MLBRunModel().predict(_full_side("NYY"), _full_side("TOR"), _context())
    # Full sides in this test set lineup/bullpen; strip them to MVP reality.
    side = _full_side("NYY")
    side.lineup_confirmed = False
    side.bullpen_xera = None
    missing = side.all_missing_features()
    assert "lineup_confirmed" in missing
    assert "bullpen_xera" in missing
    # Park factor and weather are unsourced in the MVP context.
    assert "context.park_factor" in pred.missing_features
    assert "context.weather" in pred.missing_features


def test_extreme_inputs_are_clamped():
    model = MLBRunModel()
    bad = _full_side("NYY", era=99.0)
    pred = model.predict(_full_side("TOR", era=0.10), bad, _context())
    assert 0.01 < pred.home_win_prob < 0.99


# ---------------------------------------------------------------------------
# Paper gate — fail closed
# ---------------------------------------------------------------------------

def test_gate_refuses_with_calibrator_not_fitted():
    model = MLBRunModel()
    ctx = _context(probable_pitchers_confirmed=True)
    pred = model.predict(_full_side("NYY"), _full_side("TOR"), ctx)
    gate = model.evaluate_paper_gate(pred, ctx, real_odds_present=True)
    assert gate.decision == "NO_BET"
    assert "calibrator_not_fitted" in gate.reasons
    assert gate.calibrator_status == "not_fitted"


def test_gate_records_missing_features_and_unconfirmed_pitchers():
    model = MLBRunModel()
    ctx = _context()  # pitchers not confirmed
    pred = model.predict(TeamSideFeatures(team="NYY"), TeamSideFeatures(team="TOR"), ctx)
    gate = model.evaluate_paper_gate(pred, ctx, real_odds_present=False)
    assert gate.decision == "NO_BET"
    for reason in (
        "calibrator_not_fitted",
        "required_features_missing",
        "probable_pitchers_not_confirmed",
        "real_odds_missing",
    ):
        assert reason in gate.reasons


def test_calibrator_fitting_requires_sufficient_history():
    assert not can_fit_calibrator(0)
    assert not can_fit_calibrator(MIN_CALIBRATION_SAMPLES - 1)
    assert can_fit_calibrator(MIN_CALIBRATION_SAMPLES)
