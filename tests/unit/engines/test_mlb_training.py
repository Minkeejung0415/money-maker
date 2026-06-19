from alpha.engines.sports.mlb_training import FEATURE_NAMES, build_pregame_rows, live_feature_vector


def test_target_game_does_not_leak_into_features():
    games=[{"date":"2025-04-01","game_id":1,"home_team":"A","away_team":"B","home_score":10,"away_score":0},
           {"date":"2025-04-02","game_id":2,"home_team":"A","away_team":"B","home_score":0,"away_score":10}]
    rows,state=build_pregame_rows(games)
    assert rows[0]["home_win_pct"] == 0.5
    assert rows[0]["home_run_diff"] == 0.0
    assert rows[1]["home_win_pct"] == 1.0
    assert rows[1]["home_run_diff"] == 10.0


def test_input_order_is_irrelevant_and_schema_is_stable():
    games=[{"date":"2025-04-02","game_id":2,"home_team":"A","away_team":"B","home_score":2,"away_score":3},
           {"date":"2025-04-01","game_id":1,"home_team":"A","away_team":"B","home_score":4,"away_score":1}]
    rows,state=build_pregame_rows(games)
    assert [r["date"] for r in rows] == ["2025-04-01","2025-04-02"]
    live=live_feature_vector("A","B","2025-04-03",state)
    assert tuple(live) == FEATURE_NAMES
