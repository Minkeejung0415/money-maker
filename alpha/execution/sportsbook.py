"""In-memory sportsbook paper trading executor."""

from __future__ import annotations

import copy
import uuid
from typing import Any


class SportsbookExecutor:
    """Paper-trading sportsbook executor with an in-memory ledger."""

    def __init__(self, paper: bool = True) -> None:
        self.paper = paper
        self._ledger: list[dict[str, Any]] = []

    def place_bet(self, event_id: str, selection: str, stake_usd: float, odds: int) -> dict[str, Any]:
        """Place a simulated bet in paper mode or raise for live mode."""
        if not self.paper:
            raise NotImplementedError("Live sportsbook API not implemented")

        stake = float(stake_usd)
        if odds > 0:
            potential_payout = stake * (odds / 100 + 1)
        else:
            potential_payout = stake * (100 / abs(odds) + 1)

        bet = {
            "id": str(uuid.uuid4()),
            "event_id": event_id,
            "selection": selection,
            "stake_usd": stake,
            "odds": int(odds),
            "status": "paper",
            "potential_payout": float(round(potential_payout, 2)),
        }
        self._ledger.append(bet)
        return bet

    def get_ledger(self) -> list[dict[str, Any]]:
        """Return a shallow copy of the current ledger."""
        return copy.deepcopy(self._ledger)

    def settle_bet(self, bet_id: str, won: bool) -> dict[str, Any]:
        """Settle a bet in the ledger."""
        for bet in self._ledger:
            if bet.get("id") == bet_id:
                bet["status"] = "won" if won else "lost"
                return bet.copy()
        return {"status": "error", "reason": "bet not found"}

