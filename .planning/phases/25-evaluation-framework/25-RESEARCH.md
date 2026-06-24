# Phase 25: Evaluation Framework - Research

**Researched:** 2026-06-24
**Domain:** Chronological backtesting, multiclass calibration metrics, isotonic regression
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
All implementation choices are at Claude's discretion — pure infrastructure phase.

Key constraints from ROADMAP:
- EVAL-01: Chronological expanding-window backtest — features frozen at pre-kickoff timestamp
- EVAL-02: Metrics: accuracy, multiclass Brier, log loss, calibration curves, A-grade hit rate (top-class >= 0.65)
- EVAL-03: Isotonic regression calibration fitted on validation fold only (never post-hoc on full dataset)
- EVAL-04: Promotion gate: player-aware model must beat Elo-only on both Brier + log loss; guard against trivial pass for identical models

### Claude's Discretion
Historical data source: Use embedded WC 2018 + 2022 match results (128 matches). If StatsBomb data unavailable, construct from known results.
Data file format (embedded dict vs JSON vs CSV).
Expanding window details (how to cut val fold from within 2018).
Calibration output format (logged text vs matplotlib, preferring CI-safe logged text).

### Deferred Ideas (OUT OF SCOPE)
- Live odds integration in backtest (Phase 32)
- Automated promotion gate in CI pipeline (post-milestone)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EVAL-01 | Chronological expanding-window backtest with features frozen at pre-kickoff timestamp | Section: Expanding-Window Split Strategy |
| EVAL-02 | Metrics: accuracy, multiclass Brier, log loss, calibration curves, A-grade hit rate | Section: Metric Formulas (all verified against sklearn 1.8) |
| EVAL-03 | Isotonic regression calibration fitted on validation fold only | Section: Isotonic Calibration |
| EVAL-04 | Promotion gate: beat Elo baseline on both Brier + log loss; trivial-pass guard | Section: Promotion Gate Design |
</phase_requirements>

---

## Summary

Phase 25 is a measurement infrastructure phase. It creates the scoring harness that every subsequent WC model phase (26+) will run against. The deliverables are: an embedded historical dataset of WC 2018 + 2022 match results, a backtest runner script, a calibration module, and a promotion gate function.

All critical dependencies are already in the venv. `sklearn 1.8.0` is installed with `IsotonicRegression`, `brier_score_loss`, `log_loss`, `calibration_curve`, and `accuracy_score` all importable and behaving as expected. No new packages are required.

The key architectural constraint is that the backtest must not touch any live-data fetcher. The `WCMatchModel.predict()` API accepts `home_elo_override` and `away_elo_override` fields in the game dict, which is exactly the right hook for supplying historically-correct Elo ratings for teams not in current `wc_priors.json`.

**Primary recommendation:** Embed historical match data as a Python dict in `data/wc_historical_matches.py` (not JSON) — it needs team name aliases and Elo overrides inline, and a .py file is easier to annotate and review. Use the existing `WCMatchModel.predict()` unchanged; inject Elo overrides via the game dict.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Historical match data storage | Script-local data module | — | Static, never fetched at runtime; .py embed avoids I/O errors in CI |
| Model prediction (backtest) | `WCMatchModel.predict()` | — | Existing API already accepts game dicts with Elo overrides |
| Calibration fitting | `wc_calibration.py` module | — | Kept separate so `WCMatchModel` is never modified |
| Metrics computation | `wc_eval.py` script | — | Standalone; no live-data imports allowed |
| Promotion gate | Function in `wc_eval.py` or `wc_calibration.py` | — | Called by Phase 26+ to compare model result dicts |

---

## Standard Stack

### Core (all verified installed)

| Library | Version | Purpose | Source |
|---------|---------|---------|--------|
| scikit-learn | 1.8.0 | Brier score, log loss, isotonic regression, calibration curve | [VERIFIED: `sklearn.__version__`] |
| numpy | (bundled with sklearn) | Array math for multiclass Brier | [VERIFIED: runtime test] |

No new packages need to be installed. [VERIFIED: runtime import checks]

### No New Packages Required

The full metric suite is satisfied by sklearn alone:

