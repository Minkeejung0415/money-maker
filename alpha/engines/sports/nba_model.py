"""
NBA Model wrapper — produces win probabilities and EV-scored bet opportunities.

Primary implementation: implied-probability calibration from market odds,
adjusted with a simple Elo-style regression toward 50%.

Optional: delegates to NBA-Machine-Learning-Sports-Betting XGBoost model
when that library, its models, and today's TeamData.sqlite are all available.
"""
from __future__ import annotations

import importlib.util
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from alpha.engines.sports.ev_calculator import EVCalculator

logger = logging.getLogger(__name__)

# Elo regression factor: blend market-implied prob with 0.5
# 0.0 = trust market fully, 1.0 = always predict 50/50
MARKET_BLEND = 0.15

# Maps common Odds-API name variations -> exact team_index_current keys
TEAM_NAME_MAP: dict[str, str] = {
    # Lakers
    "LA Lakers": "Los Angeles Lakers",
    "L.A. Lakers": "Los Angeles Lakers",
    "LAL": "Los Angeles Lakers",
    # Clippers
    "LA Clippers": "Los Angeles Clippers",
    "L.A. Clippers": "Los Angeles Clippers",
    "LAC": "Los Angeles Clippers",
    # Warriors
    "GS Warriors": "Golden State Warriors",
    "Golden St. Warriors": "Golden State Warriors",
    "Golden St Warriors": "Golden State Warriors",
    "GSW": "Golden State Warriors",
    # Knicks
    "NY Knicks": "New York Knicks",
    "New York": "New York Knicks",
    "NYK": "New York Knicks",
    # Nets
    "BK Nets": "Brooklyn Nets",
    "BKN": "Brooklyn Nets",
    # Oklahoma City
    "OKC Thunder": "Oklahoma City Thunder",
    "OKC": "Oklahoma City Thunder",
    "Oklahoma City": "Oklahoma City Thunder",
    # San Antonio
    "SA Spurs": "San Antonio Spurs",
    "SAS": "San Antonio Spurs",
    # New Orleans
    "NO Pelicans": "New Orleans Pelicans",
    "New Orleans": "New Orleans Pelicans",
    "NOP": "New Orleans Pelicans",
    "NOLA Pelicans": "New Orleans Pelicans",
    # Minnesota
    "Minnesota": "Minnesota Timberwolves",
    "MIN": "Minnesota Timberwolves",
    # Charlotte
    "Charlotte": "Charlotte Hornets",
    "CHA": "Charlotte Hornets",
    # Memphis
    "Memphis": "Memphis Grizzlies",
    "MEM": "Memphis Grizzlies",
    # Portland
    "Portland": "Portland Trail Blazers",
    "POR": "Portland Trail Blazers",
    # Sacramento
    "Sacramento": "Sacramento Kings",
    "SAC": "Sacramento Kings",
    # Utah
    "Utah": "Utah Jazz",
    "UTA": "Utah Jazz",
    # Washington
    "Washington": "Washington Wizards",
    "WAS": "Washington Wizards",
    # Toronto
    "Toronto": "Toronto Raptors",
    "TOR": "Toronto Raptors",
    # Philadelphia
    "Philadelphia": "Philadelphia 76ers",
    "PHI": "Philadelphia 76ers",
    # Phoenix
    "Phoenix": "Phoenix Suns",
    "PHX": "Phoenix Suns",
    # Orlando
    "Orlando": "Orlando Magic",
    "ORL": "Orlando Magic",
    # Indiana
    "Indiana": "Indiana Pacers",
    "IND": "Indiana Pacers",
    # Houston
    "Houston": "Houston Rockets",
    "HOU": "Houston Rockets",
    # Detroit
    "Detroit": "Detroit Pistons",
    "DET": "Detroit Pistons",
    # Denver
    "Denver": "Denver Nuggets",
    "DEN": "Denver Nuggets",
    # Dallas
    "Dallas": "Dallas Mavericks",
    "DAL": "Dallas Mavericks",
    # Cleveland
    "Cleveland": "Cleveland Cavaliers",
    "CLE": "Cleveland Cavaliers",
    # Chicago
    "Chicago": "Chicago Bulls",
    "CHI": "Chicago Bulls",
    # Boston
    "Boston": "Boston Celtics",
    "BOS": "Boston Celtics",
    # Atlanta
    "Atlanta": "Atlanta Hawks",
    "ATL": "Atlanta Hawks",
    # Milwaukee
    "Milwaukee": "Milwaukee Bucks",
    "MIL": "Milwaukee Bucks",
    # Miami
    "Miami": "Miami Heat",
    "MIA": "Miami Heat",
}

