"""
PaperBettingLogger — append-only JSONL log of paper (simulated) bets.

This is PAPER BETTING ONLY: no wagering automation exists or may be added.
Every prediction that would have been bet is logged pregame with the full
context needed to grade it later (model probabilities, market consensus,
offered odds, stake suggestion), then settled post-game with the result,
closing line, CLV, and PnL.

Conventions:
  - American odds throughout.
  - clv (closing line value) = implied_prob(closing_odds)
                             - implied_prob(offered_odds);
    positive = we beat the close.  When closing_consensus_prob is given it
    is used as the closing probability instead (it is already no-vig).
  - pnl is computed from offered_odds and suggested_stake:
    win → stake * (decimal - 1), loss → -stake, push/void → 0.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_LOG = Path("data/paper_bets/paper_bets.jsonl")

RESULTS = {"win", "loss", "push", "void"}

# Every prediction record carries these keys (None when not applicable).
RECORD_FIELDS = [
    "prediction_id", "event_id", "created_at_utc", "commence_time_utc",
    "sport", "market", "player", "side", "line", "bookmaker",
    "offered_odds", "consensus_line", "consensus_no_vig_prob",
    "independent_model_prob", "final_calibrated_prob",
    "projected_stat", "projected_minutes",
    "model_version", "feature_schema_version",
    "bankroll_before", "suggested_stake",
    "result", "closing_line", "closing_odds", "closing_consensus_prob",
    "clv", "pnl",
    # Real-money gating provenance: research-only rows are kept for
    # calibration but must never be confused with actionable wagers.
    "recommendation_eligible", "research_only", "refusal_reasons",
]


def american_to_implied(odds: int | float) -> float:
    odds = float(odds)
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def american_to_decimal(odds: int | float) -> float:
    odds = float(odds)
    if odds > 0:
        return 1.0 + odds / 100.0
    return 1.0 + 100.0 / abs(odds)


class PaperBettingLogger:
    def __init__(self, log_path: Path | str = _DEFAULT_LOG):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log_prediction(
        self,
        event_id: str,
        sport: str,
        market: str,
        side: str,
        offered_odds: int,
        final_calibrated_prob: float,
        model_version: str,
        feature_schema_version: str,
        commence_time_utc: str = "",
        player: str | None = None,
        line: float | None = None,
        bookmaker: str | None = None,
        consensus_line: float | None = None,
        consensus_no_vig_prob: float | None = None,
        independent_model_prob: float | None = None,
        projected_stat: float | None = None,
        projected_minutes: float | None = None,
        bankroll_before: float | None = None,
        suggested_stake: float | None = None,
        recommendation_eligible: bool = False,
        refusal_reasons: list[str] | None = None,
    ) -> str:
        """
        Append a pregame prediction record; returns its prediction_id.

        Research-only (non-eligible) rows are logged too — they feed
        calibration — but carry recommendation_eligible=False,
        research_only=True, and their refusal_reasons.  Defaults are
        fail-safe: a row is research-only unless explicitly marked
        eligible by the model's gating.
        """
        record = {field: None for field in RECORD_FIELDS}
        record.update({
            "prediction_id": uuid.uuid4().hex,
            "event_id": event_id,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "commence_time_utc": commence_time_utc,
            "sport": sport,
            "market": market,
            "player": player,
            "side": side,
            "line": line,
            "bookmaker": bookmaker,
            "offered_odds": offered_odds,
            "consensus_line": consensus_line,
            "consensus_no_vig_prob": consensus_no_vig_prob,
            "independent_model_prob": independent_model_prob,
            "final_calibrated_prob": final_calibrated_prob,
            "projected_stat": projected_stat,
            "projected_minutes": projected_minutes,
            "model_version": model_version,
            "feature_schema_version": feature_schema_version,
            "bankroll_before": bankroll_before,
            "suggested_stake": suggested_stake,
            "recommendation_eligible": recommendation_eligible,
            "research_only": not recommendation_eligible,
            "refusal_reasons": list(refusal_reasons or []),
        })
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return record["prediction_id"]

    # ------------------------------------------------------------------
    # Settlement
    # ------------------------------------------------------------------

    def settle(
        self,
        prediction_id: str,
        result: str,
        closing_line: float | None = None,
        closing_odds: int | None = None,
        closing_consensus_prob: float | None = None,
    ) -> dict | None:
        """
        Grade a logged prediction.  Computes clv and pnl, rewrites the log.
        Returns the settled record, or None if prediction_id is unknown.
        """
        if result not in RESULTS:
            raise ValueError(f"result must be one of {sorted(RESULTS)}; got {result!r}")

        records = self.load()
        target = None
        for rec in records:
            if rec["prediction_id"] == prediction_id:
                target = rec
                break
        if target is None:
            logger.warning("settle(): unknown prediction_id %s", prediction_id)
            return None

        target["result"] = result
        target["closing_line"] = closing_line
        target["closing_odds"] = closing_odds
        target["closing_consensus_prob"] = closing_consensus_prob

        offered_implied = american_to_implied(target["offered_odds"])
        if closing_consensus_prob is not None:
            target["clv"] = round(float(closing_consensus_prob) - offered_implied, 6)
        elif closing_odds is not None:
            target["clv"] = round(american_to_implied(closing_odds) - offered_implied, 6)
        else:
            target["clv"] = None

        stake = target.get("suggested_stake") or 0.0
        if result == "win":
            target["pnl"] = round(stake * (american_to_decimal(target["offered_odds"]) - 1.0), 4)
        elif result == "loss":
            target["pnl"] = round(-stake, 4)
        else:  # push / void
            target["pnl"] = 0.0

        self._rewrite(records)
        return target

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def load(self) -> list[dict]:
        """All records, in insertion (time) order."""
        if not self.log_path.exists():
            return []
        records: list[dict] = []
        for raw_line in self.log_path.read_text(encoding="utf-8").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                records.append(json.loads(raw_line))
            except json.JSONDecodeError:
                logger.warning("Skipping corrupt paper-bet line")
        return records

    def settled(self) -> list[dict]:
        return [r for r in self.load() if r.get("result") is not None]

    def open_bets(self) -> list[dict]:
        return [r for r in self.load() if r.get("result") is None]

    def _rewrite(self, records: list[dict]) -> None:
        tmp = self.log_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
        tmp.replace(self.log_path)
