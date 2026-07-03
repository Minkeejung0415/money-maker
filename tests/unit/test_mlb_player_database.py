from __future__ import annotations

import pytest

from alpha.data.ingestion.mlb_player_database import (
    append_rows,
    build_player_stat_snapshot,
    derive_batter_stats,
    derive_pitcher_stats,
    filter_rows_through,
    normalize_batter_rows,
    normalize_bullpen_rows,
    normalize_absence_rows,
    normalize_lineup_rows,
    normalize_pitcher_rows,
    parse_innings,
    read_rows_csv,
    update_database_snapshot,
    write_json,
    write_rows_parquet_or_csv,
    write_rows_csv,
)


def test_parse_innings_handles_baseball_outs():
    assert parse_innings("4.1") == pytest.approx(4 + 1 / 3)
    assert parse_innings("4.2") == pytest.approx(4 + 2 / 3)


def test_normalize_batter_rows_keeps_supported_advanced_inputs_only():
    rows = normalize_batter_rows(
        [{
            "player": "Batter One",
            "team": "NYY",
            "date": "2026-06-28",
            "war": 5.0,
            "xwoba": 0.410,
            "wrc_plus": 170,
            "platoon_wrc_plus": 190,
            "lineup_spot": 2,
            "h": 2,
            "ab": 4,
        }],
        source="csv",
    )

    assert rows[0]["player_name"] == "Batter One"
    assert rows[0]["war"] == pytest.approx(5.0)
    assert rows[0]["xwoba"] == pytest.approx(0.410)
    assert rows[0]["wrc_plus"] == pytest.approx(170)
    assert "hits" not in rows[0]
    assert "at_bats" not in rows[0]
    assert rows[0]["source"] == "csv"


def test_normalize_pitcher_rows_keeps_supported_advanced_inputs_only():
    pitchers = normalize_pitcher_rows(
        [{
            "player": "Pitcher One",
            "team": "BOS",
            "date": "2026-06-28",
            "role": "SP",
            "war": 4.0,
            "xera": 3.10,
            "fip": 3.25,
            "k_bb_pct": 0.22,
            "rest_days": 5,
            "pitch_count_workload": 88,
            "er": 3,
            "ip": "4.0",
        }],
        source="csv",
    )

    assert pitchers[0]["xera"] == pytest.approx(3.10)
    assert pitchers[0]["fip"] == pytest.approx(3.25)
    assert pitchers[0]["k_bb_pct"] == pytest.approx(0.22)
    assert "earned_runs" not in pitchers[0]
    assert "innings_pitched" not in pitchers[0]

    bullpen = normalize_bullpen_rows(
        [{"team": "BOS", "date": "2026-06-28", "xera": 3.60, "fip": 3.80, "k_bb_pct": 0.18, "pit": 47, "er": 1}],
        source="csv",
    )
    assert bullpen[0]["xera"] == pytest.approx(3.60)
    assert bullpen[0]["pitch_count_workload"] == pytest.approx(47)
    assert "earned_runs" not in bullpen[0]


def test_normalize_lineup_and_absence_rows_preserve_game_links():
    lineup = normalize_lineup_rows([
        {"game_id": "g1", "player": "Batter One", "team": "NYY", "date": "2026-06-28", "order": 1, "confirmed": "true", "bats": "L"},
    ])
    absences = normalize_absence_rows([
        {"game_id": "g1", "player": "Batter Two", "team": "NYY", "date": "2026-06-28", "absence_value": 0.25, "reason": "injury"},
    ])

    assert lineup[0]["game_id"] == "g1"
    assert lineup[0]["confirmed"] is True
    assert absences[0]["absence_value"] == pytest.approx(0.25)
    assert absences[0]["absence_value_source"] == "explicit"


def test_absence_value_can_be_derived_from_war():
    absences = normalize_absence_rows([
        {"game_id": "g1", "player": "Elite Bat", "team": "NYY", "date": "2026-06-28", "war": 6.0},
        {"game_id": "g1", "player": "Two Way Star", "team": "LAD", "date": "2026-06-28", "batting_war": 5.0, "pitching_war": 4.0},
        {"game_id": "g1", "player": "MVP Cap", "team": "LAD", "date": "2026-06-28", "war": 12.0},
    ])

    assert absences[0]["absence_value"] == pytest.approx(0.30)
    assert absences[0]["today_player_value"] == pytest.approx(6.0)
    assert absences[0]["absence_value_source"] == "today_player_value"
    assert absences[1]["war"] == pytest.approx(9.0)
    assert absences[1]["absence_value"] == pytest.approx(0.45)
    assert absences[2]["absence_value"] == pytest.approx(0.50)


def test_absence_today_player_value_uses_context_components():
    absences = normalize_absence_rows([
        {
            "game_id": "g1",
            "player": "MVP Bat",
            "team": "LAD",
            "date": "2026-06-28",
            "war": 8.0,
            "xwoba": 0.420,
            "wrc_plus": 180,
            "platoon_wrc_plus": 210,
            "lineup_spot": 2,
            "team_matchup_adjustment": 0.20,
        },
        {
            "game_id": "g1",
            "player": "Ace",
            "team": "LAD",
            "date": "2026-06-28",
            "role": "SP",
            "war": 5.0,
            "xera": 2.80,
            "fip": 3.00,
            "k_bb_pct": 0.25,
            "rest_days": 5,
            "projected_innings": 6.5,
        },
    ])

    assert absences[0]["today_player_value"] > absences[0]["war"]
    assert absences[0]["absence_value"] == pytest.approx(0.50)
    assert absences[1]["today_player_value"] > absences[1]["war"]
    assert absences[1]["absence_value"] > 0.25


