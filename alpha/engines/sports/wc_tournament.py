"""
wc_tournament.py — Tournament-state logic for WC 2026 model.

Provides:
    - TournamentState: qualification pressure, rotation risk, yellow-card
      suspension risk, best-third-place ranking, and tiebreak features.

No live data — pure deterministic computation from group standings input.

TOURNEY-01: Qualification pressure states
TOURNEY-02: Rotation risk flag
TOURNEY-03: Yellow-card suspension risk + card resets
TOURNEY-04: Best-third-place ranking (2026 12-group format)
TOURNEY-05: Fair-play + FIFA ranking tiebreak features
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class PressureState(str, Enum):
    """Qualification pressure classification for a group-stage team."""
    MUST_WIN = "must-win"
    DRAW_ENOUGH = "draw-enough"
    LIKELY_THROUGH = "likely-through"
    ALREADY_THROUGH = "already-through"
    ALREADY_OUT = "already-out"


class Stage(str, Enum):
    """Tournament stage labels matching WCMatchModel stage strings."""
    GROUP_STAGE = "GROUP_STAGE"
    LAST_16 = "LAST_16"
    QUARTER_FINALS = "QUARTER_FINALS"
    SEMI_FINALS = "SEMI_FINALS"
    THIRD_PLACE = "THIRD_PLACE"
    FINAL = "FINAL"


# Stages at which accumulated yellow cards are wiped (FIFA rule).
# - LAST_16: post-group-stage reset (all group yellows cleared)
# - SEMI_FINALS: post-QF reset (QF-accumulated yellows cleared)
_CARD_RESET_STAGES: frozenset[str] = frozenset({
    Stage.LAST_16.value,
    Stage.SEMI_FINALS.value,
})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TeamStanding:
    """
    Current standing of a team in its group.

    Attributes
    ----------
    team : str
    wins, draws, losses : int
    goals_for, goals_against : int
    yellow_cards, red_cards : int
        Cumulative team cards for fair-play tiebreak.
    matches_remaining : int
        Remaining group matches for this team (0–3).
    """
    team: str
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    matches_remaining: int = 0

    @property
    def points(self) -> int:
        return self.wins * 3 + self.draws

    @property
    def goal_diff(self) -> int:
        return self.goals_for - self.goals_against

    @property
    def games_played(self) -> int:
        return self.wins + self.draws + self.losses

    @property
    def fair_play_score(self) -> int:
        """Negative: more cards → lower score (ascending = better for ranking)."""
        return -(self.yellow_cards + 3 * self.red_cards)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class TournamentState:
    """
    Deterministic tournament-state calculator for WC 2026.

    Parameters
    ----------
    groups_count : int
        Number of groups (12 for WC 2026).
    advance_per_group : int
        Teams advancing directly per group top-2 (default 2).
    best_third_spots : int
        Additional third-place qualifiers (8 for WC 2026).
    """

    def __init__(
        self,
        groups_count: int = 12,
        advance_per_group: int = 2,
        best_third_spots: int = 8,
    ) -> None:
        self._groups_count = groups_count
        self._advance_per_group = advance_per_group
        self._best_third_spots = best_third_spots

    # ------------------------------------------------------------------
    # TOURNEY-01: Qualification pressure state
    # ------------------------------------------------------------------

    def classify_pressure(
        self,
        standings: list[TeamStanding],
        team_name: str,
    ) -> PressureState:
        """
        Classify a team's qualification pressure from current group standings.

        Classification precedence (checked in order):
        1. already-out:    ≥ advance_per_group teams have points > max achievable
        2. already-through: In top-2 AND 3rd-place max < team's current points
        3. draw-enough:    Drawing next match keeps team in guaranteed top-2
        4. likely-through: Currently top-2 but not yet mathematically confirmed
        5. must-win:       Below top-2; a draw won't secure qualification

        Parameters
        ----------
        standings : list[TeamStanding]
            All teams in the same group.
        team_name : str
            Team to classify.

        Returns
        -------
        PressureState
        """
        team = next((s for s in standings if s.team == team_name), None)
        if team is None:
            raise ValueError(f"Team '{team_name}' not found in standings")

        sorted_standings = _sort_group(standings)
        team_rank = next(
            i + 1 for i, s in enumerate(sorted_standings) if s.team == team_name
        )
        mr = team.matches_remaining
        max_team_pts = team.points + mr * 3

        # 1. already-out: enough teams are locked above our maximum
        locked_above = sum(
            1 for t in standings
            if t.team != team_name and t.points > max_team_pts
        )
        if locked_above >= self._advance_per_group:
            return PressureState.ALREADY_OUT

        # 2. already-through: in top-2 and 3rd-place cannot overtake us
        if team_rank <= self._advance_per_group:
            cutoff = self._advance_per_group  # index of 3rd-place team
            if len(sorted_standings) > cutoff:
                third = sorted_standings[cutoff]
                third_max = third.points + third.matches_remaining * 3
                if team.points > third_max:
                    return PressureState.ALREADY_THROUGH
            else:
                return PressureState.ALREADY_THROUGH

        # 3. draw-enough: drawing next match (gain 1 pt) keeps us in top-2
        if mr >= 1:
            draw_pts = team.points + 1
            # Teams currently at-or-below us that could surpass our draw result
            can_surpass = sum(
                1 for t in standings
                if t.team != team_name
                and t.points <= team.points
                and (t.points + t.matches_remaining * 3) > draw_pts
            )
            currently_above = sum(
                1 for t in standings
                if t.team != team_name and t.points > team.points
            )
            if currently_above + can_surpass < self._advance_per_group:
                return PressureState.DRAW_ENOUGH

        # 4. likely-through: currently in top-2 but not guaranteed
        if team_rank <= self._advance_per_group:
            return PressureState.LIKELY_THROUGH

        # 5. must-win: outside top-2 and draw insufficient
        return PressureState.MUST_WIN

    # ------------------------------------------------------------------
    # TOURNEY-02: Rotation risk
    # ------------------------------------------------------------------

    def rotation_risk(
        self,
        standings: list[TeamStanding],
        team_name: str,
    ) -> bool:
        """
        Return True if team is already-through (qualification secured) and
        likely to rotate squad for the remaining group match.

        Parameters
        ----------
        standings : list[TeamStanding]
        team_name : str

        Returns
        -------
        bool
        """
        return self.classify_pressure(standings, team_name) == PressureState.ALREADY_THROUGH

    # ------------------------------------------------------------------
    # TOURNEY-03: Yellow-card suspension risk + card resets
    # ------------------------------------------------------------------

    @staticmethod
    def suspension_risk(player_yellow_cards: int, threshold: int = 1) -> bool:
        """
        Return True if player has accumulated ≥ threshold yellow cards,
        flagging suspension risk if another yellow is received.

        In WC group stage: 2 yellow cards in the same phase = automatic
        1-match ban. A player on 1 yellow is in the 'danger zone'.

        Parameters
        ----------
        player_yellow_cards : int
            Current yellow-card count for the player in this phase.
        threshold : int
            Count at which risk is flagged (default 1 = one caution).

        Returns
        -------
        bool
        """
        return player_yellow_cards >= threshold

    @staticmethod
    def reset_cards(
        player_cards: dict[str, int],
        entering_stage: str,
    ) -> dict[str, int]:
        """
        Reset yellow-card counts when entering a card-wipe stage.

        FIFA WC 2026 resets:
        - Entering LAST_16 (start of knockout): group-stage yellows wiped
        - Entering SEMI_FINALS (post-QF): quarter-final yellows wiped

        Parameters
        ----------
        player_cards : dict[str, int]
            Mapping of player_id → yellow-card count.
        entering_stage : str
            Stage being entered (use Stage enum values).

        Returns
        -------
        dict[str, int]
            New card dictionary (counts reset to 0 at wipe stages).
        """
        if entering_stage in _CARD_RESET_STAGES:
            return {player: 0 for player in player_cards}
        return dict(player_cards)

    # ------------------------------------------------------------------
    # TOURNEY-04: Best-third-place ranking (2026 12-group format)
    # ------------------------------------------------------------------

    def best_third_qualifiers(
        self,
        group_third_standings: list[TeamStanding],
    ) -> list[str]:
        """
        Identify the best_third_spots third-place teams that qualify.

        WC 2026: 12 groups → 12 third-place teams → top 8 advance.

        Ranking criteria (FIFA tiebreak order):
        1. Points (desc)
        2. Goal difference (desc)
        3. Goals scored (desc)
        4. Fair-play score (desc — fewer cards = higher score)

        Parameters
        ----------
        group_third_standings : list[TeamStanding]
            One TeamStanding per group, representing each group's 3rd-place
            finisher after all group matches.

        Returns
        -------
        list[str]
            Team names of qualifiers, ordered best-first.
        """
        ranked = sorted(
            group_third_standings,
            key=lambda t: (t.points, t.goal_diff, t.goals_for, t.fair_play_score),
            reverse=True,
        )
        return [t.team for t in ranked[: self._best_third_spots]]

    # ------------------------------------------------------------------
    # TOURNEY-05: Tiebreak features
    # ------------------------------------------------------------------

    @staticmethod
    def get_tiebreak_features(
        standing: TeamStanding,
        fifa_rank: Optional[int] = None,
    ) -> dict:
        """
        Return fair-play and FIFA ranking tiebreak features.

        Parameters
        ----------
        standing : TeamStanding
        fifa_rank : int, optional
            FIFA ranking (lower = stronger). Falls back to 999.

        Returns
        -------
        dict
            Keys: fair_play_score (int, negative), fifa_rank (int).
        """
        return {
            "fair_play_score": standing.fair_play_score,
            "fifa_rank": fifa_rank if fifa_rank is not None else 999,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sort_group(standings: list[TeamStanding]) -> list[TeamStanding]:
    """Sort group standings by FIFA group-stage tiebreak criteria."""
    return sorted(
        standings,
        key=lambda t: (t.points, t.goal_diff, t.goals_for, t.fair_play_score),
        reverse=True,
    )
