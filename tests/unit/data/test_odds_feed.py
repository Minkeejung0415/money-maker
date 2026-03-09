from unittest.mock import patch, MagicMock
from alpha.data.ingestion.odds_feed import OddsIngester


def test_ingester_builds_scrape_params():
    ingester = OddsIngester()
    params = ingester._build_params(sport="basketball", markets=["1x2"])
    assert params["sport"] == "basketball"
    assert "1x2" in params["markets"]


def test_parse_odds_row():
    ingester = OddsIngester()
    raw = {
        "home_team": "Lakers",
        "away_team": "Celtics",
        "odds_home": 1.85,
        "odds_away": 2.10,
        "book": "fanduel",
        "market": "moneyline",
    }
    row = ingester._parse_row(raw, sport="basketball", league="nba")
    assert row["event"] == "Lakers vs Celtics"
    assert row["sport"] == "basketball"
    assert row["odds_home"] == 1.85