def test_absence_rows_reject_surface_stats():
    with pytest.raises(ValueError, match="unsupported absence stat"):
        normalize_absence_rows([
            {"game_id": "g1", "player": "Surface Stat Bat", "team": "NYY", "date": "2026-06-28", "war": 4.0, "BA": 0.320},
        ])


def test_derive_batter_stats_formula_outputs():
    rows = normalize_batter_rows([
        {"player": "Batter One", "team": "NYY", "date": "2026-06-27", "war": 5.0, "xwoba": 0.420, "wrc_plus": 180, "lineup_spot": 2},
    ])

    stats = derive_batter_stats(rows)["Batter One"]

    assert stats["war"] == pytest.approx(5.0)
    assert stats["xwoba"] == pytest.approx(0.420)
    assert stats["wrc_plus"] == pytest.approx(180)
    assert stats["batting_value"] == pytest.approx(stats["today_player_value"])
    assert stats["batting_value"] > stats["war"]


def test_derive_pitcher_stats_changes_after_append():
    first = normalize_pitcher_rows([
        {"player": "Pitcher One", "team": "BOS", "date": "2026-06-27", "xera": 2.80, "fip": 3.00, "k_bb_pct": 0.25, "pitch_count_workload": 90},
    ])
    second = normalize_pitcher_rows([
        {"player": "Pitcher One", "team": "BOS", "date": "2026-06-28", "xera": 4.20, "fip": 4.10, "k_bb_pct": 0.15, "pitch_count_workload": 104},
    ])

    before = derive_pitcher_stats(first)["Pitcher One"]
    after = derive_pitcher_stats(append_rows(first, second))["Pitcher One"]

    assert before["starter_quality"] > after["starter_quality"]
    assert after["xera"] == pytest.approx(3.5)
    assert after["fip"] == pytest.approx(3.55)
    assert after["pitch_count_workload"] == pytest.approx(104)


def test_filter_rows_through_uses_target_and_window():
    rows = normalize_batter_rows([
        {"player": "Batter One", "date": "2026-06-20", "war": 1.0},
        {"player": "Batter One", "date": "2026-06-26", "war": 2.0},
        {"player": "Batter One", "date": "2026-06-29", "war": 3.0},
    ])

    filtered = filter_rows_through(rows, "2026-06-28", window_days=7)

    assert [row["game_date"] for row in filtered] == ["2026-06-26"]


def test_build_player_stat_snapshot_has_season_and_rolling():
    batters = normalize_batter_rows([
        {"player": "Batter One", "date": "2026-06-26", "war": 3.0, "xwoba": 0.360, "wrc_plus": 130},
    ])
    pitchers = normalize_pitcher_rows([
        {"player": "Pitcher One", "date": "2026-06-26", "xera": 3.20, "fip": 3.40, "k_bb_pct": 0.20},
    ])

    snapshot = build_player_stat_snapshot(
        batter_rows=batters,
        pitcher_rows=pitchers,
        target_date="2026-06-28",
        windows=(7,),
    )

    assert "Batter One" in snapshot["season"]["batters"]
    assert "Pitcher One" in snapshot["rolling"]["7"]["pitchers"]


def test_missing_components_do_not_crash():
    assert derive_batter_stats(normalize_batter_rows([{"player": "Batter One"}]))["Batter One"]["batting_value"] == 0.0
    assert derive_pitcher_stats(normalize_pitcher_rows([{"player": "Pitcher One"}]))["Pitcher One"]["starter_quality"] == 0.0


def test_write_rows_parquet_or_csv_falls_back_to_file(tmp_path):
    output = write_rows_parquet_or_csv(tmp_path / "rows.parquet", [{"a": 1}])

    assert output.exists()
    assert output.suffix in {".parquet", ".csv"}


def test_csv_and_json_helpers_round_trip(tmp_path):
    csv_path = write_rows_csv(tmp_path / "rows.csv", [{"a": 1, "b": "two"}])
    json_path = write_json(tmp_path / "payload.json", {"ok": True})

    assert read_rows_csv(csv_path) == [{"a": "1", "b": "two"}]
    assert json_path.exists()


def test_update_database_snapshot_is_idempotent():
    batters = normalize_batter_rows([
        {"player": "Batter One", "team": "NYY", "date": "2026-06-28", "war": 1.0},
    ], source="fixture")

    first = update_database_snapshot(
        {},
        batters=batters,
        source="fixture",
        import_date="2026-06-28",
    )
    second = update_database_snapshot(
        first,
        batters=batters,
        source="fixture",
        import_date="2026-06-28",
    )

    assert len(second["components"]["batters"]) == 1
    assert second["sources"]["fixture"]["last_import_date"] == "2026-06-28"
