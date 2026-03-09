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
