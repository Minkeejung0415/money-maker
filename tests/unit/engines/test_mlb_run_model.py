"""Tests: MLB run-distribution simulation model and paper-bet gating."""
from __future__ import annotations

import numpy as np
import pytest

from alpha.engines.sports.mlb_features import GameContext, TeamSideFeatures
from alpha.engines.sports.mlb_run_model import (
    MLBRunModel,
    ProbabilityCalibrator,
    RunDistribution,
    estimate_expected_runs,
    fit_run_distribution,
    simulate_game,
)


def _side(team="NYY", **overrides) -> TeamSideFeatures:
    """Fully-populated side; tests override what they probe."""
    base = dict(
        team=team,
        pitcher_confirmed=True,
        starter_name="Ace Starter",
        starter_xera=4.20,
        starter_xwoba_allowed=0.315,
        starter_throws="R",
        starter_days_since_prev_game=5.0,
        starter_expected_innings=5.5,
        lineup_confirmed=True,
        lineup_woba_vs_rhp=0.315,
        lineup_woba_vs_lhp=0.315,
        bullpen_ip_last1=2.0,
        bullpen_ip_last3=8.0,
        high_leverage_available=True,
        closer_available=True,
        bullpen_xera=4.30,
        runs_per_game=4.5,
    )
    base.update(overrides)
    return TeamSideFeatures(**base)


# ---------------------------------------------------------------------------
# Expected runs
# ---------------------------------------------------------------------------

def test_neutral_inputs_give_league_average_runs():
    mu, missing = estimate_expected_runs(_side(), _side("BOS"))
    assert mu == pytest.approx(4.5, abs=0.15)
    assert missing == []


def test_better_opposing_starter_reduces_runs():
    base, _ = estimate_expected_runs(_side(), _side("BOS"))
    vs_ace, _ = estimate_expected_runs(_side(), _side("BOS", starter_xera=2.80))
    vs_scrub, _ = estimate_expected_runs(_side(), _side("BOS", starter_xera=5.80))
    assert vs_ace < base < vs_scrub


def test_lineup_handedness_matchup_used():
    """Vs a LHP, the lineup's wOBA-vs-LHP drives the estimate."""
    crushes_lefties = _side(lineup_woba_vs_lhp=0.360, lineup_woba_vs_rhp=0.290)
    vs_lhp, _ = estimate_expected_runs(
        crushes_lefties, _side("BOS", starter_throws="L"))
    vs_rhp, _ = estimate_expected_runs(
        crushes_lefties, _side("BOS", starter_throws="R"))
    assert vs_lhp > vs_rhp


def test_bullpen_fatigue_increases_runs():
    fresh, _ = estimate_expected_runs(_side(), _side("BOS", bullpen_ip_last3=6.0))
    gassed, _ = estimate_expected_runs(_side(), _side("BOS", bullpen_ip_last3=16.0))
    assert gassed > fresh


def test_unavailable_high_leverage_and_closer_increase_runs():
    full, _ = estimate_expected_runs(_side(), _side("BOS"))
    depleted, _ = estimate_expected_runs(
        _side(), _side("BOS", high_leverage_available=False, closer_available=False))
    assert depleted > full


def test_park_and_weather_adjustments():
    coors = GameContext(park_factor_runs=1.15, temperature_f=70.0, wind_mph_out=0.0)
    neutral = GameContext(park_factor_runs=1.0, temperature_f=70.0, wind_mph_out=0.0)
    hi, _ = estimate_expected_runs(_side(), _side("BOS"), coors)
    lo, _ = estimate_expected_runs(_side(), _side("BOS"), neutral)
    assert hi == pytest.approx(lo * 1.15, rel=0.01)

    hot_wind_out = GameContext(park_factor_runs=1.0, temperature_f=95.0, wind_mph_out=12.0)
    hot, _ = estimate_expected_runs(_side(), _side("BOS"), hot_wind_out)
    assert hot > lo


def test_roof_closed_suppresses_weather():
    open_hot = GameContext(park_factor_runs=1.0, temperature_f=95.0,
                           wind_mph_out=10.0, roof_status="open")
    closed_hot = GameContext(park_factor_runs=1.0, temperature_f=95.0,
                             wind_mph_out=10.0, roof_status="closed")
    mu_open, _ = estimate_expected_runs(_side(), _side("BOS"), open_hot)
    mu_closed, _ = estimate_expected_runs(_side(), _side("BOS"), closed_hot)
    neutral, _ = estimate_expected_runs(
        _side(), _side("BOS"),
        GameContext(park_factor_runs=1.0, temperature_f=70.0, wind_mph_out=0.0))
    assert mu_open > mu_closed
    assert mu_closed == pytest.approx(neutral, rel=1e-6)


