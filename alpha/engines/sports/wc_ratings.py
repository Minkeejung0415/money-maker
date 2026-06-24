"""
WCTeamRatings — hybrid team ratings for WC model evaluation.

Builds sequential Elo states from WC_HISTORICAL, seeds xG EWMA
from .wc_cache/wc_stats.pkl, and exposes composite Elo for injection
into WCMatchModel game dicts.

No live data. No modification to wc_model.py or wc_scanner.py.

Design:
    - Sequential Elo updated match-by-match through 2018 and 2022 tournaments
    - xG EWMA seeded from wc_stats.pkl per-team averages (avg_xG, defense_score)
    - Composite Elo = sequential_elo + xG_adj + FIFA_adj + host_adj + conf_adj
    - Used for backtesting via WCHybridModel; scanner is unchanged
"""
from __future__ import annotations

import logging
import math
import pickle
from pathlib import Path

from data.wc_historical_matches import WC_HISTORICAL
from data.wc_fifa_rankings import (
    WC_2026_HOSTS,
    get_confederation,
    get_fifa_rank,
)
from alpha.data.ingestion.wc_elo import load_wc_elo_ratings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage sort order for chronological replay
# ---------------------------------------------------------------------------

_STAGE_ORDER: dict[str, int] = {
    "GROUP_STAGE": 0,
    "LAST_16": 1,
    "QUARTER_FINALS": 2,
    "SEMI_FINALS": 3,
    "THIRD_PLACE": 4,
    "FINAL": 5,
}

_WC_CACHE_PATH = Path("data/.wc_cache/wc_stats.pkl")

# Global xG defaults when stats cache is unavailable
_DEFAULT_XG_ATTACK: float = 1.2
_DEFAULT_XG_DEFENSE: float = 1.2

# Elo update K factor (WC literature standard)
_DEFAULT_K: float = 30.0

# Elo fallback for teams with no prior
_ELO_FALLBACK: int = 1500


def _ewma_alpha(half_life: int) -> float:
    """Compute EWMA smoothing factor from half-life (in matches)."""
    return 1.0 - 0.5 ** (1.0 / half_life)


