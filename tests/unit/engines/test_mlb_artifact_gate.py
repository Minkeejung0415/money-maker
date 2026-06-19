import joblib
from unittest.mock import patch
from sklearn.linear_model import LogisticRegression
import numpy as np
from alpha.engines.sports.mlb_model import MLBModel
from alpha.engines.sports.mlb_training import FEATURE_NAMES


def test_unvalidated_bundle_is_rejected(tmp_path, monkeypatch):
    path=tmp_path/"mlb_win_probability.pkl"; joblib.dump({"kind":"mlb_win_probability_bundle","validated":False},path)
    monkeypatch.setattr(MLBModel,"_find_model_path",lambda self:path)
    model=MLBModel(); assert not model._xgb_models_loaded


def test_schema_mismatch_is_rejected(tmp_path, monkeypatch):
    path=tmp_path/"mlb_win_probability.pkl"; joblib.dump({"kind":"mlb_win_probability_bundle","validated":True,"feature_names":["bad"]},path)
    monkeypatch.setattr(MLBModel,"_find_model_path",lambda self:path)
    model=MLBModel(); assert not model._xgb_models_loaded
