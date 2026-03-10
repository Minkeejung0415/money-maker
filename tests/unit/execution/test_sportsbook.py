from __future__ import annotations

from alpha.execution.sportsbook import SportsbookExecutor


def test_place_bet_positive_odds_payout() -> None:
    sb = SportsbookExecutor()
    bet = sb.place_bet("evt1", "TEAM_A", 100.0, 150)

    assert bet["event_id"] == "evt1"
    assert bet["selection"] == "TEAM_A"
    assert bet["stake_usd"] == 100.0
    assert bet["odds"] == 150
    # 100 * (150/100 + 1) = 250
    assert bet["potential_payout"] == 250.0
    assert bet["status"] == "paper"


def test_place_bet_negative_odds_payout() -> None:
    sb = SportsbookExecutor()
    bet = sb.place_bet("evt2", "TEAM_B", 110.0, -110)

    assert bet["odds"] == -110
    # 110 * (100/110 + 1) ≈ 210.0 after rounding
    assert bet["potential_payout"] == 210.0


def test_place_bet_appends_to_ledger() -> None:
    sb = SportsbookExecutor()
    assert sb.get_ledger() == []
    bet = sb.place_bet("evt3", "TEAM_C", 50.0, 200)
    ledger = sb.get_ledger()
    assert len(ledger) == 1
    assert ledger[0]["id"] == bet["id"]


def test_get_ledger_returns_copy() -> None:
    sb = SportsbookExecutor()
    sb.place_bet("evt4", "TEAM_D", 25.0, 120)
    external_ledger = sb.get_ledger()
    external_ledger.clear()
    # Internal ledger should be unaffected
    assert len(sb.get_ledger()) == 1


def test_settle_bet_updates_status_to_won() -> None:
    sb = SportsbookExecutor()
    bet = sb.place_bet("evt5", "TEAM_E", 75.0, 130)
    updated = sb.settle_bet(bet["id"], won=True)
    assert updated["status"] == "won"
    # Ensure internal ledger also updated
    assert sb.get_ledger()[0]["status"] == "won"


def test_settle_bet_unknown_id_returns_error() -> None:
    sb = SportsbookExecutor()
    res = sb.settle_bet("non-existent", won=True)
    assert res["status"] == "error"
    assert res["reason"] == "bet not found"


def test_place_bet_live_mode_raises_not_implemented() -> None:
    sb = SportsbookExecutor(paper=False)
    try:
        sb.place_bet("evt6", "TEAM_F", 10.0, 100)
        raised = False
    except NotImplementedError as e:  # noqa: PERF203
        raised = True
        assert "Live sportsbook API not implemented" in str(e)
    assert raised is True

