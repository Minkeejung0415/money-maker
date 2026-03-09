"""
NBA Model wrapper — produces win probabilities and EV-scored bet opportunities.

Primary implementation: implied-probability calibration from market odds,
adjusted with a simple Elo-style regression toward 50%.

Optional: delegates to NBA-Machine-Learning-Sports-Betting XGBoost/NN models
when the library and its dependencies (tensorflow, pandas) are available.
"""
import logging
from alpha.engines.sports.ev_calculator import EVCalculator

logger = logging.getLogger(__name__)

# Elo regression factor: blend market-implied prob with 0.5
# 0.0 = trust market fully, 1.0 = always predict 50/50
MARKET_BLEND = 0.15


class NBAModel:
    def __init__(self, min_edge: float = 0.04, kelly_fraction: float = 0.25):
        self.ev_calc = EVCalculator(min_edge=min_edge)
        self._kelly_fraction = kelly_fraction
        self._nba_ml_available = self._try_load_nba_ml()

    def _try_load_nba_ml(self) -> bool:
        """Attempt to load NBA-ML library; return False if unavailable."""
        try:
            import sys
            sys.path.insert(0, "NBA-Machine-Learning-Sports-Betting")
            from src.Predict import XGBoost_Runner  # noqa: F401
            return True
        except Exception:
            return False

    def _implied_from_american(self, american_odds: int | float) -> float:
        """Convert American odds to implied probability (no vig)."""
        decimal = self.ev_calc.american_to_decimal(american_odds)
        return self.ev_calc.implied_prob(decimal)

    def _remove_vig(self, home_impl: float, away_impl: float) -> tuple[float, float]:
        """Normalize probabilities to remove bookmaker vig."""
        total = home_impl + away_impl
        return home_impl / total, away_impl / total

    def predict(self, game: dict) -> dict:
        """
        Estimate win probabilities for a game.

        Uses market-implied probabilities blended toward 50/50 as a
        lightweight calibration (reduces overconfidence in heavy favorites).
        """
        home_odds = game.get("home_odds", -110)
        away_odds = game.get("away_odds", -110)

        home_impl = self._implied_from_american(home_odds)
        away_impl = self._implied_from_american(away_odds)
        home_fair, away_fair = self._remove_vig(home_impl, away_impl)

        # Blend toward 50/50 (Elo regression)
        home_prob = home_fair * (1 - MARKET_BLEND) + 0.5 * MARKET_BLEND
        away_prob = 1 - home_prob

        return {
            "home_team": game.get("home_team", ""),
            "away_team": game.get("away_team", ""),
            "home_win_prob": round(home_prob, 4),
            "away_win_prob": round(away_prob, 4),
            "source": "market_implied",
        }

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