def test_missing_features_tracked_not_invented():
    sparse = TeamSideFeatures(team="NYY", pitcher_confirmed=True)
    mu, missing = estimate_expected_runs(_side(), sparse)
    assert mu > 0
    assert "starter_xera" in missing
    assert "bullpen_xera" in missing
    assert "bullpen_ip_last3" in missing


# ---------------------------------------------------------------------------
# Distribution fitting: Poisson vs NegBin
# ---------------------------------------------------------------------------

def test_overdispersed_runs_prefer_negbin():
    rng = np.random.default_rng(7)
    # Real MLB runs: var ~ 9-10 vs mean ~4.5 → strongly overdispersed.
    r, mu = 4.0, 4.5
    samples = rng.negative_binomial(r, r / (r + mu), size=2000)
    dist = fit_run_distribution(samples)
    assert dist.family == "negbin"
    assert dist.alpha > 0
    assert dist.aic_negbin < dist.aic_poisson


def test_equidispersed_runs_prefer_poisson():
    rng = np.random.default_rng(7)
    samples = rng.poisson(4.5, size=2000)
    dist = fit_run_distribution(samples)
    assert dist.family == "poisson"


def test_fit_requires_minimum_samples():
    with pytest.raises(ValueError, match="20"):
        fit_run_distribution([4, 5, 3])


def test_with_mean_keeps_family_and_dispersion():
    dist = RunDistribution(family="negbin", mu=4.5, alpha=0.25)
    moved = dist.with_mean(5.2)
    assert moved.family == "negbin"
    assert moved.alpha == 0.25
    assert moved.mu == 5.2


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def test_simulation_probs_sum_to_one_no_ties():
    home = RunDistribution(family="negbin", mu=5.0, alpha=0.2)
    away = RunDistribution(family="negbin", mu=4.0, alpha=0.2)
    out = simulate_game(home, away, n_sims=20_000, total_line=8.5)
    assert out["independent_home_win_prob"] + out["independent_away_win_prob"] == pytest.approx(1.0)
    assert out["independent_home_win_prob"] > 0.5  # better team favored
    assert out["over_prob"] + out["under_prob"] == pytest.approx(1.0)  # .5 line: no pushes
    assert out["n_sims"] == 20_000


def test_simulation_expected_totals_match_inputs():
    home = RunDistribution(family="poisson", mu=4.5)
    away = RunDistribution(family="poisson", mu=4.5)
    out = simulate_game(home, away, n_sims=50_000, seed=1)
    # Extra innings add a touch above mu_home + mu_away.
    assert out["expected_total_runs"] == pytest.approx(9.0, abs=0.35)
    assert out["independent_home_win_prob"] == pytest.approx(0.5, abs=0.02)


def test_integer_total_line_reports_push_prob():
    home = RunDistribution(family="poisson", mu=4.5)
    away = RunDistribution(family="poisson", mu=4.5)
    out = simulate_game(home, away, n_sims=20_000, total_line=9.0)
    assert out["push_prob"] > 0
    assert out["over_prob"] + out["under_prob"] + out["push_prob"] == pytest.approx(1.0)


def test_simulation_minimum_sims_enforced():
    d = RunDistribution(family="poisson", mu=4.5)
    with pytest.raises(ValueError):
        simulate_game(d, d, n_sims=100)


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def test_calibrator_identity_until_fitted():
    cal = ProbabilityCalibrator()
    assert cal.fitted is False
    assert cal.transform(0.6) == pytest.approx(0.6, abs=1e-9)


def test_calibrator_corrects_overconfidence():
    rng = np.random.default_rng(3)
    # Model says p, reality behaves like a flatter 0.5 + 0.5*(p-0.5).
    raw = rng.uniform(0.2, 0.8, size=2000)
    true = 0.5 + 0.5 * (raw - 0.5)
    outcomes = (rng.random(2000) < true).astype(int)
    cal = ProbabilityCalibrator()
    cal.fit(raw.tolist(), outcomes.tolist())
    assert cal.fitted
    # Overconfident high prob is pulled toward 0.5.
    assert cal.transform(0.80) < 0.78
    assert cal.transform(0.20) > 0.22
    # Monotone.
    assert cal.transform(0.7) > cal.transform(0.6) > cal.transform(0.5)


def test_calibrator_requires_minimum_samples():
    with pytest.raises(ValueError):
        ProbabilityCalibrator().fit([0.5] * 10, [1] * 10)


# ---------------------------------------------------------------------------
# Paper-bet gating (fail closed)
# ---------------------------------------------------------------------------