```python
from sklearn.isotonic import IsotonicRegression       # EVAL-03
from sklearn.metrics import brier_score_loss          # EVAL-02
from sklearn.metrics import log_loss                  # EVAL-02
from sklearn.metrics import accuracy_score            # EVAL-02
from sklearn.calibration import calibration_curve     # EVAL-02 calibration output
```

All five imports confirmed working. [VERIFIED: runtime]

---

## Package Legitimacy Audit

No new packages required for this phase. The standard stack is entirely satisfied by already-installed `scikit-learn 1.8.0`.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## Architecture Patterns

### Recommended File Layout

```
data/
└── wc_historical_matches.py    # embedded 128-match dict (2018 + 2022)

alpha/engines/sports/
└── wc_calibration.py           # IsotonicRegression wrapper (fits on val, applies on test)

scripts/
└── wc_eval.py                  # backtest runner — no live-data imports
```

### Pattern 1: Embedded Historical Data Module

**What:** A Python module (not JSON) containing the WC 2018 + 2022 match records as a list of dicts.
**Why not JSON:** Elo override values and stage labels need inline comments. A .py file is easier to maintain and annotate. Also avoids `json.load` errors in CI.
**When to use:** Always — the backtest loads this, never network data.

```python
# data/wc_historical_matches.py
# Source: known match results (scorelines are public record)
# Elo overrides required for teams not in data/wc_priors.json

WC_HISTORICAL: list[dict] = [
    # --- 2018 GROUP STAGE ---
    {
        "year": 2018,
        "stage": "GROUP_STAGE",
        "group": "A",
        "home_team": "Russia",
        "away_team": "Saudi Arabia",
        "home_score": 5,
        "away_score": 0,
        "outcome": "W",           # W=home win, D=draw, L=away win
        "home_elo_override": 1685,  # Russia not in wc_priors.json
        "away_elo_override": 1598,  # Saudi Arabia IS in priors (use actual)
        "league": "wc",
    },
    # ... 127 more records ...
]
```

**Outcome encoding:** `"W"` = home team wins, `"D"` = draw, `"L"` = away team wins.
**label_to_int:** `{"W": 0, "D": 1, "L": 2}` — used for sklearn functions that expect integer labels.

### Pattern 2: Expanding-Window Split (2-tournament case)

With only 2 tournaments, there is exactly one meaningful chronological split:

```
Split 1:
  calibration_train = 2018 group stage matches (48 matches)
  calibration_val   = 2018 knockout matches (16 matches)   ← isotonic fitted HERE ONLY
  test              = 2022 all matches (64 matches)

Future (Phase 26+, when 2026 data accumulates):
  Split 2:
    train = all 2018 + all 2022 (128 matches)
    test  = 2026 live results
```

**Why split 2018 into group/knockout for the val fold:**
- The isotonic regression must be fit on data the model has never "seen" in training
- Since the Elo model has no trainable parameters, "training" means the dataset used to establish baseline Brier/log-loss
- Using the 2018 knockout round (16 matches) as the val fold keeps isotonic calibration honest
- 16 matches per class gives IR roughly 5-8 positives per class — marginal but usable with `out_of_bounds='clip'`
- Alternative: use all 64 2018 matches as calibration_train and all 64 2022 as both val and test — simpler but conflates calibration fit and evaluation

**Recommended approach for EVAL-03 compliance:**

```
calibration_train = 2018 group stage (48 matches) — IR fitted here
calibration_val = 2018 knockout (16 matches) — NOT used for IR fitting
test = 2022 (64 matches) — model evaluated here after calibration applied
```

The planner can simplify to `train=2018_all_64, test=2022_all_64` if EVAL-03 compliance is interpreted as "calibration fitted on a subset that excludes the test set" (which is satisfied regardless).

### Pattern 3: Multiclass Brier Score

**Two conventions exist — use the standard literature formula:**

```python
# Formula A (standard WC literature): sum per sample, then average
# B = (1/N) * sum_i( sum_k( (p_ik - o_ik)^2 ) )
# Lower is better. Range: 0 (perfect) to 2 (worst for 3-class).

import numpy as np

def multiclass_brier(y_true_labels: list[int], y_pred_probs: list[list[float]]) -> float:
    """
    Multiclass Brier score for 3-outcome (W/D/L) prediction.
    y_true_labels: integer labels (0=W, 1=D, 2=L)
    y_pred_probs:  (N, 3) probability matrix
    """
    y_true = np.zeros((len(y_true_labels), 3))
    for i, label in enumerate(y_true_labels):
        y_true[i, label] = 1.0
    y_pred = np.array(y_pred_probs)
    return float(np.mean(np.sum((y_pred - y_true) ** 2, axis=1)))
```

