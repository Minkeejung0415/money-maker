from unittest.mock import MagicMock, patch
from alpha.orchestrator import Orchestrator


def test_orchestrator_initializes_with_verticals():
    orch = Orchestrator(verticals=["stocks", "crypto", "sports"])
    assert "stocks" in orch.verticals
    assert "crypto" in orch.verticals
    assert "sports" in orch.verticals


def test_orchestrator_skips_disabled_verticals():
    orch = Orchestrator(verticals=["stocks"])
    assert "crypto" not in orch.verticals
    assert "sports" not in orch.verticals


def test_orchestrator_respects_risk_off(monkeypatch):
    orch = Orchestrator(verticals=["stocks", "crypto", "sports"])
    monkeypatch.setattr(orch.macro_filter, "is_risk_on", lambda r: False)
    scalar = orch.macro_filter.get_position_scalar({"VIXCLS": 45.0})
    assert scalar == 0.25


# ---------------------------------------------------------------------------
# Fix 2: _run_stocks graceful failure when all fetches raise
# ---------------------------------------------------------------------------

def test_run_stocks_returns_empty_when_all_fetches_fail():
    """If every fetch_daily call raises, _run_stocks returns empty positions."""
    orch = Orchestrator(verticals=["stocks"])
    orch.settings.alpha_vantage_api_key = "key"

    with patch("alpha.data.ingestion.alpha_vantage.AlphaVantageClient.fetch_daily",
               side_effect=RuntimeError("network down")), \
         patch("time.sleep"):  # skip 12-s sleep in tests
        result = orch._run_stocks(position_scalar=1.0)

    assert result["vertical"] == "stocks"
    assert result["positions"] == {}
    assert result["orders"] == []


# ---------------------------------------------------------------------------
# Fix 3: _run_crypto graceful failure when all fetches raise
# ---------------------------------------------------------------------------

def test_run_crypto_returns_empty_when_all_fetches_fail():
    """If every fetch_ohlcv call raises, _run_crypto returns empty positions."""
    orch = Orchestrator(verticals=["crypto"])

    with patch("alpha.data.ingestion.crypto_feeds.fetch_ohlcv",
               side_effect=RuntimeError("exchange down")):
        result = orch._run_crypto(position_scalar=1.0)

    assert result["vertical"] == "crypto"
    assert result["positions"] == {}
    assert result["orders"] == []


# ---------------------------------------------------------------------------
# Fix 1: _run_sports returns empty when no games fetched
# ---------------------------------------------------------------------------

def test_run_sports_returns_empty_when_no_games():
    """When OddsAPIClient.fetch_nba_games returns [], sports vertical is skipped."""
    orch = Orchestrator(verticals=["sports"])

    with patch("alpha.data.ingestion.odds_api.OddsAPIClient.fetch_nba_games",
               return_value=[]):
        result = orch._run_sports(position_scalar=1.0)

    assert result["vertical"] == "sports"
    assert result["bets"] == []
    assert result["orders"] == []
