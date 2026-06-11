"""
MLBPredictionLogger — append-only JSONL prediction history with separate
settlement and closing-odds streams.

Files (all append-only; earlier snapshots are NEVER rewritten):
    predictions.jsonl   one snapshot per logged prediction
    settlements.jsonl   one settlement per prediction_id (idempotent)
    closing_odds.jsonl  closing market snapshots, stored separately

Rules:
  1. Prediction snapshots are immutable — corrections are new appends.
  2. Settlement is idempotent: re-settling a prediction with the same
     result is a no-op; a conflicting result is rejected and logged.
  3. CLV is computed only AFTER closing odds exist for a prediction.
  4. Ungraded predictions stay visible via ``ungraded()``.
  5. Calibrator fitting stays gated on graded chronological volume
     (``mlb_run_model.can_fit_calibrator``) — this module never fits one.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_LOG_DIR = Path("data") / "mlb_predictions"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError:
                logger.warning("Skipping corrupt line in %s", path.name)
    return records


class MLBPredictionLogger:
    def __init__(self, log_dir: Path | str = DEFAULT_LOG_DIR):
        self.log_dir = Path(log_dir)
        self.predictions_file = self.log_dir / "predictions.jsonl"
        self.settlements_file = self.log_dir / "settlements.jsonl"
        self.closing_odds_file = self.log_dir / "closing_odds.jsonl"

    # ------------------------------------------------------------------
    # Prediction snapshots (append-only)
    # ------------------------------------------------------------------

    def log_prediction(self, record: dict) -> str:
        """
        Append one prediction snapshot and return its prediction_id.
        Result / closing odds / CLV start as explicit placeholders.
        """
        snapshot = dict(record)
        snapshot.setdefault("prediction_id", uuid.uuid4().hex)
        snapshot.setdefault("created_at_utc", _utc_now_iso())
        # Placeholders filled later by settlement / closing-odds streams.
        snapshot.setdefault("result", None)
        snapshot.setdefault("closing_odds", None)
        snapshot.setdefault("clv", None)
        _append_jsonl(self.predictions_file, snapshot)
        return snapshot["prediction_id"]

    def predictions(self) -> list[dict]:
        return _read_jsonl(self.predictions_file)

    # ------------------------------------------------------------------
    # Settlement (idempotent, append-only)
    # ------------------------------------------------------------------

    def settle(
        self,
        prediction_id: str,
        winner: str,  # "home" | "away"
        home_score: int,
        away_score: int,
        settled_at_utc: str | None = None,
    ) -> bool:
        """
        Record the final result for a prediction.  Returns True when a new
        settlement was written.  Duplicate settlements with the same
        winner are no-ops; conflicting ones are rejected (first wins).
        """
        if winner not in ("home", "away"):
            raise ValueError(f"winner must be 'home' or 'away', got {winner!r}")

        existing = self._settlements_by_id().get(prediction_id)
        if existing is not None:
            if existing.get("winner") != winner:
                logger.error(
                    "Conflicting settlement for %s ignored (existing=%s new=%s)",
                    prediction_id, existing.get("winner"), winner,
                )
            return False

        _append_jsonl(self.settlements_file, {
            "prediction_id": prediction_id,
            "winner": winner,
            "home_score": int(home_score),
            "away_score": int(away_score),
            "settled_at_utc": settled_at_utc or _utc_now_iso(),
        })
        return True

    def _settlements_by_id(self) -> dict[str, dict]:
        by_id: dict[str, dict] = {}
        for rec in _read_jsonl(self.settlements_file):
            by_id.setdefault(rec.get("prediction_id", ""), rec)  # first wins
        return by_id

    # ------------------------------------------------------------------
    # Closing odds (stored separately)
    # ------------------------------------------------------------------

    def record_closing_odds(
        self,
        prediction_id: str,
        consensus_home_no_vig_prob: float,
        consensus_away_no_vig_prob: float,
        best_home_odds: int | None = None,
        best_away_odds: int | None = None,
        captured_at_utc: str | None = None,
    ) -> bool:
        """Append a closing-odds snapshot for a prediction (first wins)."""
        if prediction_id in self._closing_by_id():
            return False
        _append_jsonl(self.closing_odds_file, {
            "prediction_id": prediction_id,
            "consensus_home_no_vig_prob": float(consensus_home_no_vig_prob),
            "consensus_away_no_vig_prob": float(consensus_away_no_vig_prob),
            "best_home_odds": best_home_odds,
            "best_away_odds": best_away_odds,
            "captured_at_utc": captured_at_utc or _utc_now_iso(),
        })
        return True

    def _closing_by_id(self) -> dict[str, dict]:
        by_id: dict[str, dict] = {}
        for rec in _read_jsonl(self.closing_odds_file):
            by_id.setdefault(rec.get("prediction_id", ""), rec)
        return by_id

    # ------------------------------------------------------------------
    # Merged views
    # ------------------------------------------------------------------

    def merged_records(self) -> list[dict]:
        """
        Predictions joined with their settlement and closing odds.  The
        underlying snapshots stay untouched; this is a read-time view.
        CLV appears only for predictions that have BOTH a logged market
        consensus and closing odds.
        """
        settlements = self._settlements_by_id()
        closings = self._closing_by_id()
        merged = []
        for pred in self.predictions():
            rec = dict(pred)
            pid = rec.get("prediction_id", "")
            settlement = settlements.get(pid)
            if settlement is not None:
                rec["result"] = {
                    "winner": settlement["winner"],
                    "home_score": settlement["home_score"],
                    "away_score": settlement["away_score"],
                    "settled_at_utc": settlement["settled_at_utc"],
                }
            closing = closings.get(pid)
            if closing is not None:
                rec["closing_odds"] = {
                    k: closing[k]
                    for k in (
                        "consensus_home_no_vig_prob",
                        "consensus_away_no_vig_prob",
                        "best_home_odds",
                        "best_away_odds",
                        "captured_at_utc",
                    )
                }
                rec["clv"] = self._compute_clv(pred, closing)
            merged.append(rec)
        return merged

    def ungraded(self) -> list[dict]:
        """Predictions without a settlement — kept visible, never dropped."""
        return [r for r in self.merged_records() if r.get("result") is None]

    def graded_count(self) -> int:
        return sum(1 for r in self.merged_records() if r.get("result") is not None)

    @staticmethod
    def _compute_clv(prediction: dict, closing: dict) -> dict | None:
        """
        Probability-space CLV: how far the no-vig market moved between the
        logged snapshot and close.  Positive home move = home steam.
        Only computable when the prediction carried a real consensus.
        """
        logged_home = prediction.get("market_consensus_home_no_vig_prob")
        closing_home = closing.get("consensus_home_no_vig_prob")
        if logged_home is None or closing_home is None:
            return None
        move = round(float(closing_home) - float(logged_home), 6)
        return {
            "home_prob_move": move,
            "away_prob_move": round(-move, 6),
            "logged_home_no_vig_prob": float(logged_home),
            "closing_home_no_vig_prob": float(closing_home),
        }