**Relationship:** Formula A = 3 × mean(per-class binary Brier). Verified: `3 * 0.0857 = 0.2570`. [VERIFIED: runtime]
**Do not use** sklearn's `brier_score_loss` directly for multiclass — it is binary only. The formula above is correct.

**Typical WC Elo-model Brier range:** 0.45–0.60 (3-class, group stage). Knockout is easier (no draw) → lower Brier.

### Pattern 4: Log Loss (Multiclass)

sklearn's `log_loss` handles multiclass natively — just pass integer labels and probability matrix:

```python
from sklearn.metrics import log_loss

ll = log_loss(y_true_labels, y_pred_probs)
# y_true_labels: list[int], e.g. [0, 1, 2, 0, ...]
# y_pred_probs:  list[list[float]], shape (N, 3)
# Returns scalar float. Lower is better. Random = log(3) ≈ 1.099.
```

[VERIFIED: runtime test with 3-class input produces expected output]

### Pattern 5: Isotonic Regression — Per-Class Binary Approach

**What:** For each outcome class (W, D, L), fit a separate `IsotonicRegression` on the binary outcome vs. model probability for that class. Then renormalize so calibrated probabilities sum to 1.

```python
# Source: verified against sklearn 1.8.0 API
from sklearn.isotonic import IsotonicRegression
import numpy as np

class WCIsotonicCalibrator:
    """
    Per-class binary isotonic calibration for 3-outcome predictions.
    Must be fitted on val fold ONLY. Applied to test fold.
    """

    def __init__(self) -> None:
        self._calibrators: list[IsotonicRegression] | None = None

    def fit(self, probs: np.ndarray, outcomes: list[int]) -> "WCIsotonicCalibrator":
        """
        probs:    (N_val, 3) model probabilities
        outcomes: (N_val,)  integer outcome labels (0=W, 1=D, 2=L)
        """
        self._calibrators = []
        for k in range(3):
            binary = (np.array(outcomes) == k).astype(float)
            ir = IsotonicRegression(out_of_bounds="clip", increasing=True)
            ir.fit(probs[:, k], binary)
            self._calibrators.append(ir)
        return self

    def predict(self, probs: np.ndarray) -> np.ndarray:
        """Apply calibration and renormalize to sum to 1."""
        if self._calibrators is None:
            raise RuntimeError("Call fit() before predict()")
        calibrated = np.column_stack([
            self._calibrators[k].predict(probs[:, k]) for k in range(3)
        ])
        row_sums = calibrated.sum(axis=1, keepdims=True)
        row_sums = np.where(row_sums == 0, 1.0, row_sums)
        return calibrated / row_sums
```

**Critical:** `out_of_bounds='clip'` prevents extrapolation errors at test-time when probabilities land outside the training range. [VERIFIED: sklearn 1.8 API signature confirms this parameter]

**Minimum data for IR:** ~16 matches per class gives roughly 5-8 positive outcomes — IR will be monotone-constrained but coarse. Acceptable for a baseline. The fit improves significantly at 48+ samples.

### Pattern 6: A-Grade Metric

```python
def compute_a_grade(y_true_labels: list[int], y_pred_probs: list[list[float]]) -> dict:
    """
    A-grade: fraction of predictions where top-class prob >= 0.65 AND correct.
    Also reports coverage (fraction of games that qualify as A-grade eligible).
    """
    y_true = np.array(y_true_labels)
    y_pred = np.array(y_pred_probs)

    top_class = np.argmax(y_pred, axis=1)
    top_prob = np.max(y_pred, axis=1)

    eligible = top_prob >= 0.65
    correct = top_class == y_true

    n_eligible = int(eligible.sum())
    n_correct = int((eligible & correct).sum())

    return {
        "a_grade_rate": n_correct / n_eligible if n_eligible > 0 else 0.0,
        "a_grade_count": n_correct,
        "a_grade_eligible": n_eligible,
        "a_grade_coverage": float(eligible.mean()),
    }
```

