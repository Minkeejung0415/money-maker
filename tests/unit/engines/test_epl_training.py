"""Unit tests for epl_training.py — all use synthetic game dicts, no API calls."""
from alpha.engines.sports.epl_training import (
    EPL_FEATURE_NAMES,
    EPLTeamState,
    build_epl_pregame_rows,
    live_epl_feature_vector,
    calibrated,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _game(date, home, away, hs, aws, gid=None):
    return {
        "date": date,
        "home_team": home,
        "away_team": away,
        "home_score": hs,
        "away_score": aws,
        "game_id": str(gid or f"{home}-{away}-{date}"),
    }


# ---------------------------------------------------------------------------
# Feature name schema (6 tests)
# ---------------------------------------------------------------------------

def test_feature_names_count():
    assert len(EPL_FEATURE_NAMES) == 14


def test_feature_names_contains_xg():
    assert "home_xg_for" in EPL_FEATURE_NAMES
    assert "away_xg_against" in EPL_FEATURE_NAMES


def test_feature_names_contains_form():
    assert "home_form_points" in EPL_FEATURE_NAMES
    assert "away_form_goal_diff" in EPL_FEATURE_NAMES


def test_feature_names_contains_h2h():
    assert "h2h_home_win_rate" in EPL_FEATURE_NAMES


def test_feature_names_contains_rest():
    assert "home_rest_days" in EPL_FEATURE_NAMES
    assert "away_rest_days" in EPL_FEATURE_NAMES


def test_feature_names_contains_set_pieces():
    assert "home_corners_pg" in EPL_FEATURE_NAMES


# ---------------------------------------------------------------------------
# Row builder tests (8 tests)
# ---------------------------------------------------------------------------

def test_build_rows_single_game():
    games = [_game("2025-08-10", "Arsenal", "Chelsea", 2, 1)]
    rows, state = build_epl_pregame_rows(games)
    assert len(rows) == 1
    assert rows[0]["home_win"] == 1


def test_build_rows_draw_skipped():
    games = [_game("2025-08-10", "Arsenal", "Chelsea", 1, 1)]
    rows, state = build_epl_pregame_rows(games)
    assert len(rows) == 0


def test_build_rows_leakage_safe():
    """Game2 features reflect game1 Elo update; game1 features use initial state."""
    games = [
        _game("2025-08-10", "Arsenal", "Chelsea", 3, 0, gid=1),  # Arsenal wins big
        _game("2025-08-17", "Arsenal", "Chelsea", 1, 2, gid=2),
    ]
    rows, state = build_epl_pregame_rows(games)
    assert len(rows) == 2
    # Game1 features: initial Elo = 1500 vs 1500 → elo_diff would be 0 if we tracked it
    # But we check xg_for_pg defaults (no xg data provided) — should be 1.5 for initial
    # The key leakage check: form_points in row 1 should be 0 (no prior games)
    assert rows[0]["home_form_points"] == 0.0
    # After game1, Arsenal won → form_buffer has an entry → row2 home_form_points > 0
    assert rows[1]["home_form_points"] > 0.0


def test_build_rows_state_accumulates():
    games = [
        _game("2025-08-10", "Arsenal", "Chelsea", 2, 1, gid=1),
        _game("2025-08-17", "Arsenal", "Chelsea", 3, 0, gid=2),
        _game("2025-08-24", "Arsenal", "Chelsea", 1, 0, gid=3),
    ]
    rows, state = build_epl_pregame_rows(games)
    assert state["Arsenal"]["games"] == 3


def test_build_rows_returns_state_map():
    games = [_game("2025-08-10", "Arsenal", "Chelsea", 2, 1)]
    result = build_epl_pregame_rows(games)
    assert isinstance(result, tuple)
    rows, state_map = result
    assert isinstance(rows, list)
    assert isinstance(state_map, dict)


def test_build_rows_form_points_from_history():
    """After 3 wins for home team, row 4's home_form_points > 0 (not zero)."""
    games = [
        _game("2025-08-01", "Arsenal", "Chelsea", 2, 0, gid=1),
        _game("2025-08-08", "Arsenal", "Spurs", 3, 1, gid=2),
        _game("2025-08-15", "Arsenal", "Liverpool", 1, 0, gid=3),
        _game("2025-08-22", "Arsenal", "Man City", 2, 1, gid=4),
    ]
    rows, state = build_epl_pregame_rows(games)
    assert len(rows) == 4
    # Row 4 (index 3): Arsenal has 3 prior wins on record → form_points should be 9
    assert rows[3]["home_form_points"] > 0.0


def test_build_rows_h2h_from_history():
    """After home team wins first meeting, second H2H row has h2h_home_win_rate == 1.0."""
    games = [
        _game("2025-08-01", "Arsenal", "Chelsea", 2, 0, gid=1),  # Arsenal wins H2H
        _game("2025-08-22", "Arsenal", "Chelsea", 1, 0, gid=2),  # Second meeting
    ]
    rows, state = build_epl_pregame_rows(games)
    assert len(rows) == 2
    # Row 1 (index 0): no H2H history yet → default 0.5
    assert rows[0]["h2h_home_win_rate"] == 0.5
    # Row 2 (index 1): Arsenal won the first meeting as home → rate == 1.0
    assert rows[1]["h2h_home_win_rate"] == 1.0


def test_build_rows_draw_updates_form_not_row():
    """A 1-1 draw updates form_buffer but does NOT add to rows (binary classifier skips draws)."""
    games = [
        _game("2025-08-01", "Arsenal", "Chelsea", 1, 1, gid=1),  # Draw → no row
        _game("2025-08-08", "Arsenal", "Spurs", 2, 0, gid=2),    # Arsenal wins → row
    ]
    rows, state = build_epl_pregame_rows(games)
    assert len(rows) == 1  # Only the Spurs win produces a row
    # The form buffer should have been updated for the draw (1 point for Arsenal)
    # so row[0] (which is the Spurs game) should reflect the draw in form_points
    assert rows[0]["home_form_points"] == 1.0  # 1 point from the draw


# ---------------------------------------------------------------------------
# Live feature vector tests (3 tests)
# ---------------------------------------------------------------------------

def test_live_feature_vector_keys():
    fv = live_epl_feature_vector("Arsenal", "Chelsea", "2025-12-01", {})
    assert set(fv.keys()) == set(EPL_FEATURE_NAMES)


def test_live_feature_vector_empty_state():
    """With empty state_map, returns floats (no KeyError, safe defaults)."""
    fv = live_epl_feature_vector("Arsenal", "Chelsea", "2025-12-01", {})
    for key in EPL_FEATURE_NAMES:
        assert isinstance(fv[key], (int, float)), f"{key} is not numeric"


def test_live_feature_vector_xg_from_state():
    """When state_map has xg data, it is reflected in output."""
    state_map = {
        "Arsenal": {
            "games": 10,
            "wins": 6,
            "xg_for_total": 20.0,
            "xg_against_total": 8.0,
            "elo": 1550.0,
            "last_date": "2025-11-25",
            "form_buffer": [{"points": 3, "goal_diff": 1.0}] * 5,
        }
    }
    fv = live_epl_feature_vector("Arsenal", "Chelsea", "2025-12-01", state_map)
    # Arsenal has xg_for_total=20 over 10 games → xg_for_pg = 2.0
    assert abs(fv["home_xg_for"] - 2.0) < 0.01
