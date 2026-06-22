"""Explainable, bounded tactical matchup comparison for World Cup teams."""
from __future__ import annotations

from dataclasses import dataclass
import math

from alpha.data.ingestion.wc_tactics import WCTacticalProfile


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class WCTacticalComparison:
    home_team: str
    away_team: str
    home_attack_multiplier: float
    away_attack_multiplier: float
    home_components: dict[str, float]
    away_components: dict[str, float]
    home_explanations: tuple[str, ...]
    away_explanations: tuple[str, ...]
    home_formation: str
    away_formation: str


def _components(attack: WCTacticalProfile, defense: WCTacticalProfile) -> dict[str, float]:
    chance_creation = _clamp((((attack.shots_for + defense.shots_allowed) / 2.0) - 12.0) / 8.0)
    control = _clamp((attack.possession - defense.possession) / 0.25)
    press_resistance = _clamp(
        ((attack.pass_completion - 0.78) / 0.15)
        - ((defense.pressing_proxy - 3.5) / 3.5)
    )
    clearance_pressure = (defense.clearances - 15.0) / 25.0
    directness = _clamp(((attack.long_ball_rate - 0.10) / 0.10) - clearance_pressure)
    width = _clamp(((attack.cross_rate - 0.04) / 0.04) - clearance_pressure)
    set_pieces = _clamp((((attack.corners_for + defense.corners_allowed) / 2.0) - 5.0) / 4.0)
    defensive_block = _clamp(
        ((defense.clearances - 15.0) / 25.0)
        + ((12.0 - defense.shots_allowed) / 8.0)
    )
    return {
        "chance creation": chance_creation,
        "possession control": control,
        "press resistance": press_resistance,
        "directness vs block": directness,
        "width vs block": width,
        "set-piece pressure": set_pieces,
        "opponent defensive block": -defensive_block,
    }


_WEIGHTS = {
    "chance creation": 0.035,
    "possession control": 0.015,
    "press resistance": 0.015,
    "directness vs block": 0.010,
    "width vs block": 0.010,
    "set-piece pressure": 0.015,
    "opponent defensive block": 0.015,
}


def _multiplier(components: dict[str, float]) -> float:
    log_adjustment = sum(_WEIGHTS[name] * value for name, value in components.items())
    return round(max(0.90, min(1.10, math.exp(log_adjustment))), 4)


def _explanations(components: dict[str, float]) -> tuple[str, ...]:
    ranked = sorted(components.items(), key=lambda item: abs(item[1]), reverse=True)
    return tuple(
        f"{name}: {'edge' if value > 0 else 'disadvantage'} ({value:+.2f})"
        for name, value in ranked[:3]
        if abs(value) >= 0.10
    )


def compare_tactics(
    home: WCTacticalProfile,
    away: WCTacticalProfile,
) -> WCTacticalComparison:
    """Compare both attacks symmetrically; formations are descriptive only."""
    home_components = _components(home, away)
    away_components = _components(away, home)
    return WCTacticalComparison(
        home_team=home.team,
        away_team=away.team,
        home_attack_multiplier=_multiplier(home_components),
        away_attack_multiplier=_multiplier(away_components),
        home_components={key: round(value, 4) for key, value in home_components.items()},
        away_components={key: round(value, 4) for key, value in away_components.items()},
        home_explanations=_explanations(home_components),
        away_explanations=_explanations(away_components),
        home_formation=home.formation,
        away_formation=away.formation,
    )

