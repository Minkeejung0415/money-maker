from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from alpha.data.ingestion.wc_tactical_history import (
    TACTICAL_COMPONENTS,
    TacticalHistoryRow,
    audit_rows,
    partition_rows,
    write_dataset,
)


def _row(event_id: str = "1", kickoff: datetime | None = None) -> TacticalHistoryRow:
    kickoff = kickoff or datetime(2025, 1, 10, tzinfo=timezone.utc)
    before = (kickoff - timedelta(days=1)).isoformat()
    components = {name: 0.1 for name in TACTICAL_COMPONENTS}
    return TacticalHistoryRow(
        event_id=event_id, kickoff=kickoff.isoformat(), competition="qualifier",
        home_team="A", away_team="B", home_goals=1, away_goals=0,
        stage="GROUP_STAGE", neutral=True, card_status_known=True,
        had_red_card=False, extra_time=False, home_profile_latest=before,
        away_profile_latest=before, home_profile_matches=5, away_profile_matches=5,
        home_elo=1800, away_elo=1750, elo_as_of=before,
        home_goal_rate=1.3, away_goal_rate=1.1, goal_rates_as_of=before,
        baseline_home=0.45, baseline_draw=0.30, baseline_away=0.25,
        baseline_home_lambda=1.3, baseline_away_lambda=1.1,
        home_components=components, away_components=components,
        source_url="https://example.test/event/1",
    )


def test_row_round_trip_and_future_leakage_gate():
    row = _row()
    assert TacticalHistoryRow.from_dict(row.to_dict()) == row
    with pytest.raises(ValueError, match="strictly before kickoff"):
        replace(row, elo_as_of=row.kickoff).validate()


def test_red_card_and_unknown_card_status_fail_closed():
    with pytest.raises(ValueError, match="red-card"):
        replace(_row(), had_red_card=True).validate()
    with pytest.raises(ValueError, match="card status"):
        replace(_row(), card_status_known=False).validate()


def test_partition_seals_latest_pre_tournament_validation_and_wc_audit():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [_row(str(index), start + timedelta(days=index)) for index in range(260)]
    wc_start = datetime(2026, 6, 11, tzinfo=timezone.utc)
    rows += [_row(f"wc-{index}", wc_start + timedelta(hours=index)) for index in range(31)]
    development, validation, audit = partition_rows(
        rows, audit_cutoff=wc_start + timedelta(days=2)
    )
    assert len(validation) == 50
    assert len(audit) == 31
    assert not ({row.event_id for row in development} & {row.event_id for row in validation})


def test_duplicate_event_is_counted_and_conflicts_are_rejected():
    row = _row()
    report = audit_rows([row, row], audit_cutoff=datetime(2026, 6, 21, tzinfo=timezone.utc))
    assert report.duplicate_events == 1
    with pytest.raises(ValueError, match="conflicting duplicate"):
        partition_rows([row, replace(row, home_goals=2)], audit_cutoff=datetime(2026, 6, 21, tzinfo=timezone.utc))


def test_dataset_is_deterministic_and_manifest_is_sealed(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [_row(str(index), start + timedelta(days=index)) for index in range(3)]
    cutoff = datetime(2026, 6, 21, tzinfo=timezone.utc)
    first = write_dataset(rows, tmp_path, audit_cutoff=cutoff)
    second = write_dataset(reversed(rows), tmp_path, audit_cutoff=cutoff)
    assert first == second
    assert json.loads((tmp_path / "manifest.json").read_text())["schema_version"] == 1
