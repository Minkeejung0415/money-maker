"""World Cup route-level xG offsets from projected XI role strengths.

The route-offset layer is an adapter over the WC hybrid/scoreline stack. It
never predicts WDL directly. It turns bounded role and tactical-duel signals
into small xG deltas that can be inspected in shadow mode before promotion.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Mapping

SCHEMA_VERSION = "wc_route_offsets_v1"
DEFAULT_CONFIG_ID = "wc_route_offsets_rule_config_v1"
REQUIRED_ROLES = ("GK", "CB", "FB", "DM", "W", "ST")
ROUTES = ("center", "wing", "set_piece", "counterattack")
CRITICAL_ROLES = frozenset({"GK", "CB", "FB", "DM", "W", "ST"})


@dataclass(frozen=True)
class RouteOffsetConfig:
    """Caps and identity for deterministic route-offset rules."""

    config_id: str = DEFAULT_CONFIG_ID
    schema_version: str = SCHEMA_VERSION
    max_rule_delta: float = 0.08
    max_team_delta: float = 0.18
    stale_after_hours: int = 72


@dataclass(frozen=True)
class RouteOffsetResult:
    """Computed route-offset diagnostics for one fixture."""

    status: str
    reason: str
    schema_version: str
    config_id: str
    source: str
    updated_at: str | None
    role_coverage: dict[str, float]
    missing_roles: dict[str, list[str]]
    uncertainty_shrink: float
    pick_eligible: bool
    active_duels: list[dict[str, object]]
    route_deltas: dict[str, dict[str, float]]
    total_delta: dict[str, float]
    cap_hits: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "config_id": self.config_id,
            "source": self.source,
            "updated_at": self.updated_at,
            "role_coverage": self.role_coverage,
            "missing_roles": self.missing_roles,
            "uncertainty_shrink": self.uncertainty_shrink,
            "pick_eligible": self.pick_eligible,
            "active_duels": self.active_duels,
            "route_deltas": self.route_deltas,
            "total_delta": self.total_delta,
            "cap_hits": self.cap_hits,
        }


class WCRouteOffsetEngine:
    """Evaluate projected-XI tactical duels as bounded route-level xG deltas."""

    def __init__(
        self,
        snapshots: Mapping[str, object] | None = None,
        config: RouteOffsetConfig | None = None,
    ) -> None:
        self.config = config or RouteOffsetConfig()
        self._snapshots = dict(snapshots or {})

    @classmethod
    def from_file(
        cls,
        path: str | Path | None,
        config: RouteOffsetConfig | None = None,
    ) -> "WCRouteOffsetEngine":
        if path is None:
            return cls(config=config)
        p = Path(path)
        if not p.exists():
            return cls(config=config)
        data = json.loads(p.read_text(encoding="utf-8"))
        fixtures = data.get("fixtures", data) if isinstance(data, Mapping) else {}
        if isinstance(fixtures, list):
            fixtures = {
                str(item.get("event_id") or f"{item.get('home_team')}|{item.get('away_team')}"): item
                for item in fixtures
                if isinstance(item, Mapping)
            }
        return cls(fixtures if isinstance(fixtures, Mapping) else {}, config=config)

    def evaluate(self, game: Mapping[str, object], as_of: datetime | None = None) -> RouteOffsetResult:
        snapshot = self._find_snapshot(game)
        if snapshot is None:
            return self._empty("fallback", "route_offset_snapshot_missing")
        if not isinstance(snapshot, Mapping):
            return self._empty("fallback", "route_offset_snapshot_invalid")

        schema = str(snapshot.get("schema_version") or SCHEMA_VERSION)
        if schema != self.config.schema_version:
            return self._empty("fallback", "route_offset_schema_mismatch", schema_version=schema)

        source = str(snapshot.get("source") or "projected_xi_snapshot")
        updated_at = snapshot.get("updated_at")
        if self._is_stale(updated_at, as_of=as_of):
            return self._empty(
                "fallback",
                "route_offset_snapshot_stale",
                source=source,
                updated_at=str(updated_at) if updated_at else None,
            )

        home_roles = _extract_roles(snapshot, "home")
        away_roles = _extract_roles(snapshot, "away")
        missing = {
            "home": [role for role in REQUIRED_ROLES if role not in home_roles],
            "away": [role for role in REQUIRED_ROLES if role not in away_roles],
        }
        coverage = {
            "home": round((len(REQUIRED_ROLES) - len(missing["home"])) / len(REQUIRED_ROLES), 4),
            "away": round((len(REQUIRED_ROLES) - len(missing["away"])) / len(REQUIRED_ROLES), 4),
        }
        shrink = min(coverage.values())
        critical_missing = bool((set(missing["home"]) | set(missing["away"])) & CRITICAL_ROLES)
        route_deltas = {side: {route: 0.0 for route in ROUTES} for side in ("home", "away")}
        active_duels: list[dict[str, object]] = []
        cap_hits: list[str] = []

        self._add_duel(
            "wing_isolation",
            route_deltas,
            active_duels,
            cap_hits,
            home_value=_wing_attack(home_roles) - _wide_defense(away_roles),
            away_value=_wing_attack(away_roles) - _wide_defense(home_roles),
            route="wing",
            weight=0.045,
            shrink=shrink,
        )
        self._add_duel(
            "aerial_set_piece_mismatch",
            route_deltas,
            active_duels,
            cap_hits,
            home_value=_aerial_attack(home_roles) - _aerial_defense(away_roles),
            away_value=_aerial_attack(away_roles) - _aerial_defense(home_roles),
            route="set_piece",
            weight=0.04,
            shrink=shrink,
        )
        self._add_duel(
            "press_vs_build",
            route_deltas,
            active_duels,
            cap_hits,
            home_value=_press(home_roles) - _build_security(away_roles),
            away_value=_press(away_roles) - _build_security(home_roles),
            route="counterattack",
            weight=0.035,
            shrink=shrink,
        )

        total_delta = {
            side: self._cap_team_delta(sum(route_deltas[side].values()), side, cap_hits)
            for side in ("home", "away")
        }
        for side in ("home", "away"):
            raw = sum(route_deltas[side].values())
            if abs(raw) > self.config.max_team_delta and raw != 0:
                ratio = total_delta[side] / raw
                route_deltas[side] = {
                    route: round(value * ratio, 4)
                    for route, value in route_deltas[side].items()
                }
            else:
                route_deltas[side] = {
                    route: round(value, 4)
                    for route, value in route_deltas[side].items()
                }

        status = "shadow_ready"
        reason = "ok"
        pick_eligible = not critical_missing and shrink >= 0.8
        if not pick_eligible:
            status = "shadow_suppressed"
            reason = "route_offset_role_coverage_incomplete"

        return RouteOffsetResult(
            status=status,
            reason=reason,
            schema_version=schema,
            config_id=self.config.config_id,
            source=source,
            updated_at=str(updated_at) if updated_at else None,
            role_coverage=coverage,
            missing_roles=missing,
            uncertainty_shrink=round(shrink, 4),
            pick_eligible=pick_eligible,
            active_duels=active_duels,
            route_deltas=route_deltas,
            total_delta={side: round(value, 4) for side, value in total_delta.items()},
            cap_hits=cap_hits,
        )

    def _find_snapshot(self, game: Mapping[str, object]) -> object | None:
        event_id = game.get("event_id")
        if event_id is not None and str(event_id) in self._snapshots:
            return self._snapshots[str(event_id)]
        fixture_key = f"{game.get('home_team')}|{game.get('away_team')}"
        return self._snapshots.get(fixture_key)

    def _empty(
        self,
        status: str,
        reason: str,
        *,
        schema_version: str | None = None,
        source: str = "none",
        updated_at: str | None = None,
    ) -> RouteOffsetResult:
        return RouteOffsetResult(
            status=status,
            reason=reason,
            schema_version=schema_version or self.config.schema_version,
            config_id=self.config.config_id,
            source=source,
            updated_at=updated_at,
            role_coverage={"home": 0.0, "away": 0.0},
            missing_roles={"home": list(REQUIRED_ROLES), "away": list(REQUIRED_ROLES)},
            uncertainty_shrink=0.0,
            pick_eligible=False,
            active_duels=[],
            route_deltas={side: {route: 0.0 for route in ROUTES} for side in ("home", "away")},
            total_delta={"home": 0.0, "away": 0.0},
            cap_hits=[],
        )

    def _is_stale(self, value: object, as_of: datetime | None = None) -> bool:
        if value is None:
            return False
        try:
            updated = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return True
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        ref = as_of or datetime.now(timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        age_hours = (ref - updated).total_seconds() / 3600.0
        return age_hours > self.config.stale_after_hours

    def _add_duel(
        self,
        rule_id: str,
        route_deltas: dict[str, dict[str, float]],
        active_duels: list[dict[str, object]],
        cap_hits: list[str],
        *,
        home_value: float,
        away_value: float,
        route: str,
        weight: float,
        shrink: float,
    ) -> None:
        for side, raw_value in (("home", home_value), ("away", away_value)):
            raw_delta = raw_value * weight * shrink
            delta = _cap(raw_delta, self.config.max_rule_delta)
            if delta != raw_delta:
                cap_hits.append(f"{rule_id}:{side}:rule")
            route_deltas[side][route] += delta
            if abs(delta) >= 0.001:
                active_duels.append({
                    "rule_id": rule_id,
                    "team_side": side,
                    "route": route,
                    "raw_value": round(raw_value, 4),
                    "delta": round(delta, 4),
                    "shrink": round(shrink, 4),
                })

    def _cap_team_delta(self, value: float, side: str, cap_hits: list[str]) -> float:
        capped = _cap(value, self.config.max_team_delta)
        if capped != value:
            cap_hits.append(f"{side}:team")
        return capped


def apply_route_offsets(
    home_lambda: float,
    away_lambda: float,
    result: Mapping[str, object] | RouteOffsetResult | None,
) -> tuple[float, float]:
    """Apply total route deltas to lambdas with scoreline bounds."""
    if result is None:
        return home_lambda, away_lambda
    if isinstance(result, RouteOffsetResult):
        payload = result.as_dict()
    else:
        payload = dict(result)
    total_delta = payload.get("total_delta", {})
    if not isinstance(total_delta, Mapping):
        return home_lambda, away_lambda
    return (
        _bounded_goal_rate(home_lambda + _float(total_delta.get("home"))),
        _bounded_goal_rate(away_lambda + _float(total_delta.get("away"))),
    )


def allocate_route_lambdas(home_lambda: float, away_lambda: float) -> dict[str, dict[str, float]]:
    """Allocate total lambdas into stable route buckets for diagnostics."""
    weights = {"center": 0.44, "wing": 0.28, "set_piece": 0.18, "counterattack": 0.10}
    return {
        "home": {route: round(home_lambda * weight, 4) for route, weight in weights.items()},
        "away": {route: round(away_lambda * weight, 4) for route, weight in weights.items()},
    }


def _extract_roles(snapshot: Mapping[str, object], side: str) -> dict[str, Mapping[str, object]]:
    side_payload = snapshot.get(side, {})
    if not isinstance(side_payload, Mapping):
        return {}
    roles = side_payload.get("roles", side_payload)
    if not isinstance(roles, Mapping):
        return {}
    return {str(role).upper(): values for role, values in roles.items() if isinstance(values, Mapping)}


def _score(roles: Mapping[str, Mapping[str, object]], role: str, keys: tuple[str, ...]) -> float:
    values = [_float(roles.get(role, {}).get(key)) for key in keys]
    values = [value for value in values if math.isfinite(value)]
    if not values:
        return 0.0
    return max(-1.0, min(1.0, sum(values) / len(values)))


def _wing_attack(roles: Mapping[str, Mapping[str, object]]) -> float:
    return _score(roles, "W", ("isolation", "crossing", "cutbacks", "transition"))


def _wide_defense(roles: Mapping[str, Mapping[str, object]]) -> float:
    return 0.7 * _score(roles, "FB", ("defensive_isolation", "recovery", "duel_defense")) + 0.3 * _score(
        roles, "CB", ("side_cover", "wide_cover", "box_defense")
    )


def _aerial_attack(roles: Mapping[str, Mapping[str, object]]) -> float:
    return 0.65 * _score(roles, "ST", ("aerial", "box_presence")) + 0.35 * _score(
        roles, "CB", ("set_piece_threat", "aerial")
    )


def _aerial_defense(roles: Mapping[str, Mapping[str, object]]) -> float:
    return 0.65 * _score(roles, "CB", ("aerial_defense", "box_defense")) + 0.35 * _score(
        roles, "GK", ("cross_claiming", "shot_stopping")
    )


def _press(roles: Mapping[str, Mapping[str, object]]) -> float:
    return 0.45 * _score(roles, "W", ("pressing", "transition")) + 0.35 * _score(
        roles, "ST", ("pressing",)
    ) + 0.20 * _score(roles, "DM", ("ball_recovery", "pressing"))


def _build_security(roles: Mapping[str, Mapping[str, object]]) -> float:
    return 0.55 * _score(roles, "CB", ("buildup_security", "press_resistance")) + 0.45 * _score(
        roles, "DM", ("press_resistance", "buildup_security")
    )


def _cap(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def _float(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(result):
        return 0.0
    return result


def _bounded_goal_rate(value: float) -> float:
    return max(0.25, min(3.5, value))
