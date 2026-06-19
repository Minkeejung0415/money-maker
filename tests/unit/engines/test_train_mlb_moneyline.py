import importlib.util
from datetime import date, timedelta
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[3]/"scripts"/"train_mlb_moneyline.py"


def _trainer():
    spec=importlib.util.spec_from_file_location("train_mlb_moneyline",SCRIPT); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


def test_train_writes_auditable_bundle(tmp_path):
    games=[]; start=date(2023,4,1)
    teams=[f"T{i}" for i in range(10)]
    for i in range(500):
        h=teams[i%10]; a=teams[(i*3+1)%10]
        hs=6 if (i%10)<6 else 2; aws=3 if hs==6 else 5
        games.append({"date":str(start+timedelta(days=i//5)),"game_id":i,"home_team":h,"away_team":a,"home_score":hs,"away_score":aws})
    out=tmp_path/"model.pkl"; meta=_trainer().train(games,out)
    assert out.exists() and out.with_suffix('.meta.json').exists()
    assert meta["feature_names"] and "brier_score" in meta["metrics"]
    assert meta["test_start"] > meta["training_end"]
