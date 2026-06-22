"""Tests for World Cup tactical profile ingestion."""
from __future__ import annotations

from datetime import date

from alpha.data.ingestion.wc_tactics import (
    WCTacticsClient,
    aggregate_tactical_profile,
    parse_tactical_match,
)


def _entry(team, possession, passes, shots, corners, clearances=10):
    values = {
        "possessionPct": possession,
        "totalPasses": passes,
        "passPct": 0.85,
        "totalShots": shots,
        "shotsOnTarget": max(1, shots // 3),
        "wonCorners": corners,
        "totalLongBalls": 40,
        "totalCrosses": 20,
        "totalTackles": 12,
        "interceptions": 8,
        "totalClearance": clearances,
    }
    return {
        "team": {"displayName": team},
        "statistics": [{"name": key, "displayValue": str(value)} for key, value in values.items()],
    }


def _summary():
    return {
        "boxscore": {"teams": [
            _entry("Spain", 65, 700, 18, 8),
            _entry("Germany", 35, 350, 8, 2, 25),
        ]},
        "rosters": [
            {"team": {"displayName": "Spain"}, "formation": "4-3-3"},
            {"team": {"displayName": "Germany"}, "formation": "4-2-3-1"},
        ],
    }


def test_parse_tactical_match_uses_team_and_opponent_context():
    result = parse_tactical_match(_summary(), "Spain")
    assert result is not None
    assert result["possession"] == 0.65
    assert result["shots_for"] == 18
    assert result["shots_allowed"] == 8
    assert result["corners_allowed"] == 2
    assert result["formation"] == "4-3-3"


def test_parse_tactical_match_rejects_missing_required_stats():
    assert parse_tactical_match({"boxscore": {"teams": []}}, "Spain") is None


def test_aggregate_profile_requires_three_complete_matches():
    metrics = parse_tactical_match(_summary(), "Spain")
    assert aggregate_tactical_profile("Spain", [{"date": "2026-06-01", "metrics": metrics}]) is None


def test_aggregate_profile_is_recent_weighted_and_keeps_formation():
    low = parse_tactical_match(_summary(), "Spain")
    high = dict(low)
    high["shots_for"] = 24
    matches = [
        {"date": "2026-06-01", "metrics": low},
        {"date": "2026-06-05", "metrics": low},
        {"date": "2026-06-10", "metrics": high},
    ]
    profile = aggregate_tactical_profile("Spain", matches)
    assert profile is not None
    assert 18 < profile.shots_for < 24
    assert profile.formation == "4-3-3"
    assert profile.matches == 3


def test_team_resolution_merges_adjacent_display_dates(monkeypatch, tmp_path):
    client = WCTacticsClient(tmp_path)

    def fake_cached(key, url, ttl):
        if "20260621" in url:
            return {"events": [{"competitions": [{"competitors": [
                {"team": {"displayName": "Egypt", "id": "2620"}}
            ]}]}]}
        return {"events": []}

    monkeypatch.setattr(client, "_cached_json", fake_cached)
    assert client.resolve_team_ids(date(2026, 6, 22))["Egypt"] == "2620"


def test_team_resolution_adds_canonical_name_aliases(monkeypatch, tmp_path):
    client = WCTacticsClient(tmp_path)
    monkeypatch.setattr(client, "_cached_json", lambda *args: {
        "events": [{"competitions": [{"competitors": [
            {"team": {"displayName": "Türkiye", "id": "2036"}},
            {"team": {"displayName": "Cape Verde", "id": "1321"}},
        ]}]}]
    })
    result = client.resolve_team_ids(date(2026, 6, 22))
    assert result["Turkey"] == "2036"
    assert result["Cape Verde Islands"] == "1321"