**Expected WC Elo behavior:** The Elo model rarely produces top-class prob >= 0.65 for group-stage games (draws suppress strong-team confidence). Coverage will likely be 10-25% of group stage, higher for knockout.

### Pattern 7: Promotion Gate Design

**Requirement (EVAL-04):** Candidate must beat baseline on both Brier AND log loss. Guard against trivial pass for identical models.

```python
_MIN_DELTA = 0.001  # minimum improvement to be considered non-trivial

def promotion_gate(
    baseline: dict, candidate: dict, min_delta: float = _MIN_DELTA
) -> tuple[bool, str]:
    """
    Compare two model result dicts on Brier + log loss.
    Returns (passes: bool, reason: str).

    Trivial-pass guard: delta must exceed min_delta on BOTH metrics.
    Identical models always return (False, ...) because delta == 0.0 < 0.001.

    baseline / candidate dicts must contain:
        "brier":    float (lower is better)
        "log_loss": float (lower is better)
        "n_samples": int  (for audit trail)
    """
    brier_delta = baseline["brier"] - candidate["brier"]
    ll_delta = baseline["log_loss"] - candidate["log_loss"]

    passes_brier = brier_delta > min_delta
    passes_ll = ll_delta > min_delta

    if passes_brier and passes_ll:
        return True, (
            f"PASS: brier -{brier_delta:.4f}, log_loss -{ll_delta:.4f} "
            f"(n={candidate['n_samples']})"
        )

    reasons = []
    if not passes_brier:
        reasons.append(f"Brier delta={brier_delta:.4f} (need >{min_delta})")
    if not passes_ll:
        reasons.append(f"log_loss delta={ll_delta:.4f} (need >{min_delta})")
    return False, "FAIL: " + "; ".join(reasons)
```

**Verified behavior:** [VERIFIED: runtime]
- Identical models: `(False, "FAIL: Brier delta=0.0000 ...")`
- Sub-threshold improvement: `(False, "FAIL: ...")`
- Real improvement on both: `(True, "PASS: ...")`
- One metric regresses: `(False, "FAIL: ...")`

**Why `min_delta=0.001` is the right floor:** 0.001 Brier improvement on 64 samples is ~one match predicted better. Below this, the difference is within dataset variance noise.

### Pattern 8: Calibration Curve Output (CI-Safe)

Avoid matplotlib — write calibration data as logged text instead:

```python
from sklearn.calibration import calibration_curve

def log_calibration_summary(
    y_true_labels: list[int], y_pred_probs: list[list[float]], class_names: list[str]
) -> None:
    """Log calibration curve data as text (no matplotlib dependency)."""
    y_pred = np.array(y_pred_probs)
    for k, name in enumerate(class_names):
        binary = (np.array(y_true_labels) == k).astype(int)
        probs_k = y_pred[:, k]
        try:
            frac_pos, mean_pred = calibration_curve(binary, probs_k, n_bins=5, strategy="uniform")
            print(f"  Calibration [{name}]:")
            for fp, mp in zip(frac_pos, mean_pred):
                gap = fp - mp
                bar = "+" * int(abs(gap) * 40) if gap > 0 else "-" * int(abs(gap) * 40)
                print(f"    pred={mp:.2f} actual={fp:.2f} gap={gap:+.3f} {bar}")
        except ValueError:
            print(f"  Calibration [{name}]: insufficient data for curve")
```

### Anti-Patterns to Avoid

- **Using current wc_priors.json Elo for historical matches without override:** Nine 2018 teams and seven 2022 teams are missing from the current ratings file. Without `home_elo_override`/`away_elo_override` in the match dict, these get fallback Elo=1500, which skews their match predictions significantly.
- **Fitting isotonic regression on the full 2018+2022 dataset then testing on 2022:** This is post-hoc calibration — data leakage. The EVAL-03 requirement explicitly prohibits it.
- **Using sklearn `brier_score_loss` for multiclass:** That function is binary-only. Use the manual formula: `np.mean(np.sum((y_pred - y_true_onehot)**2, axis=1))`.
- **Setting `min_delta=0.0` in the promotion gate:** Identical models would then trivially pass because `0.0 > 0.0` is False, but rounding in float arithmetic can produce `4.44e-16 > 0.0 = True`. Use `min_delta=0.001`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Isotonic regression | Custom PAVA implementation | `sklearn.isotonic.IsotonicRegression` | sklearn's is battle-tested, handles edge cases, has `out_of_bounds` param |
| Log loss | Manual `-sum(o*log(p))` | `sklearn.metrics.log_loss` | Handles numerical stability (log(0) clipping) correctly |
| Calibration bins | Manual histogram | `sklearn.calibration.calibration_curve` | Handles empty bins, uniform/quantile strategy |
| Accuracy | Manual count | `sklearn.metrics.accuracy_score` | Nothing to gain from custom; just use it |

