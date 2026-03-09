from alpha.orchestrator import Orchestrator


def test_orchestrator_has_risk_components():
    orch = Orchestrator(total_capital=100_000.0)
    assert hasattr(orch, "position_sizer")
    assert hasattr(orch, "drawdown_monitor")
    assert hasattr(orch, "exposure_limiter")


def test_effective_scalar_macro_wins():
    orch = Orchestrator(total_capital=100_000.0)
    # Macro says 0.5, no drawdown → effective = 0.5
    scalar = orch.get_effective_scalar(current_capital=100_000.0, macro_scalar=0.5)
    assert scalar == 0.5


def test_effective_scalar_drawdown_wins():
    orch = Orchestrator(total_capital=100_000.0)
    # Drawdown at 15% with 20% max → scalar = 0.25; macro = 1.0
    scalar = orch.get_effective_scalar(current_capital=85_000.0, macro_scalar=1.0)
    assert scalar < 1.0


def test_circuit_breaker_zeroes_scalar():
    orch = Orchestrator(total_capital=100_000.0)
    orch.drawdown_monitor.max_drawdown_pct = 0.10
    # 20% drawdown → breaker triggers → scalar = 0
    scalar = orch.get_effective_scalar(current_capital=79_000.0, macro_scalar=1.0)
    assert scalar == 0.0


def test_run_cycle_returns_results():
    orch = Orchestrator(verticals=["stocks"], total_capital=100_000.0)
    # Won't hit network — stocks engine returns empty dict stub
    result = orch._run_vertical("stocks", position_scalar=1.0)
    assert result["vertical"] == "stocks"
