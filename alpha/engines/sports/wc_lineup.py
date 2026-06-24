"""
LineupProjector — starter probability estimation and line score aggregation.

Design:
  - Input: squad dict {player_name: PlayerInfo}
  - Output: LineupFeatures dataclass
  - Line scores use SUM (not mean) so 11-player squad scores higher than 10-player
  - Absence impact = player_value - replacement_value in same role (>=0)
  - Uncertainty band = std dev of p_start values across squad
  - Continuity modifier for back-line/GK changes vs reference lineup

Phase 30 will populate real FBref/Understat player values into the same
PlayerInfo structure. Phase 32 wires this into the full stacked model.
wc_scanner.py is NOT modified.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TypedDict


# ---------------------------------------------------------------------------
# Role → line mapping
# ---------------------------------------------------------------------------

LINE_GROUPS: dict[str, frozenset[str]] = {
    "GK":       frozenset({"GK"}),
    "Back":     frozenset({"CB", "LB", "RB"}),
    "Midfield": frozenset({"DM", "CM"}),
    "Front":    frozenset({"LW", "RW", "ST", "SS"}),
}

# Roles considered for continuity check (GK + center-backs)
_CONTINUITY_ROLES: frozenset[str] = frozenset({"GK", "CB"})

# Probability threshold above which a player is "clearly starting"
_STARTER_THRESHOLD: float = 0.5

# Std-dev threshold above which we consider the XI well-determined ("HIGH" confidence)
_CONFIDENCE_THRESHOLD: float = 0.35


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PlayerInfo:
    """Per-player input to LineupProjector."""

    role: str
    """Position role: GK, CB, LB, RB, DM, CM, LW, RW, ST, SS."""

    p_start: float
    """Starter probability in [0.0, 1.0]."""

    value: float
    """Player quality score (0–100 scale). Phase 30 populates real values."""

    replacement_value: float
    """Best available replacement's value in the same role."""


@dataclass
class LineupFeatures:
    """Output of LineupProjector.project()."""

    gk_score: float
    """Sum of (value × p_start) for GK line."""

    back_score: float
    """Sum of (value × p_start) for Back line (CB, LB, RB)."""

    midfield_score: float
    """Sum of (value × p_start) for Midfield line (DM, CM)."""

    front_score: float
    """Sum of (value × p_start) for Front line (LW, RW, ST, SS)."""

    total_score: float
    """Sum of all four line scores."""

    expected_starters: float
    """Sum of all p_start values — should be ~11 for a full squad."""

    absence_impacts: dict[str, float]
    """player_name → positive absence delta (max(0, value − replacement_value))."""

    uncertainty_band: float
    """Std dev of p_start values. High = XI is well-determined (low uncertainty)."""

    continuity_modifier: float
    """0.0 if reference lineup unchanged; −0.05 per GK or CB that changed."""

    lineup_confidence: str
    """'HIGH' if uncertainty_band > _CONFIDENCE_THRESHOLD, else 'LOW'."""


# ---------------------------------------------------------------------------
# Helper: build a mock squad for testing and demo
# ---------------------------------------------------------------------------

def build_mock_squad(team_strength: float = 75.0) -> dict[str, PlayerInfo]:
    """
    Build a 16-player mock squad with realistic p_start values.

    team_strength scales the value field (0–100). Used in unit tests and
    the wc_eval.py demo section.
    """
    # Typical 4-3-3 / 4-2-3-1 shape
    players: list[tuple[str, str, float, float]] = [
        # name, role, p_start, value_fraction
        ("GK1",   "GK",  0.95, 1.00),
        ("GK2",   "GK",  0.05, 0.60),
        ("CB1",   "CB",  0.92, 0.90),
        ("CB2",   "CB",  0.90, 0.88),
        ("CB3",   "CB",  0.10, 0.65),
        ("LB1",   "LB",  0.88, 0.85),
        ("RB1",   "RB",  0.85, 0.82),
        ("DM1",   "DM",  0.93, 0.92),
        ("DM2",   "DM",  0.08, 0.62),
        ("CM1",   "CM",  0.87, 0.88),
        ("CM2",   "CM",  0.82, 0.84),
        ("CM3",   "CM",  0.12, 0.58),
        ("LW1",   "LW",  0.90, 0.95),
        ("RW1",   "RW",  0.88, 0.90),
        ("ST1",   "ST",  0.92, 0.98),
        ("ST2",   "ST",  0.08, 0.65),
    ]
    squad: dict[str, PlayerInfo] = {}
    for name, role, p_start, value_fraction in players:
        value = team_strength * value_fraction
        # Replacement value is the second-best player in the same role
        replacement = team_strength * max(0.55, value_fraction - 0.30)
        squad[name] = PlayerInfo(
            role=role,
            p_start=p_start,
            value=value,
            replacement_value=replacement,
        )
    return squad


