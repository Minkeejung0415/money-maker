# Alpha Terminal — Milestone 5: Risk Layer

**Goal:** Build `alpha/risk/` — cross-asset position sizer, real-time
drawdown monitor with circuit breaker, and exposure limiter.

---

### Task 1: Cross-Asset Position Sizer
- `alpha/risk/position_sizer.py`
- `tests/unit/risk/test_position_sizer.py`

### Task 2: Drawdown Monitor + Circuit Breaker
- `alpha/risk/drawdown.py`
- `tests/unit/risk/test_drawdown.py`

### Task 3: Exposure Limiter
- `alpha/risk/exposure.py`
- `tests/unit/risk/test_exposure.py`

### Task 4: Wire Risk into Orchestrator
- Update `alpha/orchestrator.py` to apply risk layer to all engine outputs
- `tests/unit/test_orchestrator_risk.py`
