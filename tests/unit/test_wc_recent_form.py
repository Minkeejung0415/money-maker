"""Tests for recent international form ingestion from EloRatings TSV."""
from __future__ import annotations

from datetime import date

import pytest

from alpha.data.ingestion.wc_recent_form import parse_recent_form_tsv


def _row(day, home, away, home_goals, away_goals, home_elo=1800, away_elo=1800):
    return "\t".join([
        "2026", "06", f"{day:02d}", home, away,
        str(home_goals), str(away_goals), "F", "", "0",
        str(home_elo), str(away_elo), "0", "0", "1", "1",
    ])


def test_parse_recent_form_handles_team_on_both_sides_and_cutoff():
    rows = [
        _row(1, "ES", "FR", 2, 0, 2000, 1950),
        _row(2, "DE", "ES", 1, 3, 1900, 2010),
        _row(3, "ES", "IT", 1, 1, 2020, 1920),
        _row(4, "PT", "ES", 0, 2, 1940, 2030),
        _row(5, "ES", "NL", 4, 1, 2040, 1960),
        _row(10, "ES", "SA", 9, 0, 2100, 1600),
    ]
    stats = parse_recent_form_tsv("\n".join(rows), as_of=date(2026, 6, 10), n=10)
    assert stats is not None
    assert stats["games"] == 5
    assert stats["latest_match"] == "2026-06-05"
    assert stats["elo_rating"] == 2040
    assert stats["avg_goals"] > stats["defense_score"]


def test_parse_recent_form_uses_only_most_recent_n_with_decay():
    rows = [_row(day, "ES", "X", 0 if day < 8 else 3, 1) for day in range(1, 11)]
    stats = parse_recent_form_tsv("\n".join(rows), as_of=date(2026, 6, 20), n=3)
    assert stats is not None
    assert stats["games"] == 3
    assert stats["avg_goals"] == pytest.approx(3.0)


def test_parse_recent_form_rejects_too_little_history():
    rows = [_row(day, "ES", "X", 1, 0) for day in range(1, 5)]
    assert parse_recent_form_tsv("\n".join(rows), as_of=date(2026, 6, 20)) is None


def test_opponent_strength_adjustment_discounts_goals_against_weak_team():
    strong_opponents = "\n".join(
        _row(day, "ES", "X", 2, 0, 2000, 2000) for day in range(1, 6)
    )
    weak_opponents = "\n".join(
        _row(day, "ES", "X", 2, 0, 2000, 1200) for day in range(1, 6)
    )
    strong = parse_recent_form_tsv(strong_opponents, as_of=date(2026, 6, 20))
    weak = parse_recent_form_tsv(weak_opponents, as_of=date(2026, 6, 20))
    assert strong is not None and weak is not None
    assert strong["avg_goals"] > weak["avg_goals"]
