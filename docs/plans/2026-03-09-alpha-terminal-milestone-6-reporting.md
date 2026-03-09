# Alpha Terminal — Milestone 6: Reporting

**Goal:** Build `alpha/reporting/` — cross-vertical P&L tracker,
immutable audit log, and a plotly dashboard skeleton.

---

### Task 1: P&L Tracker
- `alpha/reporting/pnl_tracker.py` — record trades, compute P&L by vertical
- `tests/unit/reporting/test_pnl_tracker.py`

### Task 2: Audit Log
- `alpha/reporting/audit_log.py` — append-only trade record with SQLite backing
- `tests/unit/reporting/test_audit_log.py`

### Task 3: Dashboard Skeleton
- `alpha/reporting/dashboard.py` — Streamlit + plotly P&L charts
- `tests/unit/reporting/test_dashboard.py`