def _fitted_calibrator() -> ProbabilityCalibrator:
    cal = ProbabilityCalibrator()
    cal.a, cal.b, cal.fitted, cal.n_fit = 1.0, 0.0, True, 100
    return cal


def _real_odds_game(**over):
    g = {"home_team": "NYY", "away_team": "BOS", "home_odds": -120,
         "away_odds": 100, "has_real_odds": True}
    g.update(over)
    return g


def test_no_bet_without_real_odds():
    model = MLBRunModel(calibrator=_fitted_calibrator())
    # StatsAPI placeholder game: -110/-110 with has_real_odds=False.
    game = _real_odds_game(has_real_odds=False, home_odds=-110, away_odds=-110)
    out = model.evaluate_paper_bet(game, _side(), _side("BOS"))
    assert out["bet_side"] == "no_bet"
    assert "no_real_odds" in out["reasons"]


def test_no_bet_without_confirmed_pitchers():
    model = MLBRunModel(calibrator=_fitted_calibrator())
    out = model.evaluate_paper_bet(
        _real_odds_game(), _side(pitcher_confirmed=False), _side("BOS"))
    assert out["bet_side"] == "no_bet"
    assert "home_pitcher_unconfirmed" in out["reasons"]


def test_no_bet_with_missing_required_features():
    model = MLBRunModel(calibrator=_fitted_calibrator())
    out = model.evaluate_paper_bet(
        _real_odds_game(), _side(starter_xera=None), _side("BOS"))
    assert out["bet_side"] == "no_bet"
    assert "missing:home.starter_xera" in out["reasons"]


def test_no_bet_without_fitted_calibrator():
    model = MLBRunModel()  # identity, unfitted calibrator
    out = model.evaluate_paper_bet(_real_odds_game(), _side(), _side("BOS"))
    assert out["bet_side"] == "no_bet"
    assert "calibrator_not_fitted" in out["reasons"]


def test_no_bet_when_edge_below_threshold():
    model = MLBRunModel(calibrator=_fitted_calibrator(), min_edge=0.03)
    # Symmetric teams + near-fair odds → tiny edge.
    out = model.evaluate_paper_bet(
        _real_odds_game(home_odds=-105, away_odds=-105), _side(), _side("BOS"))
    assert out["bet_side"] == "no_bet"
    assert any(r.startswith("edge_below_threshold") for r in out["reasons"])


def test_paper_bet_emitted_when_all_gates_pass():
    model = MLBRunModel(calibrator=_fitted_calibrator(), min_edge=0.03,
                        n_sims=20_000)
    # Home crushes a bad LHP starter while market prices it near even.
    home = _side(lineup_woba_vs_lhp=0.350, runs_per_game=5.4)
    away = _side("BOS", starter_throws="L", starter_xera=5.6,
                 bullpen_ip_last3=15.0, runs_per_game=3.9)
    out = model.evaluate_paper_bet(
        _real_odds_game(home_odds=-105, away_odds=-115), home, away)
    assert out["bet_side"] == "home"
    assert out["paper_only"] is True
    assert out["edge"] > 0.03
    assert out["calibrated_prob"] > out["market_no_vig_prob"]
    pred = out["prediction"]
    assert pred["source"] == "run_simulation"
    assert pred["independent_home_win_prob"] > 0.55
    assert pred["market_consensus_home_prob"] is None  # none supplied — kept separate


def test_market_consensus_kept_separate_from_independent():
    model = MLBRunModel(calibrator=_fitted_calibrator(), n_sims=10_000)
    ctx = GameContext(park_factor_runs=1.0, temperature_f=70.0,
                      wind_mph_out=0.0, consensus_no_vig_prob=0.58)
    pred = model.predict(_side(), _side("BOS"), ctx)
    assert pred["market_consensus_home_prob"] == 0.58
    # Symmetric teams: independent prob stays ~0.5 — consensus not blended in.
    assert abs(pred["independent_home_win_prob"] - 0.5) < 0.03


def test_prediction_reports_uncalibrated_state():
    model = MLBRunModel()  # unfitted
    pred = model.predict(_side(), _side("BOS"))
    assert pred["calibrated"] is False
    assert pred["final_calibrated_home_prob"] is None


def test_chronological_calibration_split_is_later():
    from alpha.engines.sports.mlb_run_model import chronological_calibration_split
    dates = [5, 1, 9, 3, 7, 2, 8, 4, 6, 0]
    earlier, calib = chronological_calibration_split(dates, calibration_frac=0.3)
    assert len(calib) == 3
    assert max(dates[i] for i in earlier) < min(dates[i] for i in calib)
    with pytest.raises(ValueError):
        chronological_calibration_split([1, 2], calibration_frac=0.0)
