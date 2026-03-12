"""
NBA Contextual Evaluators — position filter, shared minutes, paint deterrence,
foul trouble risk, advanced opponent stats, and the unified PropContextEvaluator.

All nba_api calls route through NBAStatsCache for rate-limiting and 6h TTL caching.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_STAT_CATEGORY_MAP: dict[str, str] = {
    "player_points": "pts",
    "player_rebounds": "reb",
    "player_assists": "ast",
    "player_threes": "pts",
    "player_steals": "stl",
    "player_blocks": "blk",
}

_GUARD_POSITIONS = {"Guard", "G", "G-F", "Point Guard", "Shooting Guard", "PG", "SG"}
_SMALL_FORWARD_POSITIONS = {"Forward", "F", "F-G", "Small Forward", "SF"}
_REBOUND_SUPPRESSED_POSITIONS = _GUARD_POSITIONS | _SMALL_FORWARD_POSITIONS

_REBOUND_THRESHOLD = 5.0

_ELITE_PAINT_PROTECTOR_BLK_RATE = 3.5   # blocks per 36 min
_ELITE_PAINT_PROTECTOR_RIM_DFG = 0.56   # rim FG% allowed
_RIM_DEPENDENT_THRESHOLD = 0.50          # >50% shots at rim
_PAINT_DETERRENCE_MIN_SHARED_MIN = 15.0
_PAINT_DETERRENCE_MIN_DISCOUNT = 0.08
_PAINT_DETERRENCE_MAX_DISCOUNT = 0.18
_THREE_POINT_SHOOTER_THRESHOLD = 0.35

_FOUL_PRONE_THRESHOLD = 3.5   # PF per 36 min
_ELITE_FT_DRAWER_RATE = 0.35  # FTA / FGA


@dataclass
class ContextFlags:
    """Accumulated adjustment flags applied to a prop."""
    position_filtered: bool = False
    shared_minutes_weight: float = 1.0
    paint_deterrence_pct: float = 0.0
    foul_trouble_risk: str = "NONE"
    foul_trouble_boost: float = 0.0
    pace_adjustment: float = 0.0
    def_rating_adjustment: float = 0.0
    opp_paint_pts_adjustment: float = 0.0
    opp_fta_rate_adjustment: float = 0.0
    on_off_adjustment: float = 0.0

    @property
    def total_adjustment(self) -> float:
        return (
            -self.paint_deterrence_pct
            + self.foul_trouble_boost
            + self.pace_adjustment
            + self.def_rating_adjustment
            + self.opp_paint_pts_adjustment
            + self.opp_fta_rate_adjustment
            + self.on_off_adjustment
        )

    def as_dict(self) -> dict:
        return {
            "position_filtered": self.position_filtered,
            "shared_minutes_weight": round(self.shared_minutes_weight, 3),
            "paint_deterrence_pct": round(self.paint_deterrence_pct, 3),
            "foul_trouble_risk": self.foul_trouble_risk,
            "foul_trouble_boost": round(self.foul_trouble_boost, 3),
            "pace_adjustment": round(self.pace_adjustment, 3),
            "def_rating_adjustment": round(self.def_rating_adjustment, 3),
            "total_adjustment": round(self.total_adjustment, 3),
        }


# ---------------------------------------------------------------------------
# Position-Based Rebound Filter
# ---------------------------------------------------------------------------

class PositionFilter:
    """
    Suppress rebound props for guards and small forwards unless they
    average above 5.0 RPG historically.
    """

    def __init__(self, cache=None, season: str = "2024-25"):
        self._cache = cache
        self._season = season
        self._player_info: dict[str, dict] = {}
        self._player_stats: dict[str, dict] | None = None

    def should_filter(self, player_name: str, market: str) -> bool:
        """Return True if this prop should be suppressed."""
        if market != "player_rebounds":
            return False

        info = self._get_player_info(player_name)
        if not info:
            return False

        position = info.get("position", "")
        is_guard_or_sf = any(
            pos_token.strip() in _REBOUND_SUPPRESSED_POSITIONS
            for pos_token in position.split("-")
        ) or position in _REBOUND_SUPPRESSED_POSITIONS

        if not is_guard_or_sf:
            return False

        avg_reb = self._get_avg_rebounds(player_name)
        if avg_reb is None or avg_reb >= _REBOUND_THRESHOLD:
            return False

        logger.debug(
            "Position filter: suppressing %s rebound prop (pos=%s, avg_reb=%.1f)",
            player_name, position, avg_reb,
        )
        return True

    def _get_player_info(self, player_name: str) -> dict:
        if player_name in self._player_info:
            return self._player_info[player_name]

        if self._cache is None:
            return {}

        player_id = self._cache.resolve_player_id(player_name)
        if player_id is None:
            return {}

        try:
            info = self._cache.fetch_player_info(player_id)
            self._player_info[player_name] = info
            return info
        except Exception as exc:
            logger.debug("Position lookup failed for %s: %s", player_name, exc)
            return {}

    def _get_avg_rebounds(self, player_name: str) -> float | None:
        if self._player_stats is None:
            self._load_player_stats()

        stats = (self._player_stats or {}).get(player_name)
        if stats:
            return stats.get("REB", 0.0)
        return None

    def _load_player_stats(self) -> None:
        if self._cache is None:
            self._player_stats = {}
            return
        try:
            rows = self._cache.fetch_league_dash_player_stats(
                season=self._season, per_mode="PerGame"
            )
            self._player_stats = {}
            for row in rows:
                name = row.get("PLAYER_NAME", "")
                if name:
                    self._player_stats[name] = row
        except Exception as exc:
            logger.debug("Player stats load failed: %s", exc)
            self._player_stats = {}


# ---------------------------------------------------------------------------
# Shared Court Time / Rotation Filter
# ---------------------------------------------------------------------------

class SharedMinutesFilter:
    """
    Calculate shared court time weight (0.0–1.0) between a player and their
    likely defensive matchup. Reduces matchup-based adjustments for bench
    vs starter situations.
    """

    def __init__(self, cache=None, season: str = "2024-25"):
        self._cache = cache
        self._season = season
        self._matchup_data: dict[str, float] | None = None

    def get_shared_minutes_weight(
        self, player_name: str, opponent_defender: str | None = None
    ) -> float:
        """
        Return weight 0.0–1.0 based on shared court time.
        1.0 = full starter overlap, 0.0 = no shared minutes.
        Defaults to 1.0 if data is unavailable.
        """
        if not opponent_defender or self._cache is None:
            return 1.0

        key = f"{player_name}:{opponent_defender}"
        if self._matchup_data and key in self._matchup_data:
            return self._matchup_data[key]

        try:
            player_id = self._cache.resolve_player_id(player_name)
            defender_id = self._cache.resolve_player_id(opponent_defender)
            if not player_id or not defender_id:
                return 1.0

            player_logs = self._cache.fetch_player_game_logs(player_id, self._season)
            defender_logs = self._cache.fetch_player_game_logs(defender_id, self._season)

            if not player_logs or not defender_logs:
                return 1.0

            player_avg_min = _avg_minutes(player_logs)
            defender_avg_min = _avg_minutes(defender_logs)

            if player_avg_min <= 0 or defender_avg_min <= 0:
                return 1.0

            # Approximate shared minutes: min of both averages / 48 (game length)
            shared = min(player_avg_min, defender_avg_min)
            weight = min(1.0, max(0.0, shared / 36.0))

            if self._matchup_data is None:
                self._matchup_data = {}
            self._matchup_data[key] = weight

            return weight
        except Exception as exc:
            logger.debug("Shared minutes calc failed: %s", exc)
            return 1.0


def _avg_minutes(logs: list[dict]) -> float:
    """Calculate average minutes from game log dicts."""
    minutes = []
    for g in logs:
        min_val = g.get("MIN", 0)
        try:
            if isinstance(min_val, str) and ":" in min_val:
                parts = min_val.split(":")
                minutes.append(float(parts[0]) + float(parts[1]) / 60)
            else:
                minutes.append(float(min_val))
        except (ValueError, TypeError):
            continue
    return sum(minutes) / len(minutes) if minutes else 0.0


# ---------------------------------------------------------------------------
# Paint Deterrence Model
# ---------------------------------------------------------------------------

class PaintDeterrenceEvaluator:
    """
    Tag elite paint protectors and discount scoring for rim-dependent players
    facing them.
    """

    def __init__(self, cache=None, season: str = "2024-25"):
        self._cache = cache
        self._season = season
        self._elite_protectors: dict[str, dict] | None = None
        self._player_shot_dist: dict[int, dict] = {}

    def evaluate(
        self,
        player_name: str,
        opponent_team: str,
        shared_minutes: float = 36.0,
    ) -> float:
        """
        Return scoring discount (0.0–0.18) for paint deterrence.
        Higher = more discount applied.
        """
        if self._cache is None:
            return 0.0

        protectors = self._get_elite_protectors()
        opp_protectors = [
            p for p in protectors.values()
            if p.get("team_abbreviation", "") != ""
            and self._team_matches(p, opponent_team)
        ]

        if not opp_protectors:
            return 0.0

        player_id = self._cache.resolve_player_id(player_name)
        if not player_id:
            return 0.0

        rim_pct = self._get_rim_shot_pct(player_id)
        if rim_pct is None or rim_pct <= _RIM_DEPENDENT_THRESHOLD:
            return 0.0

        if shared_minutes < _PAINT_DETERRENCE_MIN_SHARED_MIN:
            return 0.0

        three_pct = self._get_three_point_pct(player_name)
        if three_pct is not None and three_pct > _THREE_POINT_SHOOTER_THRESHOLD:
            return _PAINT_DETERRENCE_MIN_DISCOUNT * 0.5

        best_protector = max(opp_protectors, key=lambda p: p.get("blk_per36", 0))
        severity = self._calc_severity(best_protector, rim_pct, shared_minutes)

        return severity

    def get_team_rim_dependency(self, team_name: str) -> float:
        """
        Return team-level rim dependency score (0.0–1.0) for moneyline adjustments.
        """
        if self._cache is None:
            return 0.0

        try:
            rows = self._cache.fetch_league_dash_team_stats(
                season=self._season, measure_type="Base"
            )
            for row in rows:
                if row.get("TEAM_NAME", "") == team_name:
                    fga = row.get("FGA", 1)
                    fg2a = fga - row.get("FG3A", 0)
                    if fga > 0:
                        return min(1.0, fg2a / fga)
            return 0.0
        except Exception:
            return 0.0

    def get_elite_protectors_for_team(self, team_name: str) -> list[dict]:
        protectors = self._get_elite_protectors()
        return [
            p for p in protectors.values()
            if self._team_matches(p, team_name)
        ]

    def _get_elite_protectors(self) -> dict[str, dict]:
        if self._elite_protectors is not None:
            return self._elite_protectors

        self._elite_protectors = {}
        if self._cache is None:
            return self._elite_protectors

        try:
            per36_stats = self._cache.fetch_league_dash_player_stats(
                season=self._season, per_mode="Per36"
            )
            blk_leaders: dict[str, dict] = {}
            for row in per36_stats:
                name = row.get("PLAYER_NAME", "")
                blk = row.get("BLK", 0.0)
                if blk >= _ELITE_PAINT_PROTECTOR_BLK_RATE and name:
                    blk_leaders[name] = {
                        "player_name": name,
                        "blk_per36": float(blk),
                        "team_abbreviation": row.get("TEAM_ABBREVIATION", ""),
                        "team_id": row.get("TEAM_ID", 0),
                        "player_id": row.get("PLAYER_ID", 0),
                    }

            try:
                defend_data = self._cache.fetch_league_dash_pt_defend(
                    season=self._season, defense_category="Overall"
                )
                rim_dfg_map: dict[str, float] = {}
                for row in defend_data:
                    name = row.get("CLOSE_DEF_PERSON_ID", "")
                    dfg_pct = row.get("D_FG_PCT", 1.0)
                    pname = row.get("PLAYER_NAME", "")
                    if pname:
                        rim_dfg_map[pname] = float(dfg_pct)

                for name, info in list(blk_leaders.items()):
                    dfg = rim_dfg_map.get(name, 0.60)
                    if dfg <= _ELITE_PAINT_PROTECTOR_RIM_DFG:
                        info["rim_dfg_pct"] = dfg
                        self._elite_protectors[name] = info
            except Exception:
                # If rim defense data unavailable, use block rate alone
                self._elite_protectors = blk_leaders

            logger.info(
                "Elite paint protectors identified: %s",
                list(self._elite_protectors.keys()),
            )
        except Exception as exc:
            logger.debug("Paint protector identification failed: %s", exc)

        return self._elite_protectors

    def _get_rim_shot_pct(self, player_id: int) -> float | None:
        if player_id in self._player_shot_dist:
            return self._player_shot_dist[player_id].get("rim_pct")

        try:
            shots = self._cache.fetch_player_dash_pt_shots(player_id, self._season)
            if not shots:
                return None

            total_fga = sum(s.get("FGA", 0) for s in shots)
            rim_fga = 0
            for s in shots:
                zone = str(s.get("SHOT_DIST_RANGE", "") or s.get("CLOSE_DEF_DIST_RANGE", ""))
                if any(k in zone.lower() for k in ["less than", "0-", "restricted", "paint"]):
                    rim_fga += s.get("FGA", 0)

            rim_pct = rim_fga / total_fga if total_fga > 0 else 0.0
            self._player_shot_dist[player_id] = {"rim_pct": rim_pct}
            return rim_pct
        except Exception:
            return None

    def _get_three_point_pct(self, player_name: str) -> float | None:
        if self._cache is None:
            return None
        try:
            rows = self._cache.fetch_league_dash_player_stats(
                season=self._season, per_mode="PerGame"
            )
            for row in rows:
                if row.get("PLAYER_NAME", "") == player_name:
                    fg3_pct = row.get("FG3_PCT", 0.0)
                    return float(fg3_pct) if fg3_pct else None
            return None
        except Exception:
            return None

    @staticmethod
    def _team_matches(protector: dict, team_name: str) -> bool:
        abbr = protector.get("team_abbreviation", "")
        return (
            abbr and (
                abbr.lower() in team_name.lower()
                or team_name.lower() in abbr.lower()
            )
        ) or protector.get("team_name", "").lower() == team_name.lower()

    @staticmethod
    def _calc_severity(
        protector: dict, rim_pct: float, shared_minutes: float
    ) -> float:
        blk_factor = min(1.0, protector.get("blk_per36", 0) / 6.0)
        rim_factor = min(1.0, rim_pct / 0.70)
        minutes_factor = min(1.0, shared_minutes / 36.0)

        raw = blk_factor * rim_factor * minutes_factor
        scaled = _PAINT_DETERRENCE_MIN_DISCOUNT + raw * (
            _PAINT_DETERRENCE_MAX_DISCOUNT - _PAINT_DETERRENCE_MIN_DISCOUNT
        )
        return min(_PAINT_DETERRENCE_MAX_DISCOUNT, scaled)


# ---------------------------------------------------------------------------
# Foul Trouble Risk Model
# ---------------------------------------------------------------------------

class FoulTroubleRiskEvaluator:
    """
    Assess foul trouble risk: foul-prone defenders vs elite FT drawers.
    """

    def __init__(self, cache=None, season: str = "2024-25"):
        self._cache = cache
        self._season = season
        self._per36_stats: dict[str, dict] | None = None
        self._per_game_stats: dict[str, dict] | None = None

    def evaluate_defender(self, defender_name: str, matchup_name: str) -> dict:
        """
        Assess foul trouble risk for a defender against a specific matchup.
        Returns {risk: HIGH/MEDIUM/LOW, discount: float, boost: float}.
        """
        per36 = self._get_per36_stats()
        per_game = self._get_per_game_stats()

        defender_stats = per36.get(defender_name, {})
        matchup_stats = per_game.get(matchup_name, {})

        pf_per36 = float(defender_stats.get("PF", 0.0))
        matchup_fta = float(matchup_stats.get("FTA", 0.0))
        matchup_fga = float(matchup_stats.get("FGA", 1.0))

        fta_rate = matchup_fta / matchup_fga if matchup_fga > 0 else 0.0

        if pf_per36 >= _FOUL_PRONE_THRESHOLD and fta_rate >= _ELITE_FT_DRAWER_RATE:
            risk = "HIGH"
            discount = 0.10
            boost = 0.06
        elif pf_per36 >= _FOUL_PRONE_THRESHOLD or fta_rate >= _ELITE_FT_DRAWER_RATE:
            risk = "MEDIUM"
            discount = 0.05
            boost = 0.03
        else:
            risk = "LOW"
            discount = 0.0
            boost = 0.0

        return {"risk": risk, "discount": discount, "boost": boost}

    def get_team_foul_exposure(
        self, team_name: str, opponent_primary_handler: str | None = None
    ) -> dict:
        """
        Team-level foul exposure: if key defender is foul-prone against
        opponent's primary ball handler, return adjustment.
        """
        if not opponent_primary_handler:
            return {"risk": "LOW", "adjustment": 0.0}

        per36 = self._get_per36_stats()
        per_game = self._get_per_game_stats()

        foul_prone_defenders = [
            (name, stats) for name, stats in per36.items()
            if float(stats.get("PF", 0)) >= _FOUL_PRONE_THRESHOLD
            and self._player_on_team(name, team_name, per_game)
        ]

        if not foul_prone_defenders:
            return {"risk": "LOW", "adjustment": 0.0}

        handler_stats = per_game.get(opponent_primary_handler, {})
        handler_fta = float(handler_stats.get("FTA", 0))
        handler_fga = float(handler_stats.get("FGA", 1))
        handler_fta_rate = handler_fta / handler_fga if handler_fga > 0 else 0.0

        if handler_fta_rate >= _ELITE_FT_DRAWER_RATE:
            return {"risk": "HIGH", "adjustment": -0.03}

        return {"risk": "MEDIUM", "adjustment": -0.01}

    @staticmethod
    def _player_on_team(
        player_name: str, team_name: str, per_game: dict[str, dict]
    ) -> bool:
        stats = per_game.get(player_name, {})
        return team_name.lower() in str(stats.get("TEAM_NAME", "")).lower()

    def _get_per36_stats(self) -> dict[str, dict]:
        if self._per36_stats is not None:
            return self._per36_stats
        self._per36_stats = self._load_stats("Per36")
        return self._per36_stats

    def _get_per_game_stats(self) -> dict[str, dict]:
        if self._per_game_stats is not None:
            return self._per_game_stats
        self._per_game_stats = self._load_stats("PerGame")
        return self._per_game_stats

    def _load_stats(self, per_mode: str) -> dict[str, dict]:
        if self._cache is None:
            return {}
        try:
            rows = self._cache.fetch_league_dash_player_stats(
                season=self._season, per_mode=per_mode
            )
            return {row.get("PLAYER_NAME", ""): row for row in rows if row.get("PLAYER_NAME")}
        except Exception as exc:
            logger.debug("Stats load failed (%s): %s", per_mode, exc)
            return {}


# ---------------------------------------------------------------------------
# Advanced Opponent Stats Layer
# ---------------------------------------------------------------------------

class AdvancedOpponentStats:
    """
    Pull and integrate opponent pace, defensive rating, paint points allowed,
    FTA rate allowed, and on/off differentials.
    """

    LEAGUE_AVG_PACE = 100.0
    LEAGUE_AVG_DEF_RTG = 112.0
    LEAGUE_AVG_PITP = 48.0
    LEAGUE_AVG_FTA_RATE = 0.25

    def __init__(self, cache=None, season: str = "2024-25"):
        self._cache = cache
        self._season = season
        self._team_stats: dict[str, dict] | None = None
        self._adv_team_stats: dict[str, dict] | None = None

    def get_opponent_adjustments(self, opponent_team: str) -> dict:
        """
        Return per-stat adjustment multipliers based on opponent characteristics.
        """
        base = self._get_base_team_stats()
        advanced = self._get_advanced_team_stats()

        opp_base = base.get(opponent_team, {})
        opp_adv = advanced.get(opponent_team, {})

        pace = float(opp_adv.get("PACE", self.LEAGUE_AVG_PACE))
        def_rtg = float(opp_adv.get("DEF_RATING", self.LEAGUE_AVG_DEF_RTG))

        pace_factor = pace / self.LEAGUE_AVG_PACE
        def_factor = self.LEAGUE_AVG_DEF_RTG / def_rtg if def_rtg > 0 else 1.0

        opp_fta = float(opp_base.get("OPP_FTA", 0))
        opp_fga = float(opp_base.get("OPP_FGA", 1))
        opp_fta_rate = opp_fta / opp_fga if opp_fga > 0 else self.LEAGUE_AVG_FTA_RATE

        pitp = float(opp_base.get("OPP_PTS_PAINT", self.LEAGUE_AVG_PITP))
        pitp_factor = pitp / self.LEAGUE_AVG_PITP if self.LEAGUE_AVG_PITP > 0 else 1.0

        return {
            "pace": pace,
            "pace_factor": round(pace_factor, 4),
            "def_rating": def_rtg,
            "def_factor": round(def_factor, 4),
            "opp_fta_rate": round(opp_fta_rate, 4),
            "opp_pitp_factor": round(pitp_factor, 4),
        }

    def get_pace_adjustment(self, opponent_team: str) -> float:
        """Return % adjustment to counting stats based on opponent pace."""
        adj = self.get_opponent_adjustments(opponent_team)
        return adj["pace_factor"] - 1.0

    def get_def_rating_adjustment(self, opponent_team: str) -> float:
        """Return % adjustment based on opponent defensive quality."""
        adj = self.get_opponent_adjustments(opponent_team)
        return adj["def_factor"] - 1.0

    def _get_base_team_stats(self) -> dict[str, dict]:
        if self._team_stats is not None:
            return self._team_stats
        if self._cache is None:
            self._team_stats = {}
            return {}
        try:
            rows = self._cache.fetch_league_dash_team_stats(
                season=self._season, measure_type="Base"
            )
            self._team_stats = {
                row.get("TEAM_NAME", ""): row
                for row in rows if row.get("TEAM_NAME")
            }
        except Exception as exc:
            logger.debug("Base team stats load failed: %s", exc)
            self._team_stats = {}
        return self._team_stats

    def _get_advanced_team_stats(self) -> dict[str, dict]:
        if self._adv_team_stats is not None:
            return self._adv_team_stats
        if self._cache is None:
            self._adv_team_stats = {}
            return {}
        try:
            rows = self._cache.fetch_league_dash_team_stats(
                season=self._season, measure_type="Advanced"
            )
            self._adv_team_stats = {
                row.get("TEAM_NAME", ""): row
                for row in rows if row.get("TEAM_NAME")
            }
        except Exception as exc:
            logger.debug("Advanced team stats load failed: %s", exc)
            self._adv_team_stats = {}
        return self._adv_team_stats


# ---------------------------------------------------------------------------
# Unified PropContextEvaluator
# ---------------------------------------------------------------------------

class PropContextEvaluator:
    """
    Pipeline that runs each candidate prop through all contextual evaluators:
    position filter → shared minutes → paint deterrence → foul trouble → opp stats.
    """

    def __init__(self, cache=None, season: str = "2024-25"):
        self._cache = cache
        self._season = season
        self.position_filter = PositionFilter(cache=cache, season=season)
        self.shared_minutes = SharedMinutesFilter(cache=cache, season=season)
        self.paint_deterrence = PaintDeterrenceEvaluator(cache=cache, season=season)
        self.foul_trouble = FoulTroubleRiskEvaluator(cache=cache, season=season)
        self.opp_stats = AdvancedOpponentStats(cache=cache, season=season)

    def evaluate_props(self, props: list[dict]) -> list[dict]:
        """
        Takes a list of candidate prop dicts with keys:
            player, market, line, model_prob, over_odds, opponent_team, event_id,
            home_team, away_team, confidence
        Returns list with added keys: adjusted_prob, ev, flags
        """
        results = []
        for prop in props:
            result = self.evaluate_single(prop)
            if result is not None:
                results.append(result)
        return results

    def evaluate_single(self, prop: dict) -> dict | None:
        """
        Run a single prop through the full evaluator pipeline.
        Returns None if the prop is filtered out.
        """
        player = prop.get("player", "")
        market = prop.get("market", "")
        opponent = prop.get("opponent_team", "")
        model_prob = prop.get("model_prob", 0.5)
        over_odds = prop.get("over_odds", -110)

        flags = ContextFlags()

        # 1. Position filter
        if self.position_filter.should_filter(player, market):
            flags.position_filtered = True
            return None

        # 2. Shared minutes weight
        flags.shared_minutes_weight = self.shared_minutes.get_shared_minutes_weight(player)

        # 3. Paint deterrence
        if market in ("player_points", "player_threes"):
            deterrence = self.paint_deterrence.evaluate(player, opponent)
            flags.paint_deterrence_pct = deterrence

        # 4. Foul trouble
        defender_name = self._cache.fetch_matchup_defender(player) if self._cache else None
        ft_eval = self.foul_trouble.evaluate_defender(defender_name or "", player)
        flags.foul_trouble_risk = ft_eval["risk"]
        flags.foul_trouble_boost = ft_eval["boost"]

        # 5. Advanced opponent stats
        opp_adj = self.opp_stats.get_opponent_adjustments(opponent)
        flags.pace_adjustment = opp_adj["pace_factor"] - 1.0
        flags.def_rating_adjustment = opp_adj["def_factor"] - 1.0

        # Apply adjustments to model probability
        total_adj = flags.total_adjustment
        # Scale the projection, then re-derive probability shift
        # A +5% pace means ~5% more counting stats → shifts prob upward
        adjusted_prob = model_prob * (1.0 + total_adj)
        adjusted_prob = max(0.01, min(0.99, adjusted_prob))

        # Apply shared minutes weight to matchup-based adjustments
        if flags.shared_minutes_weight < 1.0:
            blend = flags.shared_minutes_weight
            adjusted_prob = model_prob * (1.0 - blend) + adjusted_prob * blend

        # Calculate EV
        from alpha.engines.sports.ev_calculator import EVCalculator
        ev_calc = EVCalculator(min_edge=0.0)
        decimal_odds = ev_calc.american_to_decimal(over_odds)
        implied_prob = ev_calc.implied_prob(decimal_odds)
        ev = ev_calc.expected_value(adjusted_prob, decimal_odds)
        edge = adjusted_prob - implied_prob

        return {
            **prop,
            "adjusted_prob": round(adjusted_prob, 4),
            "original_prob": model_prob,
            "ev": round(ev, 4),
            "edge": round(edge, 4),
            "implied_prob": round(implied_prob, 4),
            "flags": flags.as_dict(),
        }
