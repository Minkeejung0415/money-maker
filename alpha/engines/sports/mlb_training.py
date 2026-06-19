"""Leakage-safe MLB pregame features shared by training and live inference."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime

FEATURE_NAMES = (
    "elo_diff", "home_win_pct", "away_win_pct", "home_run_diff",
    "away_run_diff", "home_rest_days", "away_rest_days", "home_indicator",
)

@dataclass
class TeamState:
    games: int = 0
    wins: int = 0
    runs_for: float = 0.0
    runs_against: float = 0.0
    elo: float = 1500.0
    last_date: str = ""

    @property
    def win_pct(self) -> float:
        return self.wins / self.games if self.games else 0.5

    @property
    def run_diff(self) -> float:
        return (self.runs_for - self.runs_against) / self.games if self.games else 0.0


def _days_rest(last_date: str, game_date: str) -> float:
    if not last_date:
        return 3.0
    return float(max(0, min(7, (date.fromisoformat(game_date) - date.fromisoformat(last_date)).days - 1)))


def feature_vector(home: TeamState, away: TeamState, game_date: str) -> dict[str, float]:
    return {
        "elo_diff": home.elo - away.elo,
        "home_win_pct": home.win_pct,
        "away_win_pct": away.win_pct,
        "home_run_diff": home.run_diff,
        "away_run_diff": away.run_diff,
        "home_rest_days": _days_rest(home.last_date, game_date),
        "away_rest_days": _days_rest(away.last_date, game_date),
        "home_indicator": 1.0,
    }


def build_pregame_rows(games: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """Return chronological rows and terminal team state; target games never update their own features."""
    states: dict[str, TeamState] = {}
    rows: list[dict] = []
    ordered = sorted(games, key=lambda g: (str(g["date"]), str(g.get("game_id", ""))))
    for game in ordered:
        home, away = str(game["home_team"]), str(game["away_team"])
        game_date = str(game["date"])[:10]
        hs, aws = game.get("home_score"), game.get("away_score")
        if hs is None or aws is None or float(hs) == float(aws):
            continue
        h = states.setdefault(home, TeamState())
        a = states.setdefault(away, TeamState())
        features = feature_vector(h, a, game_date)
        rows.append({"date": game_date, "home_team": home, "away_team": away,
                     **features, "home_win": int(float(hs) > float(aws))})
        expected = 1.0 / (1.0 + 10.0 ** ((a.elo - h.elo) / 400.0))
        outcome = float(hs) > float(aws)
        change = 20.0 * (float(outcome) - expected)
        h.elo += change; a.elo -= change
        h.games += 1; a.games += 1
        h.wins += int(outcome); a.wins += int(not outcome)
        h.runs_for += float(hs); h.runs_against += float(aws)
        a.runs_for += float(aws); a.runs_against += float(hs)
        h.last_date = game_date; a.last_date = game_date
    return rows, {team: asdict(state) for team, state in states.items()}


def live_feature_vector(home_team: str, away_team: str, game_date: str,
                        state_map: dict[str, dict]) -> dict[str, float]:
    home = TeamState(**state_map.get(home_team, {}))
    away = TeamState(**state_map.get(away_team, {}))
    return feature_vector(home, away, game_date)
