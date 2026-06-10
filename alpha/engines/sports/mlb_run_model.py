"""
MLBRunModel — run-distribution simulation model for MLB moneyline/totals.

This is deliberately NOT a direct team-win classifier.  Pipeline:

  1. estimate_expected_runs() for the away team
  2. estimate_expected_runs() for the home team
  3. fit_run_distribution(): Poisson vs Negative Binomial compared by AIC
     on historical per-game run samples (MLB runs are overdispersed, so
     NegBin usually wins — but it is FIT, not assumed)
  4. simulate_game(): >= 10,000 Monte Carlo games, ties resolved by
     inning-by-inning extra innings
  5. derive independent_home_win_prob / independent_away_win_prob /
     expected_total_runs / over_prob / under_prob
  6. market consensus probabilities are computed separately and never
     mixed into the independent estimate
  7. ProbabilityCalibrator is fit on a chronologically LATER holdout
     (callers enforce the time split; see fit() docstring)
  8. evaluate_paper_bet() emits a PAPER bet only when ALL gates pass:
     real odds present, probable pitchers confirmed, required features
     available, calibrated edge above the configured threshold.

No real-money wagering automation exists or may be added.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np

from alpha.engines.sports.mlb_features import (
    LEAGUE,
    MLB_FEATURE_SCHEMA_VERSION,
    REQUIRED_FOR_BET,
    GameContext,
    TeamSideFeatures,
    shrink,
)

logger = logging.getLogger(__name__)

MODEL_VERSION = "mlb-runsim-1.0.0"

DEFAULT_N_SIMS = 10_000
MAX_EXTRA_INNINGS = 20

# Documented, capped adjustment elasticities for expected-runs estimation.
# Modest by design: correctness of the machinery over coefficient tuning.
_WOBA_RUN_ELASTICITY = 1.8      # runs scale ~ (wOBA/league)^1.8
_XERA_CAP = 0.30                # starter quality adj capped at +/-30%
_BULLPEN_FATIGUE_PER_IP3 = 0.012   # +1.2% opp runs per bullpen IP over
_BULLPEN_IP3_NEUTRAL = 9.0         # ~3 IP/day baseline over 3 days
_TEMP_PER_DEG_F = 0.0035        # ~+0.35% runs per degree F above 70
_TEMP_NEUTRAL_F = 70.0
_WIND_PER_MPH_OUT = 0.004       # +0.4% runs per mph blowing out
_WEATHER_CAP = 0.12             # total weather adj capped at +/-12%
_HIGH_LEV_UNAVAILABLE_PEN = 0.03   # +3% opp runs late if high-lev arms down
_CLOSER_UNAVAILABLE_PEN = 0.02


# ---------------------------------------------------------------------------
# 1-2. Expected runs
# ---------------------------------------------------------------------------

def estimate_expected_runs(
    batting: TeamSideFeatures,
    opposing: TeamSideFeatures,
    context: GameContext | None = None,
) -> tuple[float, list[str]]:
    """
    Expected runs for ``batting`` against ``opposing``'s staff.

    Multiplicative components on a shrunk base rate:
      base        team runs/game shrunk toward league
      lineup      shrunk lineup wOBA vs the starter's handedness
      starter     starter xERA vs league, weighted by expected innings
      bullpen     bullpen xERA + recent-workload fatigue for the rest
      park        park_factor_runs (1.0 = neutral)
      weather     temperature + wind, suppressed when roof closed/dome

    Missing optional inputs contribute a neutral factor and are returned
    in the missing list — they are never invented.  Callers gate bets on
    REQUIRED_FOR_BET separately.
    """
    missing: list[str] = []

    # Base offense: team runs/game, shrunk toward league baseline.
    if batting.runs_per_game is not None:
        base = shrink(batting.runs_per_game, 81, LEAGUE["runs_per_game"], 40)
    else:
        base = LEAGUE["runs_per_game"]
        missing.append("runs_per_game")

    # Lineup vs starter handedness (callers pass already-shrunk splits).
    lineup_factor = 1.0
    woba = None
    if opposing.starter_throws == "L":
        woba = batting.lineup_woba_vs_lhp
        if woba is None:
            missing.append("lineup_woba_vs_lhp")
    else:
        woba = batting.lineup_woba_vs_rhp
        if woba is None:
            missing.append("lineup_woba_vs_rhp")
    if woba is not None and LEAGUE["woba"] > 0:
        lineup_factor = (woba / LEAGUE["woba"]) ** _WOBA_RUN_ELASTICITY

    # Starter quality over expected innings; bullpen covers the rest.
    starter_share = (
        (opposing.starter_expected_innings or LEAGUE["starter_innings"]) / 9.0
    )
    starter_share = min(max(starter_share, 0.30), 0.85)

    if opposing.starter_xera is not None:
        raw = opposing.starter_xera / LEAGUE["xera"]
        starter_factor = min(max(raw, 1 - _XERA_CAP), 1 + _XERA_CAP)
    else:
        starter_factor = 1.0
        missing.append("starter_xera")

    if opposing.bullpen_xera is not None:
        raw = opposing.bullpen_xera / LEAGUE["era"]
        bullpen_factor = min(max(raw, 1 - _XERA_CAP), 1 + _XERA_CAP)
    else:
        bullpen_factor = 1.0
        missing.append("bullpen_xera")

    # Bullpen fatigue: recent workload inflates the bullpen share.
    if opposing.bullpen_ip_last3 is not None:
        overload = max(0.0, opposing.bullpen_ip_last3 - _BULLPEN_IP3_NEUTRAL)
        bullpen_factor *= 1.0 + min(0.10, overload * _BULLPEN_FATIGUE_PER_IP3)
    else:
        missing.append("bullpen_ip_last3")
    if opposing.high_leverage_available is False:
        bullpen_factor *= 1.0 + _HIGH_LEV_UNAVAILABLE_PEN
    if opposing.closer_available is False:
        bullpen_factor *= 1.0 + _CLOSER_UNAVAILABLE_PEN

    pitching_factor = starter_share * starter_factor + (1 - starter_share) * bullpen_factor

    # Park & weather (game-level).
    park_factor = 1.0
    weather_factor = 1.0
    if context is not None:
        if context.park_factor_runs is not None:
            park_factor = context.park_factor_runs
        else:
            missing.append("park_factor_runs")
        roof_open = context.roof_status not in ("closed", "dome")
        if roof_open:
            adj = 0.0
            if context.temperature_f is not None:
                adj += (context.temperature_f - _TEMP_NEUTRAL_F) * _TEMP_PER_DEG_F
            else:
                missing.append("temperature_f")
            if context.wind_mph_out is not None:
                adj += context.wind_mph_out * _WIND_PER_MPH_OUT
            else:
                missing.append("wind_mph_out")
            weather_factor = 1.0 + min(max(adj, -_WEATHER_CAP), _WEATHER_CAP)

    mu = base * lineup_factor * pitching_factor * park_factor * weather_factor
    return max(0.5, mu), missing


# ---------------------------------------------------------------------------
# 3. Run distribution: Poisson vs Negative Binomial
# ---------------------------------------------------------------------------

@dataclass
class RunDistribution:
    """Fitted per-game run distribution for one team."""
    family: str                  # 'poisson' | 'negbin'
    mu: float
    alpha: float = 0.0           # NegBin dispersion: var = mu + alpha*mu^2
    loglik_poisson: float = 0.0
    loglik_negbin: float = 0.0
    aic_poisson: float = 0.0
    aic_negbin: float = 0.0

    def with_mean(self, mu: float) -> "RunDistribution":
        """Same fitted family/dispersion, re-centered on a new mean."""
        return RunDistribution(family=self.family, mu=mu, alpha=self.alpha,
                               loglik_poisson=self.loglik_poisson,
                               loglik_negbin=self.loglik_negbin,
                               aic_poisson=self.aic_poisson,
                               aic_negbin=self.aic_negbin)

    def sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        if self.family == "negbin" and self.alpha > 0:
            r = 1.0 / self.alpha
            p = r / (r + self.mu)
            return rng.negative_binomial(r, p, size=n)
        return rng.poisson(self.mu, size=n)


def fit_run_distribution(samples: list[int] | np.ndarray) -> RunDistribution:
    """
    Fit Poisson and Negative Binomial to historical per-game run totals
    and keep the family with the lower AIC.

    NegBin dispersion alpha is estimated by method of moments
    (var = mu + alpha*mu^2); when the sample is under/equi-dispersed the
    fit degenerates to Poisson.
    """
    x = np.asarray(samples, dtype=float)
    if len(x) < 20:
        raise ValueError(f"Need >= 20 run samples to fit a distribution; got {len(x)}")
    mu = float(x.mean())
    var = float(x.var(ddof=1))

    from scipy.stats import nbinom, poisson

    ll_pois = float(poisson.logpmf(x, mu).sum())
    aic_pois = 2 * 1 - 2 * ll_pois

    alpha = max(0.0, (var - mu) / (mu ** 2)) if mu > 0 else 0.0
    if alpha <= 1e-9:
        return RunDistribution(family="poisson", mu=mu, alpha=0.0,
                               loglik_poisson=ll_pois, loglik_negbin=ll_pois,
                               aic_poisson=aic_pois, aic_negbin=aic_pois + 2)

    r = 1.0 / alpha
    p = r / (r + mu)
    ll_nb = float(nbinom.logpmf(x, r, p).sum())
    aic_nb = 2 * 2 - 2 * ll_nb

    family = "negbin" if aic_nb < aic_pois else "poisson"
    return RunDistribution(family=family, mu=mu,
                           alpha=alpha if family == "negbin" else 0.0,
                           loglik_poisson=ll_pois, loglik_negbin=ll_nb,
                           aic_poisson=aic_pois, aic_negbin=aic_nb)


# ---------------------------------------------------------------------------
# 4-5. Monte Carlo game simulation
# ---------------------------------------------------------------------------

def simulate_game(
    home_dist: RunDistribution,
    away_dist: RunDistribution,
    n_sims: int = DEFAULT_N_SIMS,
    total_line: float | None = None,
    seed: int | None = 42,
) -> dict:
    """
    Simulate n_sims (>= 10,000 recommended) full games.

    Regulation totals are drawn from each team's fitted distribution;
    tied games are resolved inning-by-inning (per-inning mean = mu/9)
    like extra innings, so there are no ties in the output.

    Returns independent win probabilities, expected total runs, and
    over/under/push probabilities for ``total_line`` when provided.
    """
    if n_sims < 1000:
        raise ValueError("n_sims must be >= 1000 (10,000+ recommended)")
    rng = np.random.default_rng(seed)

    home = home_dist.sample(n_sims, rng).astype(np.int64)
    away = away_dist.sample(n_sims, rng).astype(np.int64)

    # Extra innings for ties: one inning at a time for both teams.
    tied = np.flatnonzero(home == away)
    inning_mu_home = home_dist.mu / 9.0
    inning_mu_away = away_dist.mu / 9.0
    for _ in range(MAX_EXTRA_INNINGS):
        if tied.size == 0:
            break
        home[tied] += rng.poisson(inning_mu_home, size=tied.size)
        away[tied] += rng.poisson(inning_mu_away, size=tied.size)
        tied = tied[home[tied] == away[tied]]
    if tied.size:  # pathological leftovers: split by run-rate ratio
        p_home = inning_mu_home / max(1e-9, inning_mu_home + inning_mu_away)
        winners = rng.random(tied.size) < p_home
        home[tied] += winners.astype(np.int64)
        away[tied] += (~winners).astype(np.int64)

    totals = home + away
    home_win = float((home > away).mean())

    out = {
        "independent_home_win_prob": round(home_win, 6),
        "independent_away_win_prob": round(1.0 - home_win, 6),
        "expected_total_runs": round(float(totals.mean()), 4),
        "expected_home_runs": round(float(home.mean()), 4),
        "expected_away_runs": round(float(away.mean()), 4),
        "n_sims": n_sims,
        "distribution_family": (home_dist.family, away_dist.family),
        "over_prob": None,
        "under_prob": None,
        "push_prob": None,
    }
    if total_line is not None:
        over = float((totals > total_line).mean())
        under = float((totals < total_line).mean())
        out["over_prob"] = round(over, 6)
        out["under_prob"] = round(under, 6)
        out["push_prob"] = round(1.0 - over - under, 6)
    return out


# ---------------------------------------------------------------------------
# 7. Calibration (fit on a chronologically LATER holdout)
# ---------------------------------------------------------------------------

class ProbabilityCalibrator:
    """
    Logistic (Platt-style) calibration on the logit scale:

        calibrated = sigmoid(a * logit(p) + b)

    Fit on a holdout that is chronologically AFTER the data used to build
    the simulation inputs, and disjoint from any model-training rows.
    Identity (a=1, b=0) until fitted; ``fitted`` says whether it may be
    used for bet gating.
    """

    def __init__(self) -> None:
        self.a: float = 1.0
        self.b: float = 0.0
        self.fitted: bool = False
        self.n_fit: int = 0

    @staticmethod
    def _logit(p: np.ndarray) -> np.ndarray:
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p))

    def fit(self, probs: list[float], outcomes: list[int],
            n_iter: int = 500, lr: float = 0.5) -> None:
        """
        Newton-damped gradient fit of (a, b) by maximum likelihood.
        ``probs`` are raw simulation probabilities; ``outcomes`` the
        realized 0/1 results from the SAME (held-out, later) games.
        """
        if len(probs) != len(outcomes) or len(probs) < 30:
            raise ValueError("Need >= 30 aligned holdout samples to calibrate")
        x = self._logit(np.asarray(probs, dtype=float))
        y = np.asarray(outcomes, dtype=float)
        a, b = 1.0, 0.0
        n = len(x)
        for _ in range(n_iter):
            z = a * x + b
            p = 1.0 / (1.0 + np.exp(-z))
            grad_a = float(((p - y) * x).mean())
            grad_b = float((p - y).mean())
            a -= lr * grad_a
            b -= lr * grad_b
        self.a, self.b = a, b
        self.fitted = True
        self.n_fit = n

    def transform(self, p: float) -> float:
        z = self.a * float(self._logit(np.array([p]))[0]) + self.b
        return float(1.0 / (1.0 + math.exp(-z)))


# ---------------------------------------------------------------------------
# 6 + 8. Full evaluation with fail-closed paper-bet gating
# ---------------------------------------------------------------------------

def _american_to_implied(odds: float) -> float:
    odds = float(odds)
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _remove_vig_pair(home_odds: float, away_odds: float) -> tuple[float, float]:
    h, a = _american_to_implied(home_odds), _american_to_implied(away_odds)
    total = h + a
    if total <= 0:
        return 0.5, 0.5
    return h / total, a / total


def chronological_calibration_split(
    dates: list, calibration_frac: float = 0.30
) -> tuple[list[int], list[int]]:
    """
    Split indices so the calibrator is fit on the chronologically LATER
    portion (and the earlier portion is used for everything else).
    Returns (earlier_idx, calibration_idx) in time order.
    """
    if not 0.0 < calibration_frac < 1.0:
        raise ValueError("calibration_frac must be in (0, 1)")
    order = sorted(range(len(dates)), key=lambda i: dates[i])
    cut = int(len(order) * (1.0 - calibration_frac))
    if cut == 0 or cut == len(order):
        raise ValueError("Split produced an empty partition — need more samples")
    return order[:cut], order[cut:]


class MLBRunModel:
    """
    Orchestrates expected runs -> simulation -> calibration -> gated
    paper-bet evaluation.  Market consensus stays a separate output.
    """

    def __init__(
        self,
        home_dist_template: RunDistribution | None = None,
        away_dist_template: RunDistribution | None = None,
        calibrator: ProbabilityCalibrator | None = None,
        min_edge: float = 0.03,
        n_sims: int = DEFAULT_N_SIMS,
    ) -> None:
        # Templates carry the FITTED family/dispersion (from
        # fit_run_distribution on historical runs); means are replaced
        # per game.  Poisson(league) default keeps predict() usable, but
        # bets additionally require a fitted calibrator.
        self._home_template = home_dist_template or RunDistribution(
            family="poisson", mu=LEAGUE["runs_per_game"])
        self._away_template = away_dist_template or RunDistribution(
            family="poisson", mu=LEAGUE["runs_per_game"])
        self.calibrator = calibrator or ProbabilityCalibrator()
        self.min_edge = min_edge
        self.n_sims = n_sims

    # -- prediction ----------------------------------------------------

    def predict(
        self,
        home: TeamSideFeatures,
        away: TeamSideFeatures,
        context: GameContext | None = None,
        total_line: float | None = None,
        seed: int | None = 42,
    ) -> dict:
        """
        Independent simulation probabilities + separate market consensus.
        Never blends the two.
        """
        home_mu, miss_h = estimate_expected_runs(home, away, context)
        away_mu, miss_a = estimate_expected_runs(away, home, context)

        sim = simulate_game(
            self._home_template.with_mean(home_mu),
            self._away_template.with_mean(away_mu),
            n_sims=self.n_sims,
            total_line=total_line,
            seed=seed,
        )

        raw = sim["independent_home_win_prob"]
        calibrated = self.calibrator.transform(raw) if self.calibrator.fitted else None

        return {
            **sim,
            "expected_home_mu": round(home_mu, 4),
            "expected_away_mu": round(away_mu, 4),
            "final_calibrated_home_prob": (
                round(calibrated, 6) if calibrated is not None else None),
            "calibrated": self.calibrator.fitted,
            "market_consensus_home_prob": (
                context.consensus_no_vig_prob if context else None),
            "missing_features": sorted(set(
                [f"home.{m}" for m in miss_h] + [f"away.{m}" for m in miss_a])),
            "model_version": MODEL_VERSION,
            "feature_schema_version": MLB_FEATURE_SCHEMA_VERSION,
            "source": "run_simulation",
        }

    # -- gated paper-bet evaluation -------------------------------------

    def evaluate_paper_bet(
        self,
        game: dict,
        home: TeamSideFeatures,
        away: TeamSideFeatures,
        context: GameContext | None = None,
        total_line: float | None = None,
    ) -> dict:
        """
        Evaluate a PAPER moneyline bet.  Emits a bet decision only when
        every gate passes; otherwise returns bet_side="no_bet" with the
        explicit failed-gate reasons.  Never places real wagers.

        Gates (all required):
          - real odds present (game["has_real_odds"] is True and an odds
            pair exists — StatsAPI placeholder -110s never count)
          - probable pitchers confirmed on BOTH sides
          - REQUIRED_FOR_BET features available on both sides
          - a FITTED calibrator (edge must be calibrated)
          - calibrated edge vs no-vig market > min_edge
        """
        reasons: list[str] = []

        has_real_odds = bool(game.get("has_real_odds")) and \
            game.get("home_odds") is not None and game.get("away_odds") is not None
        if not has_real_odds:
            reasons.append("no_real_odds")
        if not home.pitcher_confirmed:
            reasons.append("home_pitcher_unconfirmed")
        if not away.pitcher_confirmed:
            reasons.append("away_pitcher_unconfirmed")
        for side_name, side in (("home", home), ("away", away)):
            miss = side.missing(REQUIRED_FOR_BET)
            reasons.extend(f"missing:{side_name}.{m}" for m in miss
                           if m != "pitcher_confirmed")
        if not self.calibrator.fitted:
            reasons.append("calibrator_not_fitted")

        if reasons:
            logger.info("MLB paper bet gated off: %s", reasons)
            return {"bet_side": "no_bet", "reasons": reasons,
                    "model_version": MODEL_VERSION}

        prediction = self.predict(home, away, context, total_line=total_line)
        cal_home = prediction["final_calibrated_home_prob"]
        cal_away = 1.0 - cal_home

        home_odds, away_odds = game["home_odds"], game["away_odds"]
        fair_home, fair_away = _remove_vig_pair(home_odds, away_odds)

        edge_home = cal_home - fair_home
        edge_away = cal_away - fair_away

        side, edge, odds, prob = ("home", edge_home, home_odds, cal_home) \
            if edge_home >= edge_away else ("away", edge_away, away_odds, cal_away)

        if edge <= self.min_edge:
            return {"bet_side": "no_bet",
                    "reasons": [f"edge_below_threshold({edge:.4f}<={self.min_edge})"],
                    "prediction": prediction, "model_version": MODEL_VERSION}

        return {
            "bet_side": side,
            "team": game.get(f"{side}_team", ""),
            "offered_odds": odds,
            "calibrated_prob": round(prob, 6),
            "market_no_vig_prob": round(fair_home if side == "home" else fair_away, 6),
            "edge": round(edge, 6),
            "prediction": prediction,
            "paper_only": True,
            "model_version": MODEL_VERSION,
        }