---

## Elo Override Reference

Teams in WC 2018 and 2022 that are **not** in current `data/wc_priors.json` and require `home_elo_override`/`away_elo_override` fields in the historical match dict:

| Team Name (match records) | Tournament | Approx Historical Elo | Source |
|--------------------------|-----------|----------------------|--------|
| Russia | 2018 | 1685 | [ASSUMED] eloratings.net training data |
| Peru | 2018 | 1810 | [ASSUMED] |
| Denmark | 2018, 2022 | 1835 | [ASSUMED] |
| Iceland | 2018 | 1767 | [ASSUMED] |
| Nigeria | 2018 | 1655 | [ASSUMED] |
| Costa Rica | 2018, 2022 | 1698 | [ASSUMED] |
| Serbia | 2018, 2022 | 1720 | [ASSUMED] |
| Korea Republic | 2018, 2022 | 1770 | [ASSUMED] — alt. name for South Korea |
| Poland | 2018, 2022 | 1780 | [ASSUMED] |
| Wales | 2022 | 1799 | [ASSUMED] |
| Cameroon | 2022 | 1625 | [ASSUMED] |

The South Korea naming issue: `wc_stats.py` maps `"South Korea" -> "Korea Republic"` via `_TEAM_NAME_MAP`. In historical match dicts, use `"Korea Republic"` as the team name and provide an Elo override — it won't be found in `wc_priors.json` (which uses `"South Korea"`). [VERIFIED: runtime check against wc_priors.json]

---

## Common Pitfalls

### Pitfall 1: Elo Fallback at 1500 for Missing Teams
**What goes wrong:** 9 teams from 2018 and 7 from 2022 are not in `wc_priors.json`. Without Elo overrides, WCMatchModel silently uses 1500 for them. Russia vs Saudi Arabia (2018 opener) becomes a coinflip (Russia's actual Elo ~1685 vs Saudi's ~1598) instead of a mild Russia advantage.
**How to avoid:** Embed `home_elo_override` and `away_elo_override` in every historical match record where the team is not in current priors. See the Elo Override Reference table above.
**Warning signs:** Backtest logs show many `WARNING: No Elo rating for '...' — using fallback 1500` lines.

### Pitfall 2: Data Leakage in Isotonic Calibration
**What goes wrong:** Fitting IsotonicRegression on all 128 matches, then evaluating on the 64 2022 matches. The calibrator has already seen 2022 outcomes.
**How to avoid:** Fit on 2018 data only (or group stage subset). Apply to 2022.
**Warning signs:** Calibration error on test set is suspiciously close to zero.

### Pitfall 3: Formula A vs Formula B Confusion for Brier
**What goes wrong:** Using `mean(per-class binary brier)` (Formula B) as the reported metric. This is 1/3 of the standard multiclass Brier (Formula A). Comparison with published WC model benchmarks will be off by a factor of 3.
**How to avoid:** Use `np.mean(np.sum((y_pred - y_true_onehot)**2, axis=1))`.
**Warning signs:** Brier scores < 0.20 for a WC Elo model (typical range for Formula A is 0.45–0.60 on group stage).

### Pitfall 4: WCMatchModel.predict() Mutates Input Dict
**What goes wrong:** `WCMatchModel.predict(game)` mutates the input dict in place AND returns it. If the historical match record dict is the same object used as input, prediction fields accumulate across calls.
**How to avoid:** Always pass a copy: `model.predict(dict(match))`.
**Warning signs:** Test assertions see stale `win_prob` from a prior match.

