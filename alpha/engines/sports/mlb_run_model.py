"""
MLBRunModel — independent expected-runs model producing moneyline win
probabilities from TeamSideFeatures + GameContext.

Pipeline:
  1. Expected runs per side = league baseline
       x offense factor   (season RPG blended with last-10, shrunk)
       x pitcher factor   (opposing starter run prevention vs league)
       x park factor      (neutral 1.0 when unsourced)
       x home/away factor (small structural home edge)
  2. Win probability via Pythagenpat from the two expected-run totals.

Fail-closed contract:
  - Missing inputs are replaced by NEUTRAL factors (1.0) for the
    probability estimate, but every neutral substitution is recorded in
    ``neutral_factors_used`` and surfaced through ``missing_features``.
  - The model is UNCALIBRATED until enough graded chronological history
    exists.  ``evaluate_paper_gate`` therefore always refuses with
    ``calibrator_not_fitted`` until a fitted calibrator is supplied.
  - There is NO real-money execution path here, by design.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from alpha.engines.sports.mlb_features import (
    FEATURE_SCHEMA_VERSION,
    LEAGUE_RUNS_PER_GAME,
    LEAGUE_XERA,
    GameContext,
    TeamSideFeatures,
    shrink_to_prior,
)

logger = logging.getLogger(__name__)

MODEL_VERSION = "mlb_run_model_v1"

# Structural home advantage in MLB is ~54% of run differential; expressed
# here as a small multiplicative bump/penalty on expected runs.
HOME_RUNS_FACTOR = 1.024
AWAY_RUNS_FACTOR = 0.976

# Clamp factors so one noisy feed can never produce an absurd probability.
_FACTOR_FLOOR = 0.70
_FACTOR_CEIL = 1.30

# Minimum graded, chronologically-ordered predictions before a calibrator
# may be fitted.  Until then every paper-bet evaluation refuses.
MIN_CALIBRATION_SAMPLES = 150


def _clamp(x: float) -> float:
    return max(_FACTOR_FLOOR, min(_FACTOR_CEIL, x))


@dataclass
class RunModelPrediction:
    home_win_prob: float
    away_win_prob: float
    expected_runs_home: float
    expected_runs_away: float
    missing_features: list[str] = field(default_factory=list)
    neutral_factors_used: list[str] = field(default_factory=list)
    model_version: str = MODEL_VERSION
    feature_schema_version: str = FEATURE_SCHEMA_VERSION


@dataclass
class PaperGateResult:
    decision: str  # "NO_BET" | "PAPER_BET"
    reasons: list[str] = field(default_factory=list)
    calibrator_status: str = "not_fitted"


class MLBRunModel:
    """Independent MLB moneyline model.  Paper-mode only."""

    def __init__(self) -> None:
        # No fitted calibrator exists yet; remains False until a real
        # chronological calibration set is available (see
        # MIN_CALIBRATION_SAMPLES).  Never set this without fitted data.
        self.calibrator_fitted: bool = False

    @property
    def calibrator_status(self) -> str:
        return "fitted" if self.calibrator_fitted else "not_fitted"

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(
        self,
        home: TeamSideFeatures,
        away: TeamSideFeatures,
        context: GameContext,
    ) -> RunModelPrediction:
        missing: list[str] = []
        missing.extend(f"home.{m}" for m in home.all_missing_features())
        missing.extend(f"away.{m}" for m in away.all_missing_features())
        missing.extend(f"context.{m}" for m in context.missing_context_features())

        neutral: list[str] = []

        home_off = self._offense_factor(home, "home", neutral)
        away_off = self._offense_factor(away, "away", neutral)
        # Each offense faces the OPPOSING starter.
        home_vs_pitcher = self._pitcher_factor(away, "away", neutral)
        away_vs_pitcher = self._pitcher_factor(home, "home", neutral)

        if context.park_factor is not None:
            park = _clamp(float(context.park_factor))
        else:
            park = 1.0
            neutral.append("context.park_factor")

        exp_home = (
            LEAGUE_RUNS_PER_GAME * home_off * home_vs_pitcher * park * HOME_RUNS_FACTOR
        )
        exp_away = (
            LEAGUE_RUNS_PER_GAME * away_off * away_vs_pitcher * park * AWAY_RUNS_FACTOR
        )

        home_p = self._pythagenpat(exp_home, exp_away)

        return RunModelPrediction(
            home_win_prob=round(home_p, 6),
            away_win_prob=round(1.0 - home_p, 6),
            expected_runs_home=round(exp_home, 3),
            expected_runs_away=round(exp_away, 3),
            missing_features=missing,
            neutral_factors_used=neutral,
        )

    # ------------------------------------------------------------------
    # Paper-bet gate (fail closed)
    # ------------------------------------------------------------------

    def evaluate_paper_gate(
        self,
        prediction: RunModelPrediction,
        context: GameContext,
        real_odds_present: bool,
    ) -> PaperGateResult:
        """
        Decide whether a PAPER bet may even be recorded as actionable.
        Any single refusal reason blocks the bet.  This gate can only
        become more permissive when real data (calibration history,
        confirmed pitchers, live odds) exists — never by default.
        """
        reasons: list[str] = []
        if not self.calibrator_fitted:
            reasons.append("calibrator_not_fitted")
        if prediction.missing_features:
            reasons.append("required_features_missing")
        if prediction.neutral_factors_used:
            reasons.append("neutral_factors_substituted")
        if not context.probable_pitchers_confirmed:
            reasons.append("probable_pitchers_not_confirmed")
        if not real_odds_present:
            reasons.append("real_odds_missing")

        decision = "NO_BET" if reasons else "PAPER_BET"
        return PaperGateResult(
            decision=decision,
            reasons=reasons,
            calibrator_status=self.calibrator_status,
        )

    # ------------------------------------------------------------------
    # Internal factors
    # ------------------------------------------------------------------

    @staticmethod
    def _offense_factor(
        side: TeamSideFeatures, label: str, neutral: list[str]
    ) -> float:
        off = side.offense
        if off is None or off.runs_per_game_season is None:
            neutral.append(f"{label}.offense")
            return 1.0
        season = shrink_to_prior(
            off.runs_per_game_season, off.games_sample, LEAGUE_RUNS_PER_GAME, 30.0
        )
        if off.runs_per_game_last10 is not None:
            blended = 0.7 * season + 0.3 * float(off.runs_per_game_last10)
        else:
            blended = season
            neutral.append(f"{label}.offense.runs_per_game_last10")
        return _clamp(blended / LEAGUE_RUNS_PER_GAME)

    @staticmethod
    def _pitcher_factor(
        opposing_side: TeamSideFeatures, label: str, neutral: list[str]
    ) -> float:
        """Run-scoring multiplier the OPPOSING starter imposes on a lineup."""
        sp = opposing_side.starter
        if sp is None:
            neutral.append(f"{label}.starter")
            return 1.0
        # Prefer xERA, then FIP, then ERA — all innings-shrunk.
        for fname in ("xera", "fip", "era"):
            value = sp.shrunk(fname)
            if value is not None:
                return _clamp(float(value) / LEAGUE_XERA)
        neutral.append(f"{label}.starter.run_prevention")
        return 1.0

    @staticmethod
    def _pythagenpat(runs_for: float, runs_against: float) -> float:
        """Pythagenpat win expectancy with dynamic exponent."""
        total = max(runs_for + runs_against, 0.1)
        exponent = total ** 0.287
        rf = max(runs_for, 0.01) ** exponent
        ra = max(runs_against, 0.01) ** exponent
        return rf / (rf + ra)


def can_fit_calibrator(num_graded_chronological: int) -> bool:
    """Calibrator fitting is allowed only with sufficient graded history."""
    return num_graded_chronological >= MIN_CALIBRATION_SAMPLES
