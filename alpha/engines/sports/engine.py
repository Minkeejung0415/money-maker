"""
Sports Engine — main entry point for the sports betting vertical.
Ties together: NBAModel → EVCalculator → KellySizer → bet list.
"""
import logging
from alpha.engines.sports.nba_model import NBAModel
from alpha.engines.sports.ev_calculator import EVCalculator
from alpha.engines.sports.kelly import KellySizer

logger = logging.getLogger(__name__)


class SportsEngine:
    def __init__(
        self,
        bankroll: float = 10_000.0,
        min_edge: float = 0.04,
        kelly_fraction: float = 0.25,
        max_stake_pct: float = 0.05,
    ):
        self.bankroll = bankroll
        self.nba_model = NBAModel(min_edge=min_edge)
        self.ev_calc = EVCalculator(min_edge=min_edge)
        self.kelly = KellySizer(kelly_fraction=kelly_fraction, max_stake_pct=max_stake_pct)

    def _route_game(self, game: dict) -> dict:
        """Dispatch to the right model based on sport/league."""
        league = game.get("league", "").lower()
        if league == "nba":
            return self.nba_model.evaluate_bet(game)
        # Default: use NBA model for all basketball; extend for other sports
        return self.nba_model.evaluate_bet(game)

    def run(
        self,
        games: list[dict],
        position_scalar: float = 1.0,
    ) -> dict:
        """
        Evaluate all games, size bets with Kelly, apply position scalar.

        Args:
            games: List of game dicts with odds and team info.
            position_scalar: From MacroFilter (1.0 = full, 0.25 = risk-off).

        Returns:
            {bets, total_stake, regime_scalar}
        """
        bets = []
        for game in games:
            try:
                opportunity = self._route_game(game)
                if opportunity["bet_side"] == "no_bet":
                    continue

                stake = self.kelly.bet_size(
                    win_prob=opportunity["model_prob"],
                    decimal_odds=opportunity["decimal_odds"],
                    bankroll=self.bankroll,
                )
                stake_scaled = round(stake * position_scalar, 2)

                bets.append({
                    **opportunity,
                    "home_team": game.get("home_team", ""),
                    "away_team": game.get("away_team", ""),
                    "league": game.get("league", ""),
                    "stake": stake_scaled,
                })
            except Exception as e:
                logger.warning(f"Failed to evaluate game: {e}")

        total_stake = round(sum(b["stake"] for b in bets), 2)

        return {
            "bets": bets,
            "total_stake": total_stake,
            "regime_scalar": position_scalar,
        }
