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
    normalize_pitcher_rows,
    parse_innings,
    write_rows_parquet_or_csv,
)


def test_parse_innings_handles_baseball_outs():
    assert parse_innings("4.1") == pytest.approx(4 + 1 / 3)
    assert parse_innings("4.2") == pytest.approx(4 + 2 / 3)


def test_normalize_batter_rows_preserves_raw_components():
    rows = normalize_batter_rows(
        [{"player": "Batter One", "team": "NYY", "date": "2026-06-28", "h": 2, "ab": 4, "bb": 1, "tb": 5, "hr": 1, "rbi": 3, "pa": 5}],
        source="csv",
    )

    assert rows[0]["player_name"] == "Batter One"
    assert rows[0]["hits"] == pytest.approx(2.0)
    assert rows[0]["total_bases"] == pytest.approx(5.0)
    assert rows[0]["source"] == "csv"


def test_normalize_pitcher_and_bullpen_rows_preserve_components():
    pitchers = normalize_pitcher_rows(
        [{"player": "Pitcher One", "team": "BOS", "date": "2026-06-28", "er": 3, "ip": "4.0", "h": 5, "bb": 2, "so": 6, "pit": 88}],
        source="csv",
    )
    bullpen = normalize_bullpen_rows(
        [{"team": "BOS", "date": "2026-06-28", "er": 1, "ip": "3.2", "pit": 47}],
        source="csv",
    )

    assert pitchers[0]["earned_runs"] == pytest.approx(3.0)
    assert pitchers[0]["innings_pitched"] == pytest.approx(4.0)
    assert bullpen[0]["team"] == "BOS"
    assert bullpen[0]["innings_pitched"] == pytest.approx(3 + 2 / 3)


def test_derive_batter_stats_formula_outputs():
    rows = normalize_batter_rows([
        {"player": "Batter One", "team": "NYY", "date": "2026-06-27", "h": 2, "ab": 4, "bb": 1, "tb": 5, "hr": 1, "rbi": 2, "pa": 5},
    ])

    stats = derive_batter_stats(rows)["Batter One"]

    assert stats["avg"] == pytest.approx(0.5)
    assert stats["obp"] == pytest.approx(3 / 5)
    assert stats["slg"] == pytest.approx(1.25)
    assert stats["hr_rate"] == pytest.approx(0.2)
    assert stats["batting_value"] == pytest.approx(stats["ops"])


def test_derive_pitcher_stats_changes_after_append():
    first = normalize_pitcher_rows([
        {"player": "Pitcher One", "team": "BOS", "date": "2026-06-27", "er": 1, "ip": "6.0", "h": 4, "bb": 1, "so": 7, "hr": 0},
    ])
    second = normalize_pitcher_rows([
        {"player": "Pitcher One", "team": "BOS", "date": "2026-06-28", "er": 3, "ip": "4.0", "h": 5, "bb": 2, "so": 3, "hr": 1},
    ])

    before = derive_pitcher_stats(first)["Pitcher One"]
    after = derive_pitcher_stats(append_rows(first, second))["Pitcher One"]

    assert before["era"] == pytest.approx(1.5)
    assert after["era"] == pytest.approx(3.6)
    assert after["whip"] == pytest.approx(12 / 10)
    assert after["k_per9"] == pytest.approx(9.0)


def test_filter_rows_through_uses_target_and_window():
    rows = normalize_batter_rows([
        {"player": "Batter One", "date": "2026-06-20", "h": 1, "ab": 4},
        {"player": "Batter One", "date": "2026-06-26", "h": 2, "ab": 4},
        {"player": "Batter One", "date": "2026-06-29", "h": 4, "ab": 4},
    ])

    filtered = filter_rows_through(rows, "2026-06-28", window_days=7)

    assert [row["game_date"] for row in filtered] == ["2026-06-26"]


def test_build_player_stat_snapshot_has_season_and_rolling():
    batters = normalize_batter_rows([
        {"player": "Batter One", "date": "2026-06-26", "h": 2, "ab": 4, "tb": 3},
    ])
    pitchers = normalize_pitcher_rows([
        {"player": "Pitcher One", "date": "2026-06-26", "er": 2, "ip": "6.0", "h": 6, "bb": 1, "so": 5},
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
    assert derive_batter_stats(normalize_batter_rows([{"player": "Batter One"}]))["Batter One"]["avg"] == 0.0
    assert derive_pitcher_stats(normalize_pitcher_rows([{"player": "Pitcher One"}]))["Pitcher One"]["era"] == 0.0


def test_write_rows_parquet_or_csv_falls_back_to_file(tmp_path):
    output = write_rows_parquet_or_csv(tmp_path / "rows.parquet", [{"a": 1}])

    assert output.exists()
    assert output.suffix in {".parquet", ".csv"}
