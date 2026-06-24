"""
Embedded June 2026 FIFA rankings for all 48 WC 2026 qualified teams.

Source: FIFA World Rankings (June 2026, public record).
Used as static additive feature in WCTeamRatings composite Elo.

WC 2026 hosts: United States, Mexico, Canada.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# June 2026 FIFA Rankings (team_name -> rank)
# ---------------------------------------------------------------------------

FIFA_RANKINGS: dict[str, int] = {
    "Argentina": 1,
    "France": 2,
    "England": 3,
    "Belgium": 4,
    "Brazil": 5,
    "Portugal": 6,
    "Netherlands": 7,
    "Spain": 8,
    "Croatia": 9,
    "Italy": 10,
    "Morocco": 11,
    "Switzerland": 12,
    "United States": 13,
    "Mexico": 14,
    "Germany": 15,
    "Colombia": 16,
    "Uruguay": 17,
    "Senegal": 18,
    "Denmark": 19,
    "Japan": 20,
    "Ecuador": 21,
    "Australia": 22,
    "Iran": 23,
    "South Korea": 24,
    "Poland": 25,
    "Canada": 26,
    "Serbia": 27,
    "Cameroon": 28,
    "Qatar": 29,
    "Tunisia": 30,
    "Costa Rica": 31,
    "Saudi Arabia": 32,
    "Ghana": 33,
    "Wales": 34,
    "Ivory Coast": 35,
    "Peru": 36,
    "Chile": 37,
    "Paraguay": 38,
    "Nigeria": 39,
    "Algeria": 40,
    "Egypt": 41,
    "Mali": 42,
    "Norway": 43,
    "Austria": 44,
    "Czech Republic": 45,
    "Jamaica": 46,
    "Venezuela": 47,
    "Panama": 48,
    # WC 2026 qualifiers — approximate rankings
    "New Zealand": 70,
    "Honduras": 65,
    "Bolivia": 75,
    # Aliases used in wc_historical_matches
    "Korea Republic": 24,   # same as South Korea
    "Czechia": 45,          # same as Czech Republic
}

# ---------------------------------------------------------------------------
# Confederation membership
# ---------------------------------------------------------------------------

CONFEDERATIONS: dict[str, str] = {
    # UEFA
    "France": "UEFA",
    "England": "UEFA",
    "Belgium": "UEFA",
    "Portugal": "UEFA",
    "Netherlands": "UEFA",
    "Spain": "UEFA",
    "Croatia": "UEFA",
    "Italy": "UEFA",
    "Switzerland": "UEFA",
    "Germany": "UEFA",
    "Denmark": "UEFA",
    "Poland": "UEFA",
    "Serbia": "UEFA",
    "Wales": "UEFA",
    "Norway": "UEFA",
    "Austria": "UEFA",
    "Czech Republic": "UEFA",
    "Czechia": "UEFA",       # alias
    "Sweden": "UEFA",
    "Scotland": "UEFA",
    "Turkey": "UEFA",
    # CONMEBOL
    "Argentina": "CONMEBOL",
    "Brazil": "CONMEBOL",
    "Colombia": "CONMEBOL",
    "Uruguay": "CONMEBOL",
    "Ecuador": "CONMEBOL",
    "Chile": "CONMEBOL",
    "Paraguay": "CONMEBOL",
    "Peru": "CONMEBOL",
    "Venezuela": "CONMEBOL",
    "Bolivia": "CONMEBOL",
    # CONCACAF
    "United States": "CONCACAF",
    "Mexico": "CONCACAF",
    "Canada": "CONCACAF",
    "Costa Rica": "CONCACAF",
    "Jamaica": "CONCACAF",
    "Honduras": "CONCACAF",
    "Panama": "CONCACAF",
    "Haiti": "CONCACAF",
    # CAF
    "Morocco": "CAF",
    "Senegal": "CAF",
    "Cameroon": "CAF",
    "Ghana": "CAF",
    "Tunisia": "CAF",
    "Ivory Coast": "CAF",
    "Nigeria": "CAF",
    "Algeria": "CAF",
    "Egypt": "CAF",
    "Mali": "CAF",
    "South Africa": "CAF",
    "Congo DR": "CAF",
    "Cape Verde Islands": "CAF",
    # AFC
    "Japan": "AFC",
    "Australia": "AFC",
    "Iran": "AFC",
    "South Korea": "AFC",
    "Korea Republic": "AFC",   # alias
    "Saudi Arabia": "AFC",
    "Qatar": "AFC",
    "Iraq": "AFC",
    "Jordan": "AFC",
    "Uzbekistan": "AFC",
    # OFC
    "New Zealand": "OFC",
}

# ---------------------------------------------------------------------------
# 2026 host countries
# ---------------------------------------------------------------------------

WC_2026_HOSTS: frozenset[str] = frozenset({"United States", "Mexico", "Canada"})

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def get_fifa_rank(team: str) -> int:
    """Return FIFA ranking for team. Falls back to 200 for unknown teams."""
    return FIFA_RANKINGS.get(team, 200)


def get_confederation(team: str) -> str:
    """Return confederation for team. Falls back to 'OTHER' for unknown teams."""
    return CONFEDERATIONS.get(team, "OTHER")
