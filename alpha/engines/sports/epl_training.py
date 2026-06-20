"""Leakage-safe EPL pregame features shared by training and live inference."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date

FORM_WINDOW: int = 5

EPL_FEATURE_NAMES = (
    "home_xg_for", "home_xg_against", "away_xg_for", "away_xg_against",
    "home_form_points", "home_form_goal_diff", "away_form_points", "away_form_goal_diff",
    "h2h_home_win_rate", "home_rest_days", "away_rest_days",
    "home_corners_pg", "away_corners_pg", "home_aerial_pct",
)


@dataclass
class EPLTeamState:
    games: int = 0
    wins: int = 0
    xg_for_total: float = 0.0
    xg_against_total: float = 0.0
    elo: float = 1500.0
    last_date: str = ""
    form_buffer: list = field(default_factory=list)
    # Each entry: {"points": int (W=3, D=1, L=0), "goal_diff": float}
    # Kept to last FORM_WINDOW*2 entries to bound memory; sliced to last 5 when computing.

    @property
    def xg_for_pg(self) -> float:
        return self.xg_for_total / self.games if self.games else 1.5

    @property
    def xg_against_pg(self) -> float:
        return self.xg_against_total / self.games if self.games else 1.5

    def form_points_n(self, n: int = FORM_WINDOW) -> float:
        return float(sum(e["points"] for e in self.form_buffer[-n:]))

    def form_goal_diff_n(self, n: int = FORM_WINDOW) -> float:
        return float(sum(e["goal_diff"] for e in self.form_buffer[-n:]))


def _days_rest(last_date: str, game_date: str) -> float:
    """Mirror mlb_training._days_rest: max(0, min(7, delta-1)), default 3.0 when empty."""
    if not last_date:
        return 3.0
    return float(max(0, min(7, (date.fromisoformat(game_date) - date.fromisoformat(last_date)).days - 1)))


def _feature_vector(
    home: EPLTeamState,
    away: EPLTeamState,
    game_date: str,
    h2h_home_win_rate: float,
    fbref_home: dict,
    fbref_away: dict,
) -> dict[str, float]:
    """Return dict with all 14 EPL_FEATURE_NAMES keys."""
    return {
        "home_xg_for": home.xg_for_pg,
        "home_xg_against": home.xg_against_pg,
        "away_xg_for": away.xg_for_pg,
        "away_xg_against": away.xg_against_pg,
        "home_form_points": home.form_points_n(FORM_WINDOW),
        "home_form_goal_diff": home.form_goal_diff_n(FORM_WINDOW),
        "away_form_points": away.form_points_n(FORM_WINDOW),
        "away_form_goal_diff": away.form_goal_diff_n(FORM_WINDOW),
        "h2h_home_win_rate": h2h_home_win_rate,
        "home_rest_days": _days_rest(home.last_date, game_date),
        "away_rest_days": _days_rest(away.last_date, game_date),
        "home_corners_pg": float(fbref_home.get("corners_per_game", 0.0)),
        "away_corners_pg": float(fbref_away.get("corners_per_game", 0.0)),
        "home_aerial_pct": float(fbref_home.get("aerial_won_pct", 0.0)),
    }


def build_epl_pregame_rows(
    games: list[dict],
    xg_map: dict[str, dict] | None = None,
    fbref_map: dict[str, dict] | None = None,
) -> tuple[list[dict], dict[str, dict]]:
    """Return leakage-safe chronological rows and terminal team state.

    xg_map: optional {team_name: {"xG_for": float, "xG_against": float}} from soccer_stats.py
    fbref_map: optional {team_name: {"corners_per_game": float, "aerial_won_pct": float}}

    Draws update form and H2H state but do NOT append rows (binary classifier skips draws).
    """
    states: dict[str, EPLTeamState] = {}
    h2h_log: dict[str, list] = {}
    rows: list[dict] = []

    ordered = sorted(games, key=lambda g: (str(g["date"]), str(g.get("game_id", ""))))

    for game in ordered:
        home = str(game["home_team"])
        away = str(game["away_team"])
        game_date = str(game["date"])[:10]
        hs = game.get("home_score")
        aws = game.get("away_score")

        if hs is None or aws is None:
            continue

        hs_f = float(hs)
        aws_f = float(aws)

        h = states.setdefault(home, EPLTeamState())
        a = states.setdefault(away, EPLTeamState())

        # --- Compute H2H rate BEFORE updating h2h_log ---
        h2h_key = f"{home}|{away}"
        rev_key = f"{away}|{home}"
        both_directions = h2h_log.get(h2h_key, []) + h2h_log.get(rev_key, [])
        recent_h2h = sorted(both_directions, key=lambda r: r["date"])[-FORM_WINDOW:]
        if recent_h2h:
            home_side_wins = sum(
                1 for r in recent_h2h
                if r["home"] == home and r["winner"] == "home"
            )
            h2h_home_win_rate = home_side_wins / len(recent_h2h)
        else:
            h2h_home_win_rate = 0.5

        # --- fbref lookup ---
        fbref_home = (fbref_map or {}).get(home, {})
        fbref_away = (fbref_map or {}).get(away, {})

        # --- Extract PREGAME features (leakage-safe: before this game's result) ---
        features = _feature_vector(h, a, game_date, h2h_home_win_rate, fbref_home, fbref_away)

        home_win = hs_f > aws_f
        draw = hs_f == aws_f

        # --- Append row only for non-draws (binary classifier) ---
        if not draw:
            rows.append({
                "date": game_date,
                "home_team": home,
                "away_team": away,
                **features,
                "home_win": int(home_win),
            })

        # --- Update state AFTER extracting features ---
        gd = hs_f - aws_f
        points_h = 3 if home_win else (1 if draw else 0)
        points_a = 3 if (not home_win and not draw) else (1 if draw else 0)

        h.form_buffer.append({"points": points_h, "goal_diff": gd})
        a.form_buffer.append({"points": points_a, "goal_diff": -gd})
        h.form_buffer = h.form_buffer[-(FORM_WINDOW * 2):]
        a.form_buffer = a.form_buffer[-(FORM_WINDOW * 2):]

        # Elo update (K=20)
        expected = 1.0 / (1.0 + 10.0 ** ((a.elo - h.elo) / 400.0))
        change = 20.0 * (float(home_win) - expected)
        h.elo += change
        a.elo -= change

        # xG accumulation from game dict if present
        home_xg = game.get("home_xg")
        away_xg = game.get("away_xg")
        if home_xg is not None:
            h.xg_for_total += float(home_xg)
            a.xg_against_total += float(home_xg)
        if away_xg is not None:
            a.xg_for_total += float(away_xg)
            h.xg_against_total += float(away_xg)

        h.games += 1
        a.games += 1
        if home_win:
            h.wins += 1
        if not home_win and not draw:
            a.wins += 1
        h.last_date = game_date
        a.last_date = game_date

        # Update H2H log
        h2h_log.setdefault(h2h_key, []).append({
            "date": game_date,
            "home": home,
            "away": away,
            "winner": "home" if home_win else ("draw" if draw else "away"),
        })

    return rows, {team: asdict(state) for team, state in states.items()}


def live_epl_feature_vector(
    home_team: str,
    away_team: str,
    game_date: str,
    state_map: dict[str, dict],
    home_team_id: int = 0,
    away_team_id: int = 0,
    fetch_live: bool = False,
) -> dict[str, float]:
    """Return feature vector for a live game using pre-computed state_map.

    If fetch_live=True and team IDs are provided, attempts to call live ingestion
    functions (fetch_team_form, fetch_h2h, fetch_days_rest, get_fbref_set_pieces).
    All live fetches are wrapped in try/except and fall back silently.

    For training and offline use, set fetch_live=False (default) — uses state_map only.
    """
    # Reconstruct EPLTeamState from state_map (handles missing keys with defaults)
    home_data = state_map.get(home_team, {})
    away_data = state_map.get(away_team, {})

    # EPLTeamState has form_buffer as a list field — handle gracefully
    home_state = EPLTeamState(**{k: v for k, v in home_data.items() if k in EPLTeamState.__dataclass_fields__})
    away_state = EPLTeamState(**{k: v for k, v in away_data.items() if k in EPLTeamState.__dataclass_fields__})

    h2h_home_win_rate = 0.5
    fbref_home: dict = {}
    fbref_away: dict = {}

    if fetch_live and home_team_id > 0:
        try:
            from alpha.data.ingestion.soccer_form import fetch_team_form, fetch_h2h, fetch_days_rest
            from alpha.data.ingestion.soccer_fbref import get_fbref_set_pieces

            h2h_data = fetch_h2h(home_team_id, away_team_id)
            h2h_home_win_rate = float(h2h_data.get("h2h_home_win_rate", 0.5))

            fbref_data = get_fbref_set_pieces()
            fbref_home = fbref_data.get(home_team, {})
            fbref_away = fbref_data.get(away_team, {})
        except Exception:
            pass

    return _feature_vector(home_state, away_state, game_date, h2h_home_win_rate, fbref_home, fbref_away)


def calibrated(calibrator, raw_probs):
    """Apply Platt calibrator to raw probabilities. Shared by train script and SoccerModel."""
    import numpy as np
    p = np.clip(raw_probs, 1e-6, 1 - 1e-6)
    return calibrator.predict_proba(np.log(p / (1 - p)).reshape(-1, 1))[:, 1]
