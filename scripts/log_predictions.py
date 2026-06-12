"""
Prediction logger — appends one JSONL record per NBA prop prediction.

Each record stores everything needed to grade the pick later:
  player, market, line, direction (over/under), model_prob,
  market_implied, confidence, game_date, logged_at, outcome

outcome is None until graded. Fill it in with:
  True  = pick hit
  False = pick missed

File location: data/prediction_log.jsonl (one JSON object per line)

Usage:
  from scripts.log_predictions import log_prediction
  log_prediction(
      player="Jayson Tatum",
      market="player_points",
      line=28.5,
      direction="over",
      model_prob=0.72,
      market_implied=0.50,
      confidence="HIGH",
      game_date="2026-03-15",
  )
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG = Path("data/prediction_log.jsonl")


def log_prediction(
    player: str,
    market: str,
    line: float,
    model_prob: float,
    market_implied: float,
    confidence: str,
    game_date: str,
    direction: str = "over",
    outcome: bool | None = None,
    log_file: Path = DEFAULT_LOG,
    source: str = "rule_fallback",
    recommendation_eligible: bool = False,
    refusal_reasons: list[str] | None = None,
) -> None:
    """
    Append one prediction record to the JSONL log file (deduped by key).

    Diagnostic (research-only) rows ARE logged — they are needed for
    calibration — but each row records whether it was recommendation-
    eligible, so research rows can never be confused with actionable
    wagers when grading.  Defaults are fail-safe (research-only).
    """
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Dedup: skip if (player, market, line, direction, game_date) already logged
    dedup_key = (player, market, float(line), direction, game_date)
    if log_file.exists():
        with open(log_file, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    r = json.loads(raw)
                    if (r["player"], r["market"], float(r["line"]), r["direction"], r["game_date"]) == dedup_key:
                        return  # already logged
                except Exception:
                    continue

    record = {
        "player": player,
        "market": market,
        "line": line,
        "direction": direction,
        "model_prob": round(model_prob, 4),
        "market_implied": round(market_implied, 4),
        "confidence": confidence,
        "game_date": game_date,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "outcome": outcome,  # True=hit, False=miss, None=ungraded
        "source": source,
        "recommendation_eligible": recommendation_eligible,
        "research_only": not recommendation_eligible,
        "refusal_reasons": list(refusal_reasons or []),
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
