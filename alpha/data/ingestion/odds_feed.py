from alpha.config.settings import Settings


class OddsIngester:
    """
    Wrapper around OddsHarvester to standardize odds data
    into the Alpha Terminal's storage schema.
    """

    def __init__(self):
        self.settings = Settings()

    def _build_params(self, sport: str, markets: list[str]) -> dict:
        return {"sport": sport, "markets": markets}

    def _parse_row(self, raw: dict, sport: str, league: str) -> dict:
        home = raw.get("home_team", "")
        away = raw.get("away_team", "")
        return {
            "sport": sport,
            "league": league,
            "event": f"{home} vs {away}",
            "market": raw.get("market", ""),
            "book": raw.get("book", ""),
            "odds_home": raw.get("odds_home"),
            "odds_away": raw.get("odds_away"),
            "odds_draw": raw.get("odds_draw"),
        }

    def scrape_upcoming(self, sport: str, league: str, markets: list[str]) -> list[dict]:
        """
        Calls OddsHarvester CLI programmatically.
        Returns parsed odds rows ready for AlphaDB.insert_odds().
        """
        try:
            from oddsharvester.core.scraper import scrape_upcoming
            raw_rows = scrape_upcoming(sport=sport, markets=markets)
            return [self._parse_row(r, sport, league) for r in raw_rows]
        except ImportError:
            # OddsHarvester not available; return empty (for tests)
            return []
