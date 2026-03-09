# Alpha Terminal — Milestone 4: Sports Engine

**Goal:** Wire `alpha/engines/sports/` with NBA-ML model wrapper,
Kelly criterion sizing, EV calculator, and unified sports engine.

**Depends on:** Milestones 1-3

---

### Task 1: EV Calculator
- `alpha/engines/sports/ev_calculator.py` — expected value across markets
- `tests/unit/engines/test_ev_calculator.py`

### Task 2: Kelly Criterion Sizer
- `alpha/engines/sports/kelly.py` — fractional Kelly sizing
- `tests/unit/engines/test_kelly.py`

### Task 3: NBA Model Wrapper
- `alpha/engines/sports/nba_model.py` — wrap NBA-ML XGBoost signals
- `tests/unit/engines/test_nba_model.py`

### Task 4: Sports Engine Entry Point
- `alpha/engines/sports/engine.py` — ties odds feed + EV + Kelly → bets
- `tests/unit/engines/test_sports_engine.py`
