"""Leakage-safe contracts for historical World Cup tactical calibration data."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1
MIN_DEVELOPMENT = 200
MIN_VALIDATION = 50
MIN_EXTERNAL_AUDIT = 30
WC_AUDIT_START = datetime(2026, 6, 11, tzinfo=timezone.utc)
TACTICAL_COMPONENTS = (
    "chance creation",
    "possession control",
    "press resistance",
    "directness vs block",
    "width vs block",
    "set-piece pressure",
    "opponent defensive block",
)


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _finite(value: object, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


@dataclass(frozen=True)
class TacticalHistoryRow:
    """One completed match represented only by pre-kickoff information."""

    event_id: str
    kickoff: str
    competition: str
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    stage: str
    neutral: bool
    card_status_known: bool
    had_red_card: bool
    extra_time: bool
    home_profile_latest: str
    away_profile_latest: str
    home_profile_matches: int
    away_profile_matches: int
    home_elo: float
    away_elo: float
    elo_as_of: str
    home_goal_rate: float
    away_goal_rate: float
    goal_rates_as_of: str
    baseline_home: float
    baseline_draw: float
    baseline_away: float
    baseline_home_lambda: float
    baseline_away_lambda: float
    home_components: Mapping[str, float]
    away_components: Mapping[str, float]
    source_url: str

    def validate(self) -> None:
        if not self.event_id or not self.home_team or not self.away_team:
            raise ValueError("event_id and both teams are required")
        kickoff = _utc(self.kickoff)
        for field, timestamp in (
            ("home_profile_latest", self.home_profile_latest),
            ("away_profile_latest", self.away_profile_latest),
            ("elo_as_of", self.elo_as_of),
            ("goal_rates_as_of", self.goal_rates_as_of),
        ):
            if _utc(timestamp) >= kickoff:
                raise ValueError(f"{field} must be strictly before kickoff")
        if not self.card_status_known:
            raise ValueError("card status must be known")
        if self.had_red_card or self.extra_time:
            raise ValueError("red-card and extra-time matches are ineligible")
        if self.home_profile_matches < 3 or self.away_profile_matches < 3:
            raise ValueError("both profiles require at least three prior matches")
        probabilities = [
            _finite(self.baseline_home, "baseline_home"),
            _finite(self.baseline_draw, "baseline_draw"),
            _finite(self.baseline_away, "baseline_away"),
        ]
        if any(value <= 0 or value >= 1 for value in probabilities):
            raise ValueError("baseline probabilities must be inside (0, 1)")
        if not math.isclose(sum(probabilities), 1.0, abs_tol=1e-4):
            raise ValueError("baseline probabilities must sum to one")
        for side, components in (("home", self.home_components), ("away", self.away_components)):
            if set(components) != set(TACTICAL_COMPONENTS):
                raise ValueError(f"{side} components do not match schema")
            for name, value in components.items():
                _finite(value, f"{side}.{name}")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TacticalHistoryRow":
        row = cls(**dict(payload))
        row.validate()
        return row


@dataclass(frozen=True)
class CoverageReport:
    discovered: int
    eligible: int
    development: int
    validation: int
    external_audit: int
    duplicate_events: int
    exclusions: Mapping[str, int]

    @property
    def ready(self) -> bool:
        return (
            self.development >= MIN_DEVELOPMENT
            and self.validation >= MIN_VALIDATION
            and self.external_audit >= MIN_EXTERNAL_AUDIT
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ready": self.ready}


def partition_rows(
    rows: Iterable[TacticalHistoryRow],
    *,
    audit_cutoff: datetime,
) -> tuple[list[TacticalHistoryRow], list[TacticalHistoryRow], list[TacticalHistoryRow]]:
    """Create immutable chronological development, validation, and WC audit sets."""
    unique: dict[str, TacticalHistoryRow] = {}
    for row in rows:
        row.validate()
        previous = unique.get(row.event_id)
        if previous is not None and previous.to_dict() != row.to_dict():
            raise ValueError(f"conflicting duplicate event_id: {row.event_id}")
        unique[row.event_id] = row
    ordered = sorted(unique.values(), key=lambda row: (_utc(row.kickoff), row.event_id))
    pre_tournament = [row for row in ordered if _utc(row.kickoff) < WC_AUDIT_START]
    audit = [row for row in ordered if WC_AUDIT_START <= _utc(row.kickoff) <= audit_cutoff]
    validation = pre_tournament[-MIN_VALIDATION:] if len(pre_tournament) >= MIN_VALIDATION else pre_tournament
    validation_ids = {row.event_id for row in validation}
    development = [row for row in pre_tournament if row.event_id not in validation_ids]
    return development, validation, audit


def audit_rows(rows: Iterable[TacticalHistoryRow], *, audit_cutoff: datetime) -> CoverageReport:
    materialized = list(rows)
    unique_ids = {row.event_id for row in materialized}
    exclusions: dict[str, int] = {}
    valid: list[TacticalHistoryRow] = []
    for row in materialized:
        try:
            row.validate()
        except ValueError as exc:
            key = str(exc)
            exclusions[key] = exclusions.get(key, 0) + 1
        else:
            if row.event_id not in {item.event_id for item in valid}:
                valid.append(row)
    development, validation, audit = partition_rows(valid, audit_cutoff=audit_cutoff)
    return CoverageReport(
        discovered=len(materialized),
        eligible=len(valid),
        development=len(development),
        validation=len(validation),
        external_audit=len(audit),
        duplicate_events=len(materialized) - len(unique_ids),
        exclusions=dict(sorted(exclusions.items())),
    )


def write_dataset(
    rows: Iterable[TacticalHistoryRow],
    output_dir: str | Path,
    *,
    audit_cutoff: datetime,
) -> dict[str, Any]:
    """Write deterministic split files and a content-addressed manifest."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    development, validation, audit = partition_rows(rows, audit_cutoff=audit_cutoff)
    splits = {"development": development, "validation": validation, "external_audit": audit}
    files: dict[str, dict[str, Any]] = {}
    for name, split in splits.items():
        content = "".join(
            json.dumps(row.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
            for row in split
        )
        path = output / f"{name}.jsonl"
        path.write_text(content, encoding="utf-8")
        files[name] = {
            "path": path.name,
            "rows": len(split),
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "event_ids": [row.event_id for row in split],
        }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "audit_cutoff": audit_cutoff.astimezone(timezone.utc).isoformat(),
        "files": files,
        "ready": (
            len(development) >= MIN_DEVELOPMENT
            and len(validation) >= MIN_VALIDATION
            and len(audit) >= MIN_EXTERNAL_AUDIT
        ),
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest_path = output / "manifest.json"
    if manifest_path.exists() and manifest_path.read_text(encoding="utf-8") != manifest_text:
        raise FileExistsError("sealed manifest differs; write a new dataset version")
    manifest_path.write_text(manifest_text, encoding="utf-8")
    return manifest


def load_rows(path: str | Path) -> list[TacticalHistoryRow]:
    rows: list[TacticalHistoryRow] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(TacticalHistoryRow.from_dict(json.loads(line)))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid row {line_number}: {exc}") from exc
    return rows


def _summary_event(summary: Mapping[str, Any], event_id: str) -> dict[str, Any] | None:
    forms = summary.get("boxscore", {}).get("form", [])
    teams = {
        str(item.get("team", {}).get("id", "")): str(item.get("team", {}).get("displayName", ""))
        for item in forms
    }
    event = next(
        (event for item in forms for event in item.get("events", []) if str(event.get("id", "")) == event_id),
        None,
    )
    header_competition = (summary.get("header", {}).get("competitions") or [{}])[0]
    if event is None:
        competitors = header_competition.get("competitors", [])
        home_entry = next((item for item in competitors if item.get("homeAway") == "home"), None)
        away_entry = next((item for item in competitors if item.get("homeAway") == "away"), None)
        if home_entry is None or away_entry is None:
            return None
        event = {
            "gameDate": header_competition.get("date", ""),
            "competitionName": summary.get("header", {}).get("season", {}).get("name", "international"),
            "roundName": (header_competition.get("status", {}).get("type", {}).get("detail") or "GROUP_STAGE"),
            "homeTeamScore": home_entry.get("score", 0),
            "awayTeamScore": away_entry.get("score", 0),
        }
        home = str(home_entry.get("team", {}).get("displayName", ""))
        away = str(away_entry.get("team", {}).get("displayName", ""))
    else:
        home_id, away_id = str(event.get("homeTeamId", "")), str(event.get("awayTeamId", ""))
        home, away = teams.get(home_id, ""), teams.get(away_id, "")
    if not home or not away:
        return None
    commentary = summary.get("commentary")
    card_status_known = isinstance(commentary, list) or bool(header_competition.get("commentaryAvailable"))
    commentary_text = json.dumps({"commentary": commentary or [], "keyEvents": summary.get("keyEvents", [])}).lower()
    had_red_card = "red card" in commentary_text or '"type":"red-card"' in commentary_text
    extra_time = "extra time" in commentary_text or any(
        int(item.get("play", {}).get("period", {}).get("number", 0) or 0) > 2
        for item in (commentary or []) if isinstance(item, Mapping)
    )
    return {
        "event_id": event_id,
        "kickoff": str(event.get("gameDate", "")),
        "competition": str(event.get("competitionName") or event.get("leagueName") or "international"),
        "stage": str(event.get("roundName") or "GROUP_STAGE").upper().replace(" ", "_"),
        "home_team": home,
        "away_team": away,
        "home_goals": int(event.get("homeTeamScore", 0)),
        "away_goals": int(event.get("awayTeamScore", 0)),
        "neutral": bool(header_competition.get("neutralSite", False)),
        "card_status_known": card_status_known,
        "had_red_card": had_red_card,
        "extra_time": extra_time,
        "summary": summary,
    }


def build_rows_from_espn_cache(cache_dir: str | Path) -> list[TacticalHistoryRow]:
    """Reconstruct historical rows directly from immutable cached ESPN summaries."""
    from alpha.data.ingestion.wc_tactics import aggregate_tactical_profile, parse_tactical_match
    from alpha.engines.sports.wc_goal_markets import WCScorelineModel
    from alpha.engines.sports.wc_model import WCMatchModel
    from alpha.engines.sports.wc_tactical_matchup import compare_tactics

    events = []
    for path in sorted(Path(cache_dir).glob("event_*.json")):
        event_id = path.stem.removeprefix("event_")
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
            event = _summary_event(summary, event_id)
            if event is not None and event["kickoff"]:
                event["source_path"] = path.as_posix()
                events.append(event)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    events.sort(key=lambda event: (_utc(event["kickoff"]), event["event_id"]))

    tactical_history: dict[str, list[dict[str, Any]]] = {}
    result_history: dict[str, list[dict[str, Any]]] = {}
    elo: dict[str, float] = {}
    rows: list[TacticalHistoryRow] = []
    model = WCMatchModel()
    scoreline_model = WCScorelineModel()

    for event in events:
        kickoff = _utc(event["kickoff"])
        home, away = event["home_team"], event["away_team"]
        home_profile = aggregate_tactical_profile(home, list(tactical_history.get(home, [])))
        away_profile = aggregate_tactical_profile(away, list(tactical_history.get(away, [])))
        home_results, away_results = result_history.get(home, []), result_history.get(away, [])
        eligible = (
            home_profile is not None and away_profile is not None
            and len(home_results) >= 3 and len(away_results) >= 3
            and event["card_status_known"] and not event["had_red_card"] and not event["extra_time"]
        )
        if eligible:
            comparison = compare_tactics(home_profile, away_profile)
            home_goal_rate = sum(item["goals_for"] for item in home_results[-5:]) / min(5, len(home_results))
            away_goal_rate = sum(item["goals_for"] for item in away_results[-5:]) / min(5, len(away_results))
            home_defense = sum(item["goals_against"] for item in home_results[-5:]) / min(5, len(home_results))
            away_defense = sum(item["goals_against"] for item in away_results[-5:]) / min(5, len(away_results))
            game = model.predict({
                "home_team": home, "away_team": away, "league": "wc", "stage": "GROUP_STAGE",
                "home_elo_override": round(elo.get(home, 1500.0)),
                "away_elo_override": round(elo.get(away, 1500.0)),
                "recent_team_stats": {
                    home: {"avg_goals": home_goal_rate, "defense_score": home_defense},
                    away: {"avg_goals": away_goal_rate, "defense_score": away_defense},
                },
            })
            distribution = scoreline_model.build(game)
            latest_result = max(home_results[-1]["kickoff"], away_results[-1]["kickoff"])
            rows.append(TacticalHistoryRow(
                event_id=event["event_id"], kickoff=kickoff.isoformat(), competition=event["competition"],
                home_team=home, away_team=away, home_goals=event["home_goals"], away_goals=event["away_goals"],
                stage=event["stage"], neutral=event["neutral"], card_status_known=True,
                had_red_card=False, extra_time=False,
                home_profile_latest=f"{home_profile.latest_match}T00:00:00+00:00",
                away_profile_latest=f"{away_profile.latest_match}T00:00:00+00:00",
                home_profile_matches=home_profile.matches, away_profile_matches=away_profile.matches,
                home_elo=game["home_elo"], away_elo=game["away_elo"], elo_as_of=latest_result,
                home_goal_rate=home_goal_rate, away_goal_rate=away_goal_rate, goal_rates_as_of=latest_result,
                baseline_home=game["win_prob"], baseline_draw=game["draw_prob"], baseline_away=game["loss_prob"],
                baseline_home_lambda=distribution.home_lambda, baseline_away_lambda=distribution.away_lambda,
                home_components=comparison.home_components, away_components=comparison.away_components,
                source_url=f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary?event={event['event_id']}",
            ))

        home_elo, away_elo = elo.get(home, 1500.0), elo.get(away, 1500.0)
        expected_home = 1.0 / (1.0 + 10.0 ** ((away_elo - home_elo) / 400.0))
        actual_home = 1.0 if event["home_goals"] > event["away_goals"] else 0.0 if event["home_goals"] < event["away_goals"] else 0.5
        change = 30.0 * (actual_home - expected_home)
        elo[home], elo[away] = home_elo + change, away_elo - change
        for team, opponent, goals_for, goals_against in (
            (home, away, event["home_goals"], event["away_goals"]),
            (away, home, event["away_goals"], event["home_goals"]),
        ):
            result_history.setdefault(team, []).append({
                "kickoff": kickoff.isoformat(), "opponent": opponent,
                "goals_for": goals_for, "goals_against": goals_against,
            })
            if event["card_status_known"] and not event["had_red_card"] and not event["extra_time"]:
                metrics = parse_tactical_match(event["summary"], team)
                if metrics is not None:
                    tactical_history.setdefault(team, []).append({"date": kickoff.date().isoformat(), "metrics": metrics})
    return rows