# ---------------------------------------------------------------------------
# LineupProjector
# ---------------------------------------------------------------------------

class LineupProjector:
    """
    Projects lineup features from a squad's starter probability estimates.

    Parameters
    ----------
    reference_lineup : dict[str, str] | None
        {player_name: role} of the last confirmed lineup.
        Used to compute the continuity modifier. None = no continuity check.
    """

    def __init__(
        self,
        reference_lineup: dict[str, str] | None = None,
    ) -> None:
        self._reference: dict[str, str] = reference_lineup or {}

    def project(self, squad: dict[str, PlayerInfo]) -> LineupFeatures:
        """
        Compute lineup features from squad starter probabilities.

        Parameters
        ----------
        squad : dict[str, PlayerInfo]
            {player_name: PlayerInfo} for all squad members.

        Returns
        -------
        LineupFeatures
            Aggregated line scores, absence impacts, uncertainty, continuity.
        """
        if not squad:
            return LineupFeatures(
                gk_score=0.0,
                back_score=0.0,
                midfield_score=0.0,
                front_score=0.0,
                total_score=0.0,
                expected_starters=0.0,
                absence_impacts={},
                uncertainty_band=0.0,
                continuity_modifier=0.0,
                lineup_confidence="LOW",
            )

        # 1. Line scores (SUM × p_start — so 11 > 10)
        line_scores: dict[str, float] = {line: 0.0 for line in LINE_GROUPS}
        for player, info in squad.items():
            for line, roles in LINE_GROUPS.items():
                if info.role in roles:
                    line_scores[line] += info.value * info.p_start

        # 2. Expected starters
        expected_starters = sum(p.p_start for p in squad.values())

        # 3. Absence impacts (always non-negative)
        absence_impacts: dict[str, float] = {
            name: max(0.0, info.value - info.replacement_value)
            for name, info in squad.items()
        }

        # 4. Uncertainty band — std dev of p_start values
        p_starts = [p.p_start for p in squad.values()]
        n = len(p_starts)
        mean_p = sum(p_starts) / n
        variance = sum((p - mean_p) ** 2 for p in p_starts) / n
        uncertainty_band = math.sqrt(variance)

        # 5. Continuity modifier — −0.05 per GK or CB that is new vs reference
        continuity_modifier = 0.0
        if self._reference:
            # Players clearly starting in this squad (p_start > threshold)
            current_starters = {
                name
                for name, info in squad.items()
                if info.role in _CONTINUITY_ROLES and info.p_start > _STARTER_THRESHOLD
            }
            # Players in reference lineup with continuity roles
            reference_starters = {
                name
                for name, role in self._reference.items()
                if role in _CONTINUITY_ROLES
            }
            new_players = current_starters - reference_starters
            continuity_modifier = -0.05 * len(new_players)

        # 6. Lineup confidence
        lineup_confidence = "HIGH" if uncertainty_band > _CONFIDENCE_THRESHOLD else "LOW"

        total_score = sum(line_scores.values())

        return LineupFeatures(
            gk_score=line_scores["GK"],
            back_score=line_scores["Back"],
            midfield_score=line_scores["Midfield"],
            front_score=line_scores["Front"],
            total_score=total_score,
            expected_starters=expected_starters,
            absence_impacts=absence_impacts,
            uncertainty_band=uncertainty_band,
            continuity_modifier=continuity_modifier,
            lineup_confidence=lineup_confidence,
        )
