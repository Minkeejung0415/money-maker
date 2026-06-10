"""
Evaluation metrics and walk-forward scaffolding for the NBA betting models.

Three metric families:
  - Projection:  MAE, RMSE
  - Probability: Brier score, log loss, reliability table (calibration
    plot data)
  - Betting:     ROI, yield, win rate, CLV stats, max drawdown, streaks
    — computed from PAPER bets only.

Walk-forward rules enforced by walkforward_splits():
  - time-ordered splits only, never train on future games
  - calibration data must come from the validation window, never from
    model-training rows (callers split the train window further)
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Projection metrics
# ---------------------------------------------------------------------------

def mae(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    _check_same_len(y_true, y_pred)
    return sum(abs(t - p) for t, p in zip(y_true, y_pred)) / len(y_true)


def rmse(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    _check_same_len(y_true, y_pred)
    return math.sqrt(sum((t - p) ** 2 for t, p in zip(y_true, y_pred)) / len(y_true))


def projection_metrics(y_true: Sequence[float], y_pred: Sequence[float]) -> dict:
    return {"mae": mae(y_true, y_pred), "rmse": rmse(y_true, y_pred),
            "n": len(y_true)}


# ---------------------------------------------------------------------------
# Probability metrics
# ---------------------------------------------------------------------------

def brier_score(outcomes: Sequence[int], probs: Sequence[float]) -> float:
    """Mean squared error of probabilities vs binary outcomes (0 best)."""
    _check_same_len(outcomes, probs)
    return sum((p - o) ** 2 for o, p in zip(outcomes, probs)) / len(outcomes)


def log_loss(outcomes: Sequence[int], probs: Sequence[float], eps: float = 1e-12) -> float:
    _check_same_len(outcomes, probs)
    total = 0.0
    for o, p in zip(outcomes, probs):
        p = min(max(p, eps), 1.0 - eps)
        total += -(o * math.log(p) + (1 - o) * math.log(1.0 - p))
    return total / len(outcomes)


def reliability_table(
    outcomes: Sequence[int], probs: Sequence[float], n_bins: int = 10
) -> list[dict]:
    """
    Calibration plot data: per probability bin, mean predicted probability
    vs observed hit rate.  Empty bins are omitted.
    """
    _check_same_len(outcomes, probs)
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for o, p in zip(outcomes, probs):
        idx = min(n_bins - 1, int(p * n_bins))
        bins[idx].append((p, o))
    table = []
    for i, entries in enumerate(bins):
        if not entries:
            continue
        preds = [p for p, _ in entries]
        obs = [o for _, o in entries]
        table.append({
            "bin_low": i / n_bins,
            "bin_high": (i + 1) / n_bins,
            "mean_predicted": sum(preds) / len(preds),
            "observed_rate": sum(obs) / len(obs),
            "count": len(entries),
        })
    return table


def probability_metrics(outcomes: Sequence[int], probs: Sequence[float]) -> dict:
    return {
        "brier_score": brier_score(outcomes, probs),
        "log_loss": log_loss(outcomes, probs),
        "reliability_table": reliability_table(outcomes, probs),
        "n": len(outcomes),
    }


# ---------------------------------------------------------------------------
# Betting metrics (paper bets only)
# ---------------------------------------------------------------------------

def betting_metrics(bets: list[dict]) -> dict:
    """
    Aggregate paper-bet performance.  Each bet dict needs result, pnl,
    suggested_stake (clv optional).  Unsettled bets are ignored.
    """
    settled = [b for b in bets if b.get("result") in ("win", "loss", "push")]
    decided = [b for b in settled if b["result"] in ("win", "loss")]

    total_stake = sum(float(b.get("suggested_stake") or 0.0) for b in settled)
    total_pnl = sum(float(b.get("pnl") or 0.0) for b in settled)
    clvs = [float(b["clv"]) for b in settled if b.get("clv") is not None]

    # Max drawdown over the cumulative pnl curve (insertion order = time).
    peak = drawdown = cum = 0.0
    for b in settled:
        cum += float(b.get("pnl") or 0.0)
        peak = max(peak, cum)
        drawdown = max(drawdown, peak - cum)

    streak = longest_losing = 0
    for b in decided:
        if b["result"] == "loss":
            streak += 1
            longest_losing = max(longest_losing, streak)
        else:
            streak = 0

    roi = (total_pnl / total_stake) if total_stake > 0 else 0.0
    return {
        "num_bets": len(settled),
        "roi": round(roi, 6),
        "yield_pct": round(roi * 100, 4),
        "win_rate": round(
            sum(1 for b in decided if b["result"] == "win") / len(decided), 6
        ) if decided else 0.0,
        "total_pnl": round(total_pnl, 4),
        "avg_stake": round(total_stake / len(settled), 4) if settled else 0.0,
        "avg_clv": round(sum(clvs) / len(clvs), 6) if clvs else None,
        "median_clv": round(_median(clvs), 6) if clvs else None,
        "max_drawdown": round(drawdown, 4),
        "longest_losing_streak": longest_losing,
    }


def _odds_bucket(odds: float | None) -> str:
    if odds is None:
        return "unknown"
    odds = float(odds)
    if odds <= -200:
        return "heavy_favorite(<=-200)"
    if odds <= -120:
        return "favorite(-200..-120)"
    if odds < 120:
        return "near_even(-120..+120)"
    if odds <= 250:
        return "underdog(+120..+250)"
    return "longshot(>+250)"


def _confidence_bucket(prob: float | None) -> str:
    if prob is None:
        return "unknown"
    if prob >= 0.70:
        return ">=0.70"
    if prob >= 0.60:
        return "0.60-0.70"
    if prob >= 0.55:
        return "0.55-0.60"
    return "<0.55"


def _month(rec: dict) -> str:
    for key in ("commence_time_utc", "created_at_utc"):
        v = rec.get(key)
        if v:
            try:
                return datetime.fromisoformat(str(v).replace("Z", "+00:00")).strftime("%Y-%m")
            except ValueError:
                continue
    return "unknown"


GROUPERS: dict[str, Any] = {
    "market": lambda r: r.get("market") or "unknown",
    "player": lambda r: r.get("player") or "(team market)",
    "bookmaker": lambda r: r.get("bookmaker") or "unknown",
    "confidence_bucket": lambda r: _confidence_bucket(r.get("final_calibrated_prob")),
    "odds_bucket": lambda r: _odds_bucket(r.get("offered_odds")),
    "month": _month,
    "model_version": lambda r: r.get("model_version") or "unknown",
}


def grouped_betting_report(bets: list[dict], dimensions: Iterable[str] | None = None) -> dict:
    """Betting metrics grouped by each requested dimension."""
    report: dict[str, dict[str, dict]] = {}
    for dim in (dimensions or GROUPERS.keys()):
        grouper = GROUPERS[dim]
        groups: dict[str, list[dict]] = {}
        for b in bets:
            groups.setdefault(grouper(b), []).append(b)
        report[dim] = {key: betting_metrics(group) for key, group in sorted(groups.items())}
    return report


# ---------------------------------------------------------------------------
# Walk-forward splits
# ---------------------------------------------------------------------------

def walkforward_splits(
    dates: Sequence, n_folds: int = 5, min_train_frac: float = 0.4
) -> list[tuple[list[int], list[int]]]:
    """
    Expanding-window walk-forward splits over time-ordered data.

    ``dates`` must be sortable; indices are returned in chronological
    order.  Each fold trains on everything strictly BEFORE the test
    window — training on future games is impossible by construction.
    """
    order = sorted(range(len(dates)), key=lambda i: dates[i])
    n = len(order)
    start = int(n * min_train_frac)
    fold_size = max(1, (n - start) // n_folds)
    splits: list[tuple[list[int], list[int]]] = []
    for f in range(n_folds):
        test_lo = start + f * fold_size
        test_hi = n if f == n_folds - 1 else test_lo + fold_size
        if test_lo >= n:
            break
        splits.append((order[:test_lo], order[test_lo:test_hi]))
    return splits


# ---------------------------------------------------------------------------
# Moneyline heuristic ablation configs
# ---------------------------------------------------------------------------

def moneyline_ablation_configs() -> dict[str, dict]:
    """
    NBAModel constructor kwargs for ablation runs: a stripped base model,
    base + each component individually, and the full default config.
    (base + market consensus as an ensemble FEATURE is deferred until a
    moneyline trainer with market features exists in this repo.)
    """
    base = dict(
        enable_paint_deterrence=False,
        enable_foul_exposure=False,
        enable_recent_form=False,
        enable_h2h=False,
        enable_tanking_guard=False,
        enable_injury_adjustment=False,
        enable_rest_features=False,
    )
    configs = {"base": dict(base), "full_default": {}}
    for component in (
        "enable_injury_adjustment",
        "enable_rest_features",
        "enable_paint_deterrence",
        "enable_foul_exposure",
        "enable_recent_form",
        "enable_h2h",
        "enable_tanking_guard",
    ):
        cfg = dict(base)
        cfg[component] = True
        configs[f"base+{component.removeprefix('enable_')}"] = cfg
    return configs


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _check_same_len(a: Sequence, b: Sequence) -> None:
    if len(a) != len(b) or len(a) == 0:
        raise ValueError(f"Inputs must be equal-length and non-empty (got {len(a)}, {len(b)})")
