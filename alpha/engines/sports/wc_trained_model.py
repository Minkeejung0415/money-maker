"""Trained international-match model for World Cup 1X2 probabilities."""
from __future__ import annotations

import math
import pickle
from pathlib import Path
from typing import Any

from alpha.engines.sports.ev_calculator import EVCalculator
from alpha.engines.sports.wc_model import KNOCKOUT_STAGES

FEATURE_NAMES: tuple[str, ...] = (
    "elo_diff",
    "neutral",
    "home_host",
    "away_host",
    "is_world_cup",
    "is_qualifier",
    "is_friendly",
    "is_major_tournament",
)

TEAM_ALIASES = {
    "USA": "United States",
    "USMNT": "United States",
    "DR Congo": "Congo DR",
    "Democratic Republic of Congo": "Congo DR",
    "Congo Democratic Republic": "Congo DR",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Cape Verde": "Cape Verde Islands",
}


def normalize_team_name(team: str) -> str:
    """Normalize common international team-name variants."""
    value = str(team or "").strip()
    return TEAM_ALIASES.get(value, value)


def tournament_flags(tournament: str) -> dict[str, float]:
    """Convert a tournament label into compact model features."""
    label = str(tournament or "").lower()
    is_world_cup = "fifa world cup" in label and "qualification" not in label
    is_qualifier = "qualification" in label or "qualifying" in label or "qualifier" in label
    is_friendly = "friendly" in label
    is_major = any(
        token in label
        for token in (
            "uefa euro",
            "copa américa",
            "copa america",
            "africa cup",
            "asian cup",
            "concacaf gold cup",
            "nations league",
            "confederations cup",
        )
    )
    return {
        "is_world_cup": float(is_world_cup),
        "is_qualifier": float(is_qualifier),
        "is_friendly": float(is_friendly),
        "is_major_tournament": float(is_major),
    }


def build_runtime_features(
    home_team: str,
    away_team: str,
    *,
    ratings: dict[str, float],
    tournament: str = "FIFA World Cup",
    neutral: bool = True,
    country: str = "",
) -> dict[str, float]:
    """Build inference features from trained Elo state and fixture context."""
    home = normalize_team_name(home_team)
    away = normalize_team_name(away_team)
    home_elo = float(ratings.get(home, 1500.0))
    away_elo = float(ratings.get(away, 1500.0))
    host_country = normalize_team_name(country)
    features = {
        "elo_diff": home_elo - away_elo,
        "neutral": float(bool(neutral)),
        "home_host": float(bool(host_country) and host_country == home),
        "away_host": float(bool(host_country) and host_country == away),
    }
    features.update(tournament_flags(tournament))
    return features


class WCTrainedInternationalModel:
    """Artifact-backed multinomial model trained on international results."""

    def __init__(
        self,
        artifact_path: str | Path = "alpha/models/wc_international_1x2.pkl",
        min_edge: float = 0.04,
    ) -> None:
        path = Path(artifact_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise FileNotFoundError(f"WC trained artifact missing: {path}")
        with path.open("rb") as handle:
            self._artifact: dict[str, Any] = pickle.load(handle)
        self.ev_calc = EVCalculator(min_edge=min_edge)
        self.model_name = str(self._artifact.get("model_id", "wc_international_1x2_v1"))

    @property
    def ratings(self) -> dict[str, float]:
        return dict(self._artifact.get("ratings", {}))

    def predict_90_minute(self, game: dict) -> dict:
        """Predict regulation-time H/D/A probabilities."""
        if game.get("league") != "wc":
            raise ValueError("WC trained model only accepts league='wc'")

        features = build_runtime_features(
            game.get("home_team", ""),
            game.get("away_team", ""),
            ratings=self._artifact.get("ratings", {}),
            tournament=str(game.get("tournament", "FIFA World Cup")),
            neutral=bool(game.get("neutral", True)),
            country=str(game.get("country", "")),
        )
        x = [[features[name] for name in FEATURE_NAMES]]
        model = self._artifact["model"]
        probs = model.predict_proba(x)[0]
        classes = list(self._artifact.get("classes", model.classes_))
        prob_by_class = {str(label): float(prob) for label, prob in zip(classes, probs)}
        p_home = prob_by_class.get("H", 0.0)
        p_draw = prob_by_class.get("D", 0.0)
        p_away = prob_by_class.get("A", 0.0)
        total = max(p_home + p_draw + p_away, 1e-9)
        p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total

        result = dict(game)
        result["win_prob"] = round(p_home, 4)
        result["draw_prob"] = round(p_draw, 4)
        result["loss_prob"] = round(p_away, 4)
        result["model_name"] = self.model_name
        result["market_type"] = "90_minute"
        result["knockout"] = result.get("stage") in KNOCKOUT_STAGES
        result["elo_diff"] = round(float(features["elo_diff"]), 2)
        result["home_elo"] = round(float(self._artifact.get("ratings", {}).get(normalize_team_name(game.get("home_team", "")), 1500.0)))
        result["away_elo"] = round(float(self._artifact.get("ratings", {}).get(normalize_team_name(game.get("away_team", "")), 1500.0)))
        result["elo_edge"] = self._elo_edge(result)
        return result

    def predict(self, game: dict) -> dict:
        """Predict scanner-default market, suppressing draw for knockout advance."""
        result = self.predict_90_minute(game)
        if result.get("stage") in KNOCKOUT_STAGES:
            h = float(result["win_prob"])
            a = float(result["loss_prob"])
            total = max(h + a, 1e-9)
            result["win_prob"] = round(h / total, 4)
            result["draw_prob"] = 0.0
            result["loss_prob"] = round(a / total, 4)
            result["market_type"] = "advance"
        return result

    def _elo_edge(self, game: dict) -> bool:
        home_odds = game.get("home_odds", -110)
        try:
            market_implied = self.ev_calc.implied_prob(self.ev_calc.american_to_decimal(home_odds))
        except Exception:
            return False
        return math.isfinite(market_implied) and abs(float(game["win_prob"]) - market_implied) > 0.05
