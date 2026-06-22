"""Scoreline-based World Cup markets for true same-game combinations."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

from alpha.engines.sports.wc_model import KNOCKOUT_STAGES

_NEUTRAL_GOALS = 1.25
_MIN_GOALS = 0.25
_MAX_GOALS = 3.5
_MAX_SCORE = 10

_OUTCOMES = frozenset({"home_win", "draw", "away_win"})
_TOTALS = frozenset({"over_2_5", "under_2_5"})
_BTTS = frozenset({"btts_yes", "btts_no"})
_MARKETS = _OUTCOMES | _TOTALS | _BTTS


def _poisson_probability(goals: int, rate: float) -> float:
    return math.exp(-rate) * rate**goals / math.factorial(goals)


def _outcome(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home_win"
    if home_goals < away_goals:
        return "away_win"
    return "draw"


def _matches(score: tuple[int, int], market: str) -> bool:
    home_goals, away_goals = score
    if market in _OUTCOMES:
        return _outcome(home_goals, away_goals) == market
    if market == "over_2_5":
        return home_goals + away_goals >= 3
    if market == "under_2_5":
        return home_goals + away_goals <= 2
    if market == "btts_yes":
        return home_goals > 0 and away_goals > 0
    if market == "btts_no":
        return home_goals == 0 or away_goals == 0
    raise ValueError(f"Unknown World Cup market: {market}")


@dataclass(frozen=True)
class WCScorelineDistribution:
    """Normalized probabilities over regulation-time scorelines."""

    cells: Mapping[tuple[int, int], float]
    home_lambda: float
    away_lambda: float
    outcome_available: bool

    def probability(self, market: str) -> float:
        if market not in _MARKETS:
            raise ValueError(f"Unknown World Cup market: {market}")
        if market in _OUTCOMES and not self.outcome_available:
            raise ValueError("Regulation-time 1X2 is not available for this stage")
        return sum(prob for score, prob in self.cells.items() if _matches(score, market))

    def joint_probability(self, markets: Sequence[str]) -> float:
        if not markets:
            raise ValueError("At least one market is required")
        if len(set(markets)) != len(markets):
            raise ValueError("Duplicate markets are not a valid combination")
        unknown = set(markets) - _MARKETS
        if unknown:
            raise ValueError(f"Unknown World Cup market: {sorted(unknown)[0]}")
        if not self.outcome_available and set(markets) & _OUTCOMES:
            raise ValueError("Regulation-time 1X2 is not available for this stage")
        for family in (_OUTCOMES, _TOTALS, _BTTS):
            if len(set(markets) & family) > 1:
                raise ValueError("Contradictory legs are not a valid combination")
        return sum(
            prob
            for score, prob in self.cells.items()
            if all(_matches(score, market) for market in markets)
        )


class WCScorelineModel:
    """Build scoreline distributions from WC team priors and Elo outcomes."""

    def __init__(self, team_stats: Mapping[str, Mapping[str, float]] | None = None) -> None:
        self._team_stats = team_stats or {}

    @staticmethod
    def _bounded_rate(value: object) -> float:
        try:
            rate = float(value)
        except (TypeError, ValueError):
            rate = _NEUTRAL_GOALS
        if not math.isfinite(rate) or rate <= 0:
            rate = _NEUTRAL_GOALS
        return max(_MIN_GOALS, min(_MAX_GOALS, rate))

    def _goal_rates(
        self,
        home_team: str,
        away_team: str,
        team_stats: Mapping[str, Mapping[str, float]],
        elo_diff: float,
    ) -> tuple[float, float]:
        home = team_stats.get(home_team, {})
        away = team_stats.get(away_team, {})
        home_attack = self._bounded_rate(home.get("avg_xG", home.get("avg_goals")))
        away_attack = self._bounded_rate(away.get("avg_xG", away.get("avg_goals")))
        home_defense = self._bounded_rate(home.get("defense_score"))
        away_defense = self._bounded_rate(away.get("defense_score"))
        matchup_factor = math.sqrt(10.0 ** (max(-800.0, min(800.0, elo_diff)) / 1600.0))
        tactical = None
        # Kept outside the team profile contract so tactics never masquerade
        # as historical strength.
        if isinstance(team_stats, Mapping):
            tactical = team_stats.get("__tactical_comparison__")
        home_tactical = float(getattr(tactical, "home_attack_multiplier", 1.0))
        away_tactical = float(getattr(tactical, "away_attack_multiplier", 1.0))
        return (
            self._bounded_rate(((home_attack + away_defense) / 2.0) * matchup_factor * home_tactical),
            self._bounded_rate(((away_attack + home_defense) / 2.0) / matchup_factor * away_tactical),
        )

    @staticmethod
    def _normalize(cells: dict[tuple[int, int], float]) -> dict[tuple[int, int], float]:
        total = sum(cells.values())
        if total <= 0:
            raise ValueError("Scoreline distribution has no probability mass")
        return {score: probability / total for score, probability in cells.items()}

    @staticmethod
    def _calibrate_outcomes(
        cells: dict[tuple[int, int], float], game: Mapping[str, object]
    ) -> dict[tuple[int, int], float]:
        targets = {
            "home_win": float(game.get("win_prob", 0.0)),
            "draw": float(game.get("draw_prob", 0.0)),
            "away_win": float(game.get("loss_prob", 0.0)),
        }
        if any(not math.isfinite(value) or value <= 0 for value in targets.values()):
            raise ValueError("Group-stage 1X2 probabilities must all be positive")
        target_total = sum(targets.values())
        targets = {key: value / target_total for key, value in targets.items()}
        raw = {
            result: sum(prob for score, prob in cells.items() if _outcome(*score) == result)
            for result in _OUTCOMES
        }
        calibrated = {
            score: probability * targets[_outcome(*score)] / raw[_outcome(*score)]
            for score, probability in cells.items()
        }
        return WCScorelineModel._normalize(calibrated)

    def build(self, game: Mapping[str, object]) -> WCScorelineDistribution:
        recent_stats = game.get("recent_team_stats")
        team_stats = dict(recent_stats) if isinstance(recent_stats, Mapping) else dict(self._team_stats)
        if game.get("tactical_comparison") is not None and game.get("tactical_goal_authorized") is True:
            team_stats["__tactical_comparison__"] = game["tactical_comparison"]
        home_lambda, away_lambda = self._goal_rates(
            str(game.get("home_team", "")),
            str(game.get("away_team", "")),
            team_stats,
            float(game.get("elo_diff", 0.0)),
        )
        cells = {
            (home_goals, away_goals): _poisson_probability(home_goals, home_lambda)
            * _poisson_probability(away_goals, away_lambda)
            for home_goals in range(_MAX_SCORE + 1)
            for away_goals in range(_MAX_SCORE + 1)
        }
        cells = self._normalize(cells)
        outcome_available = str(game.get("stage", "GROUP_STAGE")) not in KNOCKOUT_STAGES
        if outcome_available:
            cells = self._calibrate_outcomes(cells, game)
        return WCScorelineDistribution(
            cells=cells,
            home_lambda=home_lambda,
            away_lambda=away_lambda,
            outcome_available=outcome_available,
        )
