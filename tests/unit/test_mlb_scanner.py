from __future__ import annotations

import sys

from scripts import mlb_scanner


def test_parse_args_accepts_schedule_date(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["mlb_scanner.py", "--mode", "parlay", "--date", "2026-06-28"],
    )

    args = mlb_scanner._parse_args()

    assert args.mode == "parlay"
    assert args.date == "2026-06-28"
