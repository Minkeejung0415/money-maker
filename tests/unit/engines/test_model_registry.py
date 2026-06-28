"""Tests for lightweight runtime artifact metadata validation."""
from __future__ import annotations

import json

from alpha.engines.model_registry import validate_runtime_artifact


def _metadata(**overrides):
    data = {
        "model_id": "wc_hybrid_baseline",
        "league": "WC",
        "market": "moneyline",
        "created_at": "2026-06-28",
        "feature_schema_hash": "abc",
        "dataset_fingerprint": "dataset",
        "calibration": "isotonic",
        "promotion_passed": True,
        "allowed_runtime": True,
    }
    data.update(overrides)
    return data


def test_missing_metadata_file_fails(tmp_path):
    check = validate_runtime_artifact(tmp_path / "missing.json", league="WC", market="moneyline")
    assert not check.ok
    assert check.reason == "artifact_metadata_missing"


def test_promoted_runtime_metadata_passes(tmp_path):
    path = tmp_path / "model.meta.json"
    path.write_text(json.dumps(_metadata()), encoding="utf-8")
    check = validate_runtime_artifact(
        path,
        league="WC",
        market="moneyline",
        expected_feature_schema_hash="abc",
        supported_model_ids={"wc_hybrid_baseline"},
    )
    assert check.ok
    assert check.metadata["model_id"] == "wc_hybrid_baseline"


def test_schema_mismatch_fails(tmp_path):
    path = tmp_path / "model.meta.json"
    path.write_text(json.dumps(_metadata(feature_schema_hash="old")), encoding="utf-8")
    check = validate_runtime_artifact(
        path,
        league="WC",
        market="moneyline",
        expected_feature_schema_hash="new",
    )
    assert not check.ok
    assert check.reason == "artifact_schema_failed"


def test_runtime_not_allowed_fails(tmp_path):
    path = tmp_path / "model.meta.json"
    path.write_text(json.dumps(_metadata(allowed_runtime=False)), encoding="utf-8")
    check = validate_runtime_artifact(path, league="WC", market="moneyline")
    assert not check.ok
    assert check.reason == "artifact_runtime_not_allowed"