### Pitfall 5: Knockout-Stage Records with Outcome="D"
**What goes wrong:** WC knockout games can end in draws after 90 minutes, but the WCMatchModel sets `draw_prob=0.0` for knockout stages. If historical records have `outcome="D"` for a 90-min knockout draw, the Brier score for that match is penalized incorrectly.
**How to avoid:** Encode knockout outcomes as the eventual winner (via penalties/AET), not the 90-min result. Include a `"result_after_aet"` field in the dict if you want both. Use only the AET/penalty winner as the ground truth label.
**Warning signs:** Any knockout record with `outcome="D"`.

### Pitfall 6: IR predict() with Out-of-Range Probabilities
**What goes wrong:** At test time, the calibrator sees probabilities outside the range of its training data. Without `out_of_bounds='clip'`, IsotonicRegression raises or extrapolates nonsensically.
**How to avoid:** Always use `IsotonicRegression(out_of_bounds='clip', increasing=True)`.
**Warning signs:** Calibrated probabilities > 1.0 or < 0.0 before normalization.

---

## Runtime State Inventory

Not applicable — this is a greenfield infrastructure phase. No renames, migrations, or live service configuration changes.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (already installed) |
| Config file | `pytest.ini` or `pyproject.toml` (existing) |
| Quick run command | `./venv/Scripts/python.exe -m pytest tests/unit/engines/test_wc_calibration.py -x -q` |
| Full suite command | `./venv/Scripts/python.exe -m pytest -x -q` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EVAL-01 | Expanding-window split returns correct train/val/test partitions | unit | `pytest tests/unit/engines/test_wc_eval.py::test_split_sizes -x` | No — Wave 0 |
| EVAL-01 | Backtest uses frozen Elo ratings via override fields, not live load | unit | `pytest tests/unit/engines/test_wc_eval.py::test_elo_override_used -x` | No — Wave 0 |
| EVAL-02 | Multiclass Brier formula A matches manual calculation | unit | `pytest tests/unit/engines/test_wc_calibration.py::test_multiclass_brier -x` | No — Wave 0 |
| EVAL-02 | Log loss matches sklearn for 3-class input | unit | `pytest tests/unit/engines/test_wc_calibration.py::test_log_loss_multiclass -x` | No — Wave 0 |
| EVAL-02 | A-grade metric: rate = n_correct_eligible / n_eligible | unit | `pytest tests/unit/engines/test_wc_calibration.py::test_a_grade_metric -x` | No — Wave 0 |
| EVAL-03 | IsotonicRegression fit on val fold only, not test | unit | `pytest tests/unit/engines/test_wc_calibration.py::test_calibrator_no_test_leakage -x` | No — Wave 0 |
| EVAL-03 | Calibrated probs sum to 1.0 after renormalization | unit | `pytest tests/unit/engines/test_wc_calibration.py::test_calibrated_probs_sum_to_one -x` | No — Wave 0 |
| EVAL-04 | Identical models fail promotion gate | unit | `pytest tests/unit/engines/test_wc_calibration.py::test_promotion_gate_identical_fail -x` | No — Wave 0 |
| EVAL-04 | Real improvement passes promotion gate | unit | `pytest tests/unit/engines/test_wc_calibration.py::test_promotion_gate_real_improvement -x` | No — Wave 0 |
| EVAL-04 | One-metric regression fails gate | unit | `pytest tests/unit/engines/test_wc_calibration.py::test_promotion_gate_one_metric_fails -x` | No — Wave 0 |

### Wave 0 Gaps

- [ ] `tests/unit/engines/test_wc_calibration.py` — covers EVAL-02, EVAL-03, EVAL-04
- [ ] `tests/unit/engines/test_wc_eval.py` — covers EVAL-01 (split logic and Elo override usage)
- [ ] `data/wc_historical_matches.py` — historical data module (not a test file but required before any test can run)

### Sampling Rate

- Per task commit: `./venv/Scripts/python.exe -m pytest tests/unit/engines/test_wc_calibration.py tests/unit/engines/test_wc_eval.py -x -q`
- Per wave merge: `./venv/Scripts/python.exe -m pytest -x -q`
- Phase gate: Full suite green before `/gsd:verify-work`

---

## Security Domain

This phase writes no network code, handles no user input, and stores no credentials. ASVS categories V2/V3/V4/V6 are not applicable.

| ASVS Category | Applies | Note |
|---------------|---------|------|
| V5 Input Validation | Minimal | Historical dict is static embedded data, not external input. No validation needed beyond Python type annotations. |