class WCTeamRatings:
    """
    Hybrid team ratings combining sequential Elo, xG EWMA, FIFA SUM,
    host flag, and confederation interaction.

    Built by replaying WC_HISTORICAL in chronological order.
    No live data — pure computation from embedded historical data.

    Parameters
    ----------
    k_factor : float
        Elo K factor for historical match updates. Default 30 (WC standard).
    xg_half_life : int
        EWMA half-life in matches for xG attack/defense states. Default 5.
    """

    def __init__(
        self,
        k_factor: float = _DEFAULT_K,
        xg_half_life: int = 5,
    ) -> None:
        self._k = k_factor
        self._alpha = _ewma_alpha(xg_half_life)

        # Step 1: Load wc_priors.json as initial Elo dict
        self._elo: dict[str, int] = dict(load_wc_elo_ratings())

        # Step 2: Seed xG states from .wc_cache/wc_stats.pkl
        self._xg_attack: dict[str, float] = {}
        self._xg_defense: dict[str, float] = {}
        self._load_xg_seeds()

        # Step 3: Replay WC_HISTORICAL chronologically
        self._replay_history()

        logger.info(
            "WCTeamRatings initialized: %d Elo entries, %d xG entries",
            len(self._elo),
            len(self._xg_attack),
        )

    def _load_xg_seeds(self) -> None:
        """
        Seed xG EWMA states from .wc_cache/wc_stats.pkl.

        Falls back to global defaults (1.2/1.2) if file is missing.
        The pickle contains: {team: {avg_xG, defense_score, avg_goals, ...}}
        """
        if not _WC_CACHE_PATH.exists():
            logger.warning(
                "wc_stats.pkl not found at %s — using xG defaults (%.1f/%.1f)",
                _WC_CACHE_PATH,
                _DEFAULT_XG_ATTACK,
                _DEFAULT_XG_DEFENSE,
            )
            return

        try:
            with open(_WC_CACHE_PATH, "rb") as f:
                stats: dict[str, dict] = pickle.load(f)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load wc_stats.pkl: %s — using xG defaults", exc)
            return

        for team, values in stats.items():
            if not isinstance(values, dict):
                # Skip metadata keys (e.g. 'built_at' string entries)
                continue
            self._xg_attack[team] = float(values.get("avg_xG", _DEFAULT_XG_ATTACK))
            self._xg_defense[team] = float(values.get("defense_score", _DEFAULT_XG_DEFENSE))

        logger.debug("Seeded xG states for %d teams from wc_stats.pkl", len(self._xg_attack))

    def _get_elo(self, team: str, match: dict, home: bool) -> int:
        """
        Return Elo for team from self._elo.

        If the match dict has a hard override (e.g. for 2018 teams not in
        wc_priors), use that override ONLY as the starting point if the team
        is not yet tracked in self._elo (it should be after first match).
        """
        if team in self._elo:
            return self._elo[team]
        # Use override from historical match record if present
        override_key = "home_elo_override" if home else "away_elo_override"
        if match.get(override_key) is not None:
            override = int(match[override_key])
            self._elo[team] = override
            return override
        # Final fallback
        self._elo[team] = _ELO_FALLBACK
        return _ELO_FALLBACK

    def _get_xg(self, team: str) -> tuple[float, float]:
        """Return (xg_attack, xg_defense) for team, using defaults if missing."""
        return (
            self._xg_attack.get(team, _DEFAULT_XG_ATTACK),
            self._xg_defense.get(team, _DEFAULT_XG_DEFENSE),
        )

    def _replay_history(self) -> None:
        """
        Replay WC_HISTORICAL sorted chronologically, updating Elo and xG EWMA.

        Sort key: (year, stage_order) ascending.
        """
        sorted_matches = sorted(
            WC_HISTORICAL,
            key=lambda m: (m["year"], _STAGE_ORDER.get(m["stage"], 99)),
        )

        for match in sorted_matches:
            home = match["home_team"]
            away = match["away_team"]
            outcome = match["outcome"]  # "W", "D", "L"
            home_score = match.get("home_score", 1)
            away_score = match.get("away_score", 1)

            # Outcome score (home perspective)
            if outcome == "W":
                score_home = 1.0
                score_away = 0.0
            elif outcome == "D":
                score_home = 0.5
                score_away = 0.5
            else:  # "L"
                score_home = 0.0
                score_away = 1.0

            # Current Elo before update
            elo_h = self._get_elo(home, match, home=True)
            elo_a = self._get_elo(away, match, home=False)

            # Elo expected scores (Bradley-Terry)
            e_home = 1.0 / (1.0 + 10.0 ** (-(elo_h - elo_a) / 400.0))
            e_away = 1.0 - e_home

            # Elo update
            self._elo[home] = int(round(elo_h + self._k * (score_home - e_home)))
            self._elo[away] = int(round(elo_a + self._k * (score_away - e_away)))

            # xG EWMA update (use goals as proxy for xG)
            # home attack / away defense
            xg_atk_h, xg_def_h = self._get_xg(home)
            xg_atk_a, xg_def_a = self._get_xg(away)

            alpha = self._alpha
            self._xg_attack[home] = alpha * home_score + (1.0 - alpha) * xg_atk_h
            self._xg_defense[home] = alpha * away_score + (1.0 - alpha) * xg_def_h
            self._xg_attack[away] = alpha * away_score + (1.0 - alpha) * xg_atk_a
            self._xg_defense[away] = alpha * home_score + (1.0 - alpha) * xg_def_a

    def get_features(self, home_team: str, away_team: str) -> dict:
        """
        Return hybrid feature dict for a matchup.

        Parameters
        ----------
        home_team : str
            Home team name (as used in WC match dicts).
        away_team : str
            Away team name.

        Returns
        -------
        dict with keys:
            elo                       (int)   — home sequential Elo after replay
            elo_away                  (int)   — away sequential Elo after replay
            xg_attack                 (float) — home xG attack EWMA
            xg_defense                (float) — home xG defense EWMA (lower=better defense)
            xg_attack_away            (float)
            xg_defense_away           (float)
            fifa_sum                  (int)   — home_rank + away_rank (lower=better matchup)
            host_flag                 (int)   — 1 if home_team is a WC 2026 host
            confederation_interaction (int)   — 1 if teams from different confederations
            composite_home_elo        (float) — effective Elo for hybrid model injection
            composite_away_elo        (float)
        """
        # Elo values after historical replay
        elo_home = self._elo.get(home_team, _ELO_FALLBACK)
        elo_away = self._elo.get(away_team, _ELO_FALLBACK)

        # xG states
        xg_atk_h, xg_def_h = self._get_xg(home_team)
        xg_atk_a, xg_def_a = self._get_xg(away_team)

        # FIFA ranking feature
        home_rank = get_fifa_rank(home_team)
        away_rank = get_fifa_rank(away_team)
        fifa_sum = home_rank + away_rank

        # Host flag
        host_flag = 1 if home_team in WC_2026_HOSTS else 0

        # Confederation interaction (1 = cross-confederation)
        home_conf = get_confederation(home_team)
        away_conf = get_confederation(away_team)
        confederation_interaction = 0 if home_conf == away_conf else 1

        # Composite Elo calculation
        composite_home_elo = self._composite_elo(
            elo_home=elo_home,
            elo_away=elo_away,
            xg_atk_h=xg_atk_h,
            xg_def_h=xg_def_h,
            xg_atk_a=xg_atk_a,
            xg_def_a=xg_def_a,
            home_rank=home_rank,
            away_rank=away_rank,
            host_flag=host_flag,
            home_conf=home_conf,
            away_conf=away_conf,
        )

        return {
            "elo": elo_home,
            "elo_away": elo_away,
            "xg_attack": xg_atk_h,
            "xg_defense": xg_def_h,
            "xg_attack_away": xg_atk_a,
            "xg_defense_away": xg_def_a,
            "fifa_sum": fifa_sum,
            "host_flag": host_flag,
            "confederation_interaction": confederation_interaction,
            "composite_home_elo": composite_home_elo,
            "composite_away_elo": float(elo_away),
        }

    @staticmethod
    def _composite_elo(
        elo_home: int,
        elo_away: int,
        xg_atk_h: float,
        xg_def_h: float,
        xg_atk_a: float,
        xg_def_a: float,
        home_rank: int,
        away_rank: int,
        host_flag: int,
        home_conf: str,
        away_conf: str,
    ) -> float:
        """
        Compute composite home Elo from sequential Elo + feature adjustments.

        Formula:
            composite = sequential_elo_home + xg_adj + fifa_adj + host_adj + conf_adj

        Adjustments (all from home-team perspective):
            xg_adj   : 200 * log10((atk_h/def_a) / (atk_a/def_h)), capped ±40
            fifa_adj : -0.05 * (home_rank - away_rank), capped ±20
            host_adj : +50 if home_team is WC 2026 host, else 0
            conf_adj : +10 if same confederation, -10 if cross-confederation
        """
        # xG ratio adjustment (±40 cap)
        home_xg_ratio = xg_atk_h / max(xg_def_a, 0.1)
        away_xg_ratio = xg_atk_a / max(xg_def_h, 0.1)

        # Guard against log(0) — ratio of ratios must be positive
        ratio_of_ratios = home_xg_ratio / max(away_xg_ratio, 0.01)
        xg_adj = max(-40.0, min(40.0, 200.0 * math.log10(ratio_of_ratios)))

        # FIFA ranking adjustment (±20 cap)
        fifa_adj = max(-20.0, min(20.0, -0.05 * (home_rank - away_rank)))

        # Host flag adjustment
        host_adj = 50.0 if host_flag == 1 else 0.0

        # Confederation adjustment
        conf_adj = 10.0 if home_conf == away_conf else -10.0

        return float(elo_home) + xg_adj + fifa_adj + host_adj + conf_adj