# Paths relative to the working directory (where the CLI is launched from)
_NBA_ML_DIR = Path("NBA-Machine-Learning-Sports-Betting")
_MODEL_DIR = _NBA_ML_DIR / "Models" / "XGBoost_Models"
_TEAMS_DB = _NBA_ML_DIR / "Data" / "TeamData.sqlite"
_ACCURACY_RE = re.compile(r"XGBoost_(\d+(?:\.\d+)?)%_")


class NBAModel:
    def __init__(self, min_edge: float = 0.04, kelly_fraction: float = 0.25):
        self.ev_calc = EVCalculator(min_edge=min_edge)
        self._kelly_fraction = kelly_fraction

        # XGBoost state — populated lazily by _load_xgb_models()
        self._xgb_ml = None
        self._xgb_ml_calibrator = None
        self._xgb_models_loaded: bool = False

        self._load_xgb_models()

    # ------------------------------------------------------------------
    # Public: stat refresh
    # ------------------------------------------------------------------

    def refresh_stats(self) -> bool:
        """
        Pull today's cumulative team stats from stats.nba.com into
        NBA-Machine-Learning-Sports-Betting/Data/TeamData.sqlite.

        Returns True on success.  On any failure (network down, NBA API
        rate-limit, missing dependency) logs a warning and returns False
        without raising — the caller can continue with market-implied logic.
        """
        try:
            if str(_NBA_ML_DIR) not in sys.path:
                sys.path.insert(0, str(_NBA_ML_DIR))

            spec = importlib.util.spec_from_file_location(
                "_nba_ml_get_data",
                _NBA_ML_DIR / "src" / "Process-Data" / "Get_Data.py",
            )
            if spec is None or spec.loader is None:
                raise ImportError("Could not locate Get_Data.py")

            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            mod.main()
            logger.info("NBA stats refresh succeeded")
            return True
        except Exception as exc:
            logger.warning("NBA stats refresh failed (continuing with cached data): %s", exc)
            return False

    # ------------------------------------------------------------------
    # Public: team name normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_team(name: str) -> str:
        """
        Map a raw team name to the exact key used in team_index_current.

        Resolution order:
        1. Exact match in TEAM_NAME_MAP
        2. Case-insensitive substring match against known canonical names
        3. Return the original name unchanged
        """
        if name in TEAM_NAME_MAP:
            return TEAM_NAME_MAP[name]

        # Try case-insensitive lookup in the explicit map
        name_lower = name.lower()
        for raw, canonical in TEAM_NAME_MAP.items():
            if raw.lower() == name_lower:
                return canonical

        # Substring match against canonical names (e.g. "Celtics" -> "Boston Celtics")
        _CANONICAL_NAMES = {
            "Atlanta Hawks", "Boston Celtics", "Brooklyn Nets",
            "Charlotte Hornets", "Chicago Bulls", "Cleveland Cavaliers",
            "Dallas Mavericks", "Denver Nuggets", "Detroit Pistons",
            "Golden State Warriors", "Houston Rockets", "Indiana Pacers",
            "Los Angeles Clippers", "Los Angeles Lakers", "Memphis Grizzlies",
            "Miami Heat", "Milwaukee Bucks", "Minnesota Timberwolves",
            "New Orleans Pelicans", "New York Knicks", "Oklahoma City Thunder",
            "Orlando Magic", "Philadelphia 76ers", "Phoenix Suns",
            "Portland Trail Blazers", "Sacramento Kings", "San Antonio Spurs",
            "Toronto Raptors", "Utah Jazz", "Washington Wizards",
        }
        for canonical in _CANONICAL_NAMES:
            if name_lower == canonical.lower():
                return canonical
            if name_lower in canonical.lower() or canonical.lower() in name_lower:
                return canonical

        return name

    # ------------------------------------------------------------------
    # Public: predict / evaluate
    # ------------------------------------------------------------------

    def predict(self, game: dict) -> dict:
        """
        Estimate win probabilities for a game.

        Tries the XGBoost 68.9 % model first; falls back to
        market-implied probabilities blended toward 50/50 on any failure.
        """
        home_team = self._normalize_team(game.get("home_team", ""))
        away_team = self._normalize_team(game.get("away_team", ""))

        if self._xgb_models_loaded:
            try:
                probs = self._predict_xgb(home_team, away_team)
                if probs is not None:
                    home_prob, away_prob = probs
                    return {
                        "home_team": home_team,
                        "away_team": away_team,
                        "home_win_prob": round(home_prob, 4),
                        "away_win_prob": round(away_prob, 4),
                        "source": "xgboost",
                    }
            except Exception as exc:
                logger.debug("XGBoost prediction failed, using market-implied: %s", exc)

        return self._market_implied_predict(game)

    def evaluate_bet(self, game: dict) -> dict:
        """
        Find the best bet in a game (home or away moneyline).
        Returns opportunity dict with bet_side, model_prob, decimal_odds, ev.
        """
        probs = self.predict(game)
        home_odds = game.get("home_odds", -110)
        away_odds = game.get("away_odds", -110)

        home_dec = self.ev_calc.american_to_decimal(home_odds)
        away_dec = self.ev_calc.american_to_decimal(away_odds)

        home_ev = self.ev_calc.expected_value(probs["home_win_prob"], home_dec)
        away_ev = self.ev_calc.expected_value(probs["away_win_prob"], away_dec)

        if home_ev >= away_ev and self.ev_calc.has_edge(probs["home_win_prob"], home_dec):
            return {
                "bet_side": "home",
                "team": probs["home_team"],
                "model_prob": probs["home_win_prob"],
                "decimal_odds": home_dec,
                "ev": round(home_ev, 4),
            }
        elif self.ev_calc.has_edge(probs["away_win_prob"], away_dec):
            return {
                "bet_side": "away",
                "team": probs["away_team"],
                "model_prob": probs["away_win_prob"],
                "decimal_odds": away_dec,
                "ev": round(away_ev, 4),
            }
        return {
            "bet_side": "no_bet",
            "team": "",
            "model_prob": 0.0,
            "decimal_odds": 0.0,
            "ev": max(home_ev, away_ev),
        }

    def evaluate_batch(self, games: list[dict]) -> list[dict]:
        return [self.evaluate_bet(g) for g in games]

    # ------------------------------------------------------------------
    # Internal: market-implied fallback (original logic)
    # ------------------------------------------------------------------

    def _implied_from_american(self, american_odds: int | float) -> float:
        """Convert American odds to implied probability (no vig)."""
        decimal = self.ev_calc.american_to_decimal(american_odds)
        return self.ev_calc.implied_prob(decimal)

    def _remove_vig(self, home_impl: float, away_impl: float) -> tuple[float, float]:
        """Normalize probabilities to remove bookmaker vig."""
        total = home_impl + away_impl
        return home_impl / total, away_impl / total

    def _market_implied_predict(self, game: dict) -> dict:
        home_odds = game.get("home_odds", -110)
        away_odds = game.get("away_odds", -110)

        home_impl = self._implied_from_american(home_odds)
        away_impl = self._implied_from_american(away_odds)
        home_fair, away_fair = self._remove_vig(home_impl, away_impl)

        home_prob = home_fair * (1 - MARKET_BLEND) + 0.5 * MARKET_BLEND
        away_prob = 1 - home_prob

        return {
            "home_team": game.get("home_team", ""),
            "away_team": game.get("away_team", ""),
            "home_win_prob": round(home_prob, 4),
            "away_win_prob": round(away_prob, 4),
            "source": "market_implied",
        }

    # ------------------------------------------------------------------
    # Internal: XGBoost model loading
    # ------------------------------------------------------------------

    def _load_xgb_models(self) -> None:
        """Load the XGBoost ML model + calibrator.  Sets self._xgb_models_loaded."""
        try:
            import xgboost as xgb  # noqa: PLC0415
            import joblib  # noqa: PLC0415

            ml_path = self._select_model_path("ML")
            if ml_path is None:
                return

            booster = xgb.Booster()
            booster.load_model(str(ml_path))
            self._xgb_ml = booster

            cal_path = ml_path.with_name(f"{ml_path.stem}_calibration.pkl")
            self._xgb_ml_calibrator = joblib.load(cal_path) if cal_path.exists() else None

            self._xgb_models_loaded = True
            logger.info("Loaded XGBoost ML model: %s", ml_path.name)
        except Exception as exc:
            logger.debug("XGBoost model load skipped: %s", exc)

    def _select_model_path(self, kind: str) -> Path | None:
        """Return the best model path for *kind* ('ML' or 'UO') by accuracy then mtime."""
        if not _MODEL_DIR.exists():
            return None
        candidates = list(_MODEL_DIR.glob(f"*{kind}*.json"))
        if not candidates:
            return None

        def _score(p: Path):
            m = _ACCURACY_RE.search(p.name)
            acc = float(m.group(1)) if m else 0.0
            return (p.stat().st_mtime, acc)

        return max(candidates, key=_score)

    # ------------------------------------------------------------------
    # Internal: XGBoost prediction pipeline
    # ------------------------------------------------------------------

    def _predict_xgb(
        self, home_team: str, away_team: str
    ) -> tuple[float, float] | None:
        """
        Build a feature vector from today's TeamData.sqlite and run the
        XGBoost ML model.

        Returns (home_win_prob, away_win_prob) or None if any step fails.
        """
        import sqlite3  # noqa: PLC0415
        import pandas as pd  # noqa: PLC0415
        import xgboost as xgb  # noqa: PLC0415

        team_df = self._get_latest_team_df()
        if team_df is None:
            logger.debug("No team data in TeamData.sqlite — using market-implied")
            return None

        index_map = self._get_team_index_map()
        if index_map is None:
            return None

        game_series = self._build_game_features(team_df, home_team, away_team, index_map)
        if game_series is None:
            logger.debug(
                "Could not build XGBoost feature vector for %s vs %s",
                home_team, away_team,
            )
            return None

        # Convert Series → single-row DataFrame; drop ID / date columns
        X = game_series.to_frame().T
        drop_cols = [c for c in X.columns if "TEAM_ID" in c or "Date" in c]
        X = X.drop(columns=drop_cols, errors="ignore")

        # Align columns to model's expected feature order
        fn = getattr(self._xgb_ml, "feature_names", None)
        if fn:
            available = [f for f in fn if f in X.columns]
            if not available:
                logger.debug("No overlapping features between game data and model")
                return None
            X = X[available]

        try:
            X = X.astype(float)
        except Exception:
            return None

        if self._xgb_ml_calibrator is not None:
            proba = self._xgb_ml_calibrator.predict_proba(X)
            home_prob = float(proba[0][1])  # class 1 = home win
        else:
            dmat = xgb.DMatrix(X)
            raw = self._xgb_ml.predict(dmat)
            home_prob = float(raw[0])

        home_prob = max(0.0, min(1.0, home_prob))
        return home_prob, 1.0 - home_prob

    def _get_latest_team_df(self):
        """
        Load the most recent date's team stats table from TeamData.sqlite.
        Returns a pandas DataFrame or None.
        """
        try:
            import sqlite3  # noqa: PLC0415
            import pandas as pd  # noqa: PLC0415

            if not _TEAMS_DB.exists():
                return None

            with sqlite3.connect(_TEAMS_DB) as con:
                cursor = con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
                tables = [row[0] for row in cursor.fetchall()]

            date_tables: list[datetime] = []
            for t in tables:
                try:
                    date_tables.append(datetime.strptime(t, "%Y-%m-%d"))
                except ValueError:
                    continue

            if not date_tables:
                return None

            latest = max(date_tables)
            table_name = latest.strftime("%Y-%m-%d")

            with sqlite3.connect(_TEAMS_DB) as con:
                return pd.read_sql_query(f'SELECT * FROM "{table_name}"', con)
        except Exception as exc:
            logger.debug("Failed to load team data from SQLite: %s", exc)
            return None

    def _get_team_index_map(self) -> dict | None:
        """Load team_index_current from the NBA-ML repo Utils."""
        try:
            if str(_NBA_ML_DIR) not in sys.path:
                sys.path.insert(0, str(_NBA_ML_DIR))
            from src.Utils.Dictionaries import team_index_current  # noqa: PLC0415
            return team_index_current
        except Exception as exc:
            logger.debug("Could not load team_index_current: %s", exc)
            return None

    def _build_game_features(
        self,
        team_df,
        home_team: str,
        away_team: str,
        index_map: dict,
    ):
        """
        Replicate Create_Games.build_game_features() locally to avoid
        importing from a directory with a hyphenated name.

        Returns a pandas Series or None.
        """
        try:
            home_index = index_map.get(home_team)
            away_index = index_map.get(away_team)
            if home_index is None or away_index is None:
                return None
            if len(team_df.index) != 30:
                return None

            import pandas as pd  # noqa: PLC0415
            home_series = team_df.iloc[home_index]
            away_series = team_df.iloc[away_index].rename(
                index={col: f"{col}.1" for col in team_df.columns}
            )
            return pd.concat([home_series, away_series])
        except Exception as exc:
            logger.debug("build_game_features failed: %s", exc)
            return None
