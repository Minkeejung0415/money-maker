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
