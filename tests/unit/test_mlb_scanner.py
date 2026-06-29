from __future__ import annotations

import json
import sys

from scripts import mlb_scanner


def test_parse_args_accepts_schedule_date(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["mlb_scanner.py", "--mode", "parlay", "--date", "2026-06-28"],
    )

    args = mlb_scanner._parse_args()

    assert args.mode == "parlay"
    assert args.date == "2026-06-28"


def test_parse_args_accepts_individual_only(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["mlb_scanner.py", "--date", "2026-06-28", "--individual-only"],
    )

    args = mlb_scanner._parse_args()

    assert args.date == "2026-06-28"
    assert args.individual_only is True


def test_parse_args_accepts_player_features_file(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["mlb_scanner.py", "--player-features-file", "data/features.json"],
    )

    args = mlb_scanner._parse_args()

    assert args.player_features_file == "data/features.json"


def test_load_player_features_file_accepts_events_wrapper(tmp_path):
    path = tmp_path / "features.json"
    path.write_text(
        json.dumps({"events": {"123": {"lineup_strength_diff": 0.1}}}),
        encoding="utf-8",
    )

    result = mlb_scanner._load_player_features_file(str(path))

    assert result == {"123": {"lineup_strength_diff": 0.1}}


def test_main_passes_schedule_date_to_live_player_features(monkeypatch):
    calls = {}

    class DummyModel:
        _player_bundle = {}
        _model_bundle = {}
        _xgb_models_loaded = False

        def predict(self, game):
            return {
                "home_win_prob": 0.55,
                "away_win_prob": 0.45,
                "model_label": "test",
                "confidence": "MEDIUM",
                "pick_eligible": False,
                "uncertainty_flags": ["test_flag"],
                "feature_context": game.get("player_features", {}),
            }

        def runtime_report(self):
            return {"source": "test", "selective_report": {}}

    def fake_fetch_today_games(date):
        calls["fetch_date"] = date
        return [{
            "event_id": "g1",
            "home_team": "New York Yankees",
            "away_team": "Boston Red Sox",
            "home_odds": -110,
            "away_odds": -110,
        }]

    def fake_build_live_player_features(games, **kwargs):
        calls["feature_date"] = kwargs.get("game_date")
        return {"g1": {"sp_quality_diff": 0.2, "player_feature_missing_flag": 0.0}}

    monkeypatch.setattr(sys, "argv", ["mlb_scanner.py", "--date", "2026-06-28", "--individual-only"])
    monkeypatch.setattr("alpha.data.ingestion.mlb_stats.fetch_today_games", fake_fetch_today_games)
    monkeypatch.setattr("alpha.engines.sports.mlb_model.MLBModel", DummyModel)
    monkeypatch.setattr(
        "alpha.data.ingestion.mlb_live_player_features.build_live_player_features",
        fake_build_live_player_features,
    )

    mlb_scanner.main()

    assert calls["fetch_date"] == "2026-06-28"
    assert calls["feature_date"] == "2026-06-28"