No threat patterns applicable to a pure local metrics library.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| scikit-learn | All EVAL requirements | Yes | 1.8.0 | — |
| numpy | Multiclass Brier formula | Yes | (bundled) | — |
| pytest | Test suite | Yes | (existing) | — |
| WCMatchModel | Backtest runner | Yes | in-repo | — |
| wc_priors.json | Elo ratings | Yes | data/wc_priors.json | Elo overrides embedded in historical dict |

**Missing dependencies with no fallback:** None.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Russia's WC 2018 Elo was ~1685 | Elo Override Reference | Backtest predictions for Russia matches skewed; minor effect on overall Brier since Russia was eliminated early |
| A2 | Peru's WC 2018 Elo was ~1810 | Elo Override Reference | Same risk; ~5 matches affected |
| A3 | Denmark's Elo was ~1835 (2018+2022) | Elo Override Reference | ~10 matches affected across both tournaments |
| A4 | Other missing-team Elo values in the table | Elo Override Reference | Minor Brier noise; baseline is approximate anyway |
| A5 | "Korea Republic" is the correct match-dict name (vs "South Korea") | Elo Override Reference | Name mismatch → fallback 1500 Elo used; but wc_stats.py alias only goes StatsBomb→football-data.org direction |
| A6 | Typical WC Elo model Brier is 0.45-0.60 for group stage | Architecture Patterns | Expectation calibration only; doesn't affect code |

**If A1-A5 are wrong:** The baseline Brier/log-loss numbers will be slightly off from what they'd be with exact historical Elos. This is acceptable — the promotion gate compares relative improvement, not absolute numbers. The planner should note that eloratings.net historical ratings can be manually spot-checked for the most-played teams.

---

## Open Questions

1. **Should `data/wc_historical_matches.py` embed all 128 matches at implementation time?**
   - What we know: 2018 had 64 matches, 2022 had 64 matches. All group stage results are public record.
   - What's unclear: Whether the implementation phase has time to manually encode all 128. A partial set (e.g., just 2022 group stage, 48 matches) would still yield a valid baseline.
   - Recommendation: Encode all 48 2022 group stage matches as minimum viable backtest (enough for IR calibration and meaningful Brier). Add 2018 in a follow-up if Phase 26 needs the additional fold.

2. **Is the 2018 knockout/group split for the val fold worth the complexity?**
   - What we know: The EVAL-03 requirement says "fitted on validation fold only." Since WCMatchModel has no trainable weights, any held-out subset of 2018 serves as a valid val fold.
   - What's unclear: Whether the planner wants a formal train/val/test three-way split or just train=2018, test=2022.
   - Recommendation: Implement the simpler two-way split first: calibration fitted on 2018 group stage (48 matches), tested on 2022 (64 matches). This satisfies EVAL-03. Document the three-way option as a future enhancement.

---

## Sources

### Primary (HIGH confidence)
- sklearn 1.8.0 runtime — `IsotonicRegression`, `brier_score_loss`, `log_loss`, `accuracy_score`, `calibration_curve` all verified importable and functional
- `alpha/engines/sports/wc_model.py` — `predict()` API, `home_elo_override` field, mutation-in-place behavior
- `data/wc_priors.json` — 48 teams listed; 9 2018 teams + 7 2022 teams confirmed missing
- `alpha/data/ingestion/wc_stats.py` — confirms no historical match results in cache (xG stats only)

### Secondary (MEDIUM confidence)
- sklearn documentation pattern for per-class binary isotonic calibration for multiclass problems [CITED: standard sklearn calibration pattern]
- Multiclass Brier score formula (sum per sample) [CITED: standard meteorological/forecasting convention, consistent with Murphy 1973]

### Tertiary (LOW confidence / ASSUMED)
- Historical Elo ratings for missing teams (Russia, Peru, Denmark, Iceland, etc.) — [ASSUMED] from training data

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified all imports against sklearn 1.8.0 at runtime
- Architecture: HIGH — built on existing WCMatchModel API hooks verified in source
- Metric formulas: HIGH — verified with runtime calculations
- Historical Elo overrides for missing teams: LOW — assumed values, should be spot-checked against eloratings.net

**Research date:** 2026-06-24
**Valid until:** 2026-09-24 (sklearn API stable; historical match data is immutable)
