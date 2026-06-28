"""Lightweight runtime artifact metadata validation.

This is intentionally small: JSON metadata beside model artifacts, validated
before a scanner can trust an artifact for runtime picks.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ArtifactCheck:
    ok: bool
    reason: str
    metadata: dict[str, Any]
    path: Path


REQUIRED_METADATA_FIELDS = frozenset({
    "model_id",
    "league",
    "market",
    "created_at",
    "feature_schema_hash",
    "dataset_fingerprint",
    "calibration",
    "promotion_passed",
    "allowed_runtime",
})


def validate_runtime_artifact(
    path: str | Path,
    *,
    league: str,
    market: str,
    expected_feature_schema_hash: str | None = None,
    supported_model_ids: set[str] | None = None,
) -> ArtifactCheck:
    """Validate JSON metadata for runtime model selection."""
    metadata_path = Path(path)
    if not metadata_path.exists():
        return ArtifactCheck(False, "artifact_metadata_missing", {}, metadata_path)

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return ArtifactCheck(False, f"artifact_metadata_invalid_json:{exc.msg}", {}, metadata_path)

    missing = sorted(REQUIRED_METADATA_FIELDS - set(metadata))
    if missing:
        return ArtifactCheck(
            False,
            "artifact_metadata_missing_fields:" + ",".join(missing),
            metadata,
            metadata_path,
        )

    if str(metadata.get("league", "")).upper() != league.upper():
        return ArtifactCheck(False, "artifact_league_mismatch", metadata, metadata_path)
    if str(metadata.get("market", "")).lower() != market.lower():
        return ArtifactCheck(False, "artifact_market_mismatch", metadata, metadata_path)
    if metadata.get("promotion_passed") is not True:
        return ArtifactCheck(False, "artifact_not_promoted", metadata, metadata_path)
    if metadata.get("allowed_runtime") is not True:
        return ArtifactCheck(False, "artifact_runtime_not_allowed", metadata, metadata_path)
    if expected_feature_schema_hash is not None and metadata.get("feature_schema_hash") != expected_feature_schema_hash:
        return ArtifactCheck(False, "artifact_schema_failed", metadata, metadata_path)
    if supported_model_ids is not None and metadata.get("model_id") not in supported_model_ids:
        return ArtifactCheck(False, "artifact_model_unsupported", metadata, metadata_path)

    artifact_file = metadata.get("artifact_path")
    if artifact_file:
        artifact_path = metadata_path.parent / str(artifact_file)
        if not artifact_path.exists():
            return ArtifactCheck(False, "artifact_file_missing", metadata, metadata_path)

    return ArtifactCheck(True, "ok", metadata, metadata_path)
