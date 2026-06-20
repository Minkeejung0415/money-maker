"""Unit tests for train_epl_moneyline.py — synthetic rows, no API calls, no file I/O mocking."""
import importlib.util
import pytest
from datetime import date, timedelta
from pathlib import Path

from alpha.engines.sports.epl_training import EPL_FEATURE_NAMES

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "train_epl_moneyline.py"


def _trainer():
    spec = importlib.util.spec_from_file_location("train_epl_moneyline", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_synthetic_rows(n: int = 400) -> list[dict]:
    """Create n synthetic game dicts that build_epl_pregame_rows() can process into rows."""
    teams = [f"Team{i}" for i in range(12)]
    start = date(2022, 8, 1)
    games = []
    for i in range(n):
        h = teams[i % 12]
        a = teams[(i * 5 + 3) % 12]
        if h == a:
            a = teams[(i * 5 + 4) % 12]
        # Alternate wins and losses (no draws) to keep binary classification meaningful
        hs = 2 if i % 2 == 0 else 1
        aws = 1 if i % 2 == 0 else 2
        games.append({
            "date": str(start + timedelta(days=i // 3)),
            "game_id": str(i),
            "home_team": h,
            "away_team": a,
            "home_score": hs,
            "away_score": aws,
        })
    return games


def test_bundle_kind(tmp_path):
    """train() on synthetic rows produces bundle['kind'] == 'epl_win_probability_bundle'."""
    trainer = _trainer()
    games = _make_synthetic_rows(400)
    out = tmp_path / "epl_model.pkl"
    meta = trainer.train(games, out)
    assert meta["kind"] == "epl_win_probability_bundle"


def test_bundle_feature_names(tmp_path):
    """bundle['feature_names'] == list(EPL_FEATURE_NAMES)."""
    trainer = _trainer()
    games = _make_synthetic_rows(400)
    out = tmp_path / "epl_model.pkl"
    meta = trainer.train(games, out)
    assert meta["feature_names"] == list(EPL_FEATURE_NAMES)


def test_meta_json_written(tmp_path):
    """.meta.json exists after train() call."""
    trainer = _trainer()
    games = _make_synthetic_rows(400)
    out = tmp_path / "epl_model.pkl"
    trainer.train(games, out)
    assert out.with_suffix(".meta.json").exists()


def test_too_few_rows_raises(tmp_path):
    """train() on <300 rows raises ValueError."""
    trainer = _trainer()
    # 50 games will produce far fewer than 300 rows
    games = _make_synthetic_rows(50)
    out = tmp_path / "epl_model.pkl"
    with pytest.raises(ValueError):
        trainer.train(games, out)


def test_validated_field_present(tmp_path):
    """bundle has 'validated' key (bool)."""
    trainer = _trainer()
    games = _make_synthetic_rows(400)
    out = tmp_path / "epl_model.pkl"
    meta = trainer.train(games, out)
    assert "validated" in meta
    assert isinstance(meta["validated"], bool)
