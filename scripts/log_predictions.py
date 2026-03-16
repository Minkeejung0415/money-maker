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
) -> None:
    """Append one prediction record to the JSONL log file."""
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
    }
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
