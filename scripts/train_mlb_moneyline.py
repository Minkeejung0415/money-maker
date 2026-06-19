"""Train and validate the MLB moneyline probability model."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from alpha.engines.sports.evaluation import probability_metrics
from alpha.engines.sports.mlb_training import FEATURE_NAMES, build_pregame_rows


def fetch_games(start: str, end: str) -> list[dict]:
    """Fetch in calendar-year chunks; StatsAPI truncates very large date ranges."""
    import statsapi
    from datetime import date
    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    result=[]
    for year in range(start_date.year, end_date.year + 1):
        chunk_start=max(start_date,date(year,1,1)).isoformat()
        chunk_end=min(end_date,date(year,12,31)).isoformat()
        for g in statsapi.schedule(start_date=chunk_start, end_date=chunk_end):
            if g.get("status") != "Final" or g.get("game_type", "R") not in ("R","F","D","L","W"):
                continue
            result.append({"date": str(g.get("game_date", g.get("game_datetime", "")))[:10],
                           "game_id": str(g.get("game_id", "")), "home_team": g.get("home_name", ""),
                           "away_team": g.get("away_name", ""), "home_score": g.get("home_score"),
                           "away_score": g.get("away_score")})
    return list({g["game_id"]: g for g in result}.values())


def _matrix(rows):
    import numpy as np
    return np.asarray([[float(r[n]) for n in FEATURE_NAMES] for r in rows]), np.asarray([r["home_win"] for r in rows])


def _platt(raw_probs, y):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    p=np.clip(raw_probs,1e-6,1-1e-6)
    logits=np.log(p/(1-p)).reshape(-1,1)
    return LogisticRegression().fit(logits,y)


def calibrated(calibrator, raw_probs):
    import numpy as np
    p=np.clip(raw_probs,1e-6,1-1e-6)
    return calibrator.predict_proba(np.log(p/(1-p)).reshape(-1,1))[:,1]


def train(games: list[dict], output: Path) -> dict:
    import joblib
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    rows,state=build_pregame_rows(games)
    if len(rows) < 300:
        raise ValueError(f"Need at least 300 completed games, got {len(rows)}")
    n=len(rows); a=int(n*.6); b=int(n*.8)
    train_rows,cal_rows,test_rows=rows[:a],rows[a:b],rows[b:]
    Xtr,ytr=_matrix(train_rows); Xc,yc=_matrix(cal_rows); Xt,yt=_matrix(test_rows)
    candidates={"logistic":LogisticRegression(max_iter=2000,C=.5),
                "hist_gradient_boosting":HistGradientBoostingClassifier(max_depth=3,max_iter=200,learning_rate=.05,l2_regularization=1.0,random_state=42)}
    scored={}
    for name,model in candidates.items():
        model.fit(Xtr,ytr)
        cal=_platt(model.predict_proba(Xc)[:,1],yc)
        probs=calibrated(cal,model.predict_proba(Xt)[:,1])
        metrics=probability_metrics(yt.tolist(),probs.tolist())
        metrics["accuracy"]=float(((probs>=.5)==yt).mean())
        scored[name]=(metrics["brier_score"],model,cal,metrics)
    name,(score,model,cal,metrics)=min(scored.items(),key=lambda x:x[1][0])
    home_rate=float(yt.mean())
    baselines={"coin_brier":probability_metrics(yt.tolist(),[.5]*len(yt))["brier_score"],
               "home_rate_brier":probability_metrics(yt.tolist(),[home_rate]*len(yt))["brier_score"]}
    validated=score < min(baselines.values())
    bundle={"kind":"mlb_win_probability_bundle","validated":validated,"model":model,
            "calibrator":cal,"feature_names":list(FEATURE_NAMES),"team_state":state,
            "metrics":metrics,"baselines":baselines,"candidate":name,
            "training_start":rows[0]["date"],"training_end":train_rows[-1]["date"],
            "test_start":test_rows[0]["date"],"test_end":test_rows[-1]["date"],
            "trained_at":datetime.now(timezone.utc).isoformat(),"version":"mlb-v1.3"}
    output.parent.mkdir(parents=True,exist_ok=True); joblib.dump(bundle,output)
    meta={k:v for k,v in bundle.items() if k not in ("model","calibrator","team_state")}
    output.with_suffix('.meta.json').write_text(json.dumps(meta,indent=2,default=str),encoding='utf-8')
    return meta


def main():
    p=argparse.ArgumentParser(); p.add_argument('--input'); p.add_argument('--start',default='2023-03-20'); p.add_argument('--end',default='2026-06-18'); p.add_argument('--output',default='alpha/models/mlb_win_probability.pkl'); args=p.parse_args()
    games=json.loads(Path(args.input).read_text(encoding='utf-8')) if args.input else fetch_games(args.start,args.end)
    meta=train(games,Path(args.output)); print(json.dumps(meta,indent=2,default=str))
    if not meta['validated']: raise SystemExit('Model failed baseline release gate')

if __name__=='__main__': main()
