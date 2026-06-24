"""
Embedded WC 2018 and WC 2022 match results.

Source: public record match scorelines (FIFA/Wikipedia).
Outcome encoding:
  "W" = home team wins (including AET/penalties in knockout)
  "D" = draw (group stage only — knockout rounds never have "D")
  "L" = away team wins (including AET/penalties in knockout)

Elo overrides for teams NOT in data/wc_priors.json (WC 2026 field):
  Russia=1685, Peru=1810, Denmark=1835, Iceland=1767, Nigeria=1655,
  Costa Rica=1698, Serbia=1720, Korea Republic=1770, Poland=1780,
  Wales=1799, Cameroon=1625, Panama=1625 (also missing from priors as
  of some builds — override included where applicable).

Note: WCMatchModel.predict() mutates the input dict in place.
Always pass copies to the model; get_matches() returns fresh copies.
"""
from __future__ import annotations

from copy import deepcopy

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GROUP_STAGE = "GROUP_STAGE"
LAST_16 = "LAST_16"
QUARTER_FINALS = "QUARTER_FINALS"
SEMI_FINALS = "SEMI_FINALS"
THIRD_PLACE = "THIRD_PLACE"
FINAL = "FINAL"

KNOCKOUT_STAGES: frozenset[str] = frozenset({
    LAST_16, QUARTER_FINALS, SEMI_FINALS, THIRD_PLACE, FINAL
})

# ---------------------------------------------------------------------------
# Elo override values for teams not in wc_priors.json
# ---------------------------------------------------------------------------

_ELO: dict[str, int] = {
    # 2018 teams missing from current wc_priors.json
    "Russia": 1685,
    "Peru": 1810,
    "Denmark": 1835,
    "Iceland": 1767,
    "Nigeria": 1655,
    "Costa Rica": 1698,
    "Serbia": 1720,
    "Korea Republic": 1770,
    "Poland": 1780,
    # 2022 teams missing from current wc_priors.json
    "Wales": 1799,
    "Cameroon": 1625,
    # Also not in priors (WC 2026 did not qualify):
    "Iran": 1700,        # Iran IS in wc_priors.json — no override needed
    "Tunisia": 1650,     # Tunisia IS in wc_priors.json — no override needed
}

# Teams confirmed IN wc_priors.json (no override needed):
# Argentina, Australia, Belgium, Brazil, Canada, Colombia, Croatia, Ecuador,
# England, France, Germany, Ghana, Japan, Mexico, Morocco, Netherlands,
# Portugal, Qatar, Saudi Arabia, Senegal, South Korea (as "South Korea"),
# Spain, Switzerland, Tunisia, United States, Uruguay, Iran
# Note: wc_priors.json uses "South Korea" not "Korea Republic"
# so Korea Republic must always have home_elo_override / away_elo_override.


def _ov(team: str) -> int | None:
    """Return Elo override if team is not in wc_priors.json, else None."""
    # Teams in wc_priors.json (confirmed present):
    _IN_PRIORS = {
        "Algeria", "Argentina", "Australia", "Austria", "Belgium",
        "Bosnia-Herzegovina", "Brazil", "Canada", "Cape Verde Islands",
        "Colombia", "Congo DR", "Croatia", "Curacao", "Czechia",
        "Ecuador", "Egypt", "England", "France", "Germany", "Ghana",
        "Haiti", "Iran", "Iraq", "Ivory Coast", "Japan", "Jordan",
        "Mexico", "Morocco", "Netherlands", "New Zealand", "Norway",
        "Panama", "Paraguay", "Portugal", "Qatar", "Saudi Arabia",
        "Scotland", "Senegal", "South Africa", "South Korea", "Spain",
        "Sweden", "Switzerland", "Tunisia", "Turkey", "United States",
        "Uruguay", "Uzbekistan",
    }
    if team in _IN_PRIORS:
        return None
    return _ELO.get(team)


def _match(
    year: int,
    stage: str,
    group: str | None,
    home: str,
    away: str,
    hs: int,
    as_: int,
    outcome: str,
) -> dict:
    """Build a single match record with Elo overrides where needed."""
    record: dict = {
        "year": year,
        "stage": stage,
        "group": group,
        "home_team": home,
        "away_team": away,
        "home_score": hs,
        "away_score": as_,
        "outcome": outcome,
        "league": "wc",
    }
    ho = _ov(home)
    ao = _ov(away)
    if ho is not None:
        record["home_elo_override"] = ho
    if ao is not None:
        record["away_elo_override"] = ao
    return record


# ---------------------------------------------------------------------------
# WC 2018 Group Stage (48 matches)
# Group A: Russia, Saudi Arabia, Egypt, Uruguay
# Group B: Portugal, Spain, Morocco, Iran
# Group C: France, Australia, Peru, Denmark
# Group D: Argentina, Iceland, Croatia, Nigeria
# Group E: Brazil, Switzerland, Costa Rica, Serbia
# Group F: Germany, Mexico, Sweden, Korea Republic
# Group G: Belgium, Panama, Tunisia, England
# Group H: Poland, Senegal, Colombia, Japan
# ---------------------------------------------------------------------------

_WC_2018_GROUP: list[dict] = [
    # --- Group A ---
    _match(2018, GROUP_STAGE, "A", "Russia", "Saudi Arabia", 5, 0, "W"),
    _match(2018, GROUP_STAGE, "A", "Egypt", "Uruguay", 0, 1, "L"),
    _match(2018, GROUP_STAGE, "A", "Russia", "Egypt", 3, 0, "W"),
    _match(2018, GROUP_STAGE, "A", "Uruguay", "Saudi Arabia", 1, 0, "W"),
    _match(2018, GROUP_STAGE, "A", "Uruguay", "Russia", 3, 0, "W"),
    _match(2018, GROUP_STAGE, "A", "Saudi Arabia", "Egypt", 2, 1, "W"),

    # --- Group B ---
    _match(2018, GROUP_STAGE, "B", "Morocco", "Iran", 0, 1, "L"),
    _match(2018, GROUP_STAGE, "B", "Portugal", "Spain", 3, 3, "D"),
    _match(2018, GROUP_STAGE, "B", "Portugal", "Morocco", 1, 0, "W"),
    _match(2018, GROUP_STAGE, "B", "Iran", "Spain", 0, 1, "L"),
    _match(2018, GROUP_STAGE, "B", "Iran", "Portugal", 1, 1, "D"),
    _match(2018, GROUP_STAGE, "B", "Spain", "Morocco", 2, 2, "D"),

    # --- Group C ---
    _match(2018, GROUP_STAGE, "C", "France", "Australia", 2, 1, "W"),
    _match(2018, GROUP_STAGE, "C", "Peru", "Denmark", 0, 1, "L"),
    _match(2018, GROUP_STAGE, "C", "Denmark", "Australia", 1, 1, "D"),
    _match(2018, GROUP_STAGE, "C", "France", "Peru", 1, 0, "W"),
    _match(2018, GROUP_STAGE, "C", "Denmark", "France", 0, 0, "D"),
    _match(2018, GROUP_STAGE, "C", "Australia", "Peru", 0, 2, "L"),

    # --- Group D ---
    _match(2018, GROUP_STAGE, "D", "Argentina", "Iceland", 1, 1, "D"),
    _match(2018, GROUP_STAGE, "D", "Croatia", "Nigeria", 2, 0, "W"),
    _match(2018, GROUP_STAGE, "D", "Argentina", "Croatia", 0, 3, "L"),
    _match(2018, GROUP_STAGE, "D", "Nigeria", "Iceland", 2, 0, "W"),
    _match(2018, GROUP_STAGE, "D", "Argentina", "Nigeria", 2, 1, "W"),
    _match(2018, GROUP_STAGE, "D", "Iceland", "Croatia", 1, 2, "L"),

    # --- Group E ---
    _match(2018, GROUP_STAGE, "E", "Brazil", "Switzerland", 1, 1, "D"),
    _match(2018, GROUP_STAGE, "E", "Costa Rica", "Serbia", 0, 1, "L"),
    _match(2018, GROUP_STAGE, "E", "Brazil", "Costa Rica", 2, 0, "W"),
    _match(2018, GROUP_STAGE, "E", "Switzerland", "Serbia", 2, 1, "W"),
    _match(2018, GROUP_STAGE, "E", "Brazil", "Serbia", 2, 0, "W"),
    _match(2018, GROUP_STAGE, "E", "Switzerland", "Costa Rica", 2, 2, "D"),

    # --- Group F ---
    _match(2018, GROUP_STAGE, "F", "Germany", "Mexico", 0, 1, "L"),
    _match(2018, GROUP_STAGE, "F", "Sweden", "Korea Republic", 1, 0, "W"),
    _match(2018, GROUP_STAGE, "F", "Germany", "Sweden", 2, 1, "W"),
    _match(2018, GROUP_STAGE, "F", "Korea Republic", "Mexico", 1, 2, "L"),
    _match(2018, GROUP_STAGE, "F", "Germany", "Korea Republic", 0, 2, "L"),
    _match(2018, GROUP_STAGE, "F", "Mexico", "Sweden", 0, 3, "L"),

    # --- Group G ---
    _match(2018, GROUP_STAGE, "G", "Belgium", "Panama", 3, 0, "W"),
    _match(2018, GROUP_STAGE, "G", "Tunisia", "England", 1, 2, "L"),
    _match(2018, GROUP_STAGE, "G", "Belgium", "Tunisia", 5, 2, "W"),
    _match(2018, GROUP_STAGE, "G", "England", "Panama", 6, 1, "W"),
    _match(2018, GROUP_STAGE, "G", "England", "Belgium", 0, 1, "L"),
    _match(2018, GROUP_STAGE, "G", "Panama", "Tunisia", 1, 2, "L"),

    # --- Group H ---
    _match(2018, GROUP_STAGE, "H", "Poland", "Senegal", 1, 2, "L"),
    _match(2018, GROUP_STAGE, "H", "Colombia", "Japan", 1, 2, "L"),
    _match(2018, GROUP_STAGE, "H", "Japan", "Senegal", 2, 2, "D"),
    _match(2018, GROUP_STAGE, "H", "Poland", "Colombia", 0, 3, "L"),
    _match(2018, GROUP_STAGE, "H", "Japan", "Poland", 0, 1, "L"),
    _match(2018, GROUP_STAGE, "H", "Senegal", "Colombia", 0, 1, "L"),
]

assert len(_WC_2018_GROUP) == 48, f"Expected 48 2018 group matches, got {len(_WC_2018_GROUP)}"

# ---------------------------------------------------------------------------
# WC 2018 Knockout (16 matches)
# Outcome = winner of match (AET/penalties if applicable), never "D"
# ---------------------------------------------------------------------------

_WC_2018_KNOCKOUT: list[dict] = [
    # --- Round of 16 ---
    # France 4-3 Argentina (Kazan)
    _match(2018, LAST_16, None, "France", "Argentina", 4, 3, "W"),
    # Uruguay 2-1 Portugal
    _match(2018, LAST_16, None, "Uruguay", "Portugal", 2, 1, "W"),
    # Spain 1-1 (Russia won 4-3 on pens)
    _match(2018, LAST_16, None, "Spain", "Russia", 1, 1, "L"),   # Russia won
    # Croatia 1-1 (Croatia won 3-2 on pens vs Denmark)
    _match(2018, LAST_16, None, "Croatia", "Denmark", 1, 1, "W"),  # Croatia won
    # Brazil 2-0 Mexico
    _match(2018, LAST_16, None, "Brazil", "Mexico", 2, 0, "W"),
    # Belgium 3-2 Japan
    _match(2018, LAST_16, None, "Belgium", "Japan", 3, 2, "W"),
    # Sweden 1-0 Switzerland
    _match(2018, LAST_16, None, "Sweden", "Switzerland", 1, 0, "W"),
    # Colombia 1-1 (England won 4-3 on pens)
    _match(2018, LAST_16, None, "Colombia", "England", 1, 1, "L"),  # England won

    # --- Quarter-finals ---
    # Uruguay 0-2 France
    _match(2018, QUARTER_FINALS, None, "Uruguay", "France", 0, 2, "L"),
    # Brazil 1-2 Belgium
    _match(2018, QUARTER_FINALS, None, "Brazil", "Belgium", 1, 2, "L"),
    # Russia 2-2 (Croatia won 4-3 on pens)
    _match(2018, QUARTER_FINALS, None, "Russia", "Croatia", 2, 2, "L"),  # Croatia won
    # Sweden 0-2 England
    _match(2018, QUARTER_FINALS, None, "Sweden", "England", 0, 2, "L"),

    # --- Semi-finals ---
    # France 1-0 Belgium
    _match(2018, SEMI_FINALS, None, "France", "Belgium", 1, 0, "W"),
    # Croatia 2-1 England (AET)
    _match(2018, SEMI_FINALS, None, "Croatia", "England", 2, 1, "W"),

    # --- Third place ---
    # Belgium 2-0 England
    _match(2018, THIRD_PLACE, None, "Belgium", "England", 2, 0, "W"),

    # --- Final ---
    # France 4-2 Croatia
    _match(2018, FINAL, None, "France", "Croatia", 4, 2, "W"),
]

assert len(_WC_2018_KNOCKOUT) == 16, f"Expected 16 2018 knockout matches, got {len(_WC_2018_KNOCKOUT)}"

# ---------------------------------------------------------------------------
# WC 2022 Group Stage (48 matches)
# Group A: Qatar, Ecuador, Senegal, Netherlands
# Group B: England, Iran, USA, Wales
# Group C: Argentina, Saudi Arabia, Mexico, Poland
# Group D: France, Australia, Tunisia, Denmark
# Group E: Spain, Costa Rica, Germany, Japan
# Group F: Belgium, Canada, Morocco, Croatia
# Group G: Brazil, Serbia, Switzerland, Cameroon
# Group H: Portugal, Ghana, Uruguay, Korea Republic
# ---------------------------------------------------------------------------

_WC_2022_GROUP: list[dict] = [
    # --- Group A ---
    _match(2022, GROUP_STAGE, "A", "Qatar", "Ecuador", 0, 2, "L"),
    _match(2022, GROUP_STAGE, "A", "Senegal", "Netherlands", 0, 2, "L"),
    _match(2022, GROUP_STAGE, "A", "Qatar", "Senegal", 1, 3, "L"),
    _match(2022, GROUP_STAGE, "A", "Netherlands", "Ecuador", 1, 1, "D"),
    _match(2022, GROUP_STAGE, "A", "Netherlands", "Qatar", 2, 0, "W"),
    _match(2022, GROUP_STAGE, "A", "Ecuador", "Senegal", 1, 2, "L"),

    # --- Group B ---
    _match(2022, GROUP_STAGE, "B", "England", "Iran", 6, 2, "W"),
    _match(2022, GROUP_STAGE, "B", "United States", "Wales", 1, 1, "D"),
    _match(2022, GROUP_STAGE, "B", "Wales", "Iran", 0, 2, "L"),
    _match(2022, GROUP_STAGE, "B", "England", "United States", 0, 0, "D"),
    _match(2022, GROUP_STAGE, "B", "Wales", "England", 0, 3, "L"),
    _match(2022, GROUP_STAGE, "B", "Iran", "United States", 0, 1, "L"),

    # --- Group C ---
    _match(2022, GROUP_STAGE, "C", "Argentina", "Saudi Arabia", 1, 2, "L"),
    _match(2022, GROUP_STAGE, "C", "Mexico", "Poland", 0, 0, "D"),
    _match(2022, GROUP_STAGE, "C", "Poland", "Saudi Arabia", 2, 0, "W"),
    _match(2022, GROUP_STAGE, "C", "Argentina", "Mexico", 2, 0, "W"),
    _match(2022, GROUP_STAGE, "C", "Poland", "Argentina", 0, 2, "L"),
    _match(2022, GROUP_STAGE, "C", "Saudi Arabia", "Mexico", 1, 2, "L"),

    # --- Group D ---
    _match(2022, GROUP_STAGE, "D", "Denmark", "Tunisia", 0, 0, "D"),
    _match(2022, GROUP_STAGE, "D", "France", "Australia", 4, 1, "W"),
    _match(2022, GROUP_STAGE, "D", "Tunisia", "Australia", 0, 1, "L"),
    _match(2022, GROUP_STAGE, "D", "France", "Denmark", 2, 1, "W"),
    _match(2022, GROUP_STAGE, "D", "Australia", "Denmark", 1, 0, "W"),
    _match(2022, GROUP_STAGE, "D", "Tunisia", "France", 1, 0, "W"),

    # --- Group E ---
    _match(2022, GROUP_STAGE, "E", "Spain", "Costa Rica", 7, 0, "W"),
    _match(2022, GROUP_STAGE, "E", "Germany", "Japan", 1, 2, "L"),
    _match(2022, GROUP_STAGE, "E", "Japan", "Costa Rica", 0, 1, "L"),
    _match(2022, GROUP_STAGE, "E", "Spain", "Germany", 1, 1, "D"),
    _match(2022, GROUP_STAGE, "E", "Japan", "Spain", 2, 1, "W"),
    _match(2022, GROUP_STAGE, "E", "Costa Rica", "Germany", 2, 4, "L"),

    # --- Group F ---
    _match(2022, GROUP_STAGE, "F", "Morocco", "Croatia", 0, 0, "D"),
    _match(2022, GROUP_STAGE, "F", "Belgium", "Canada", 1, 0, "W"),
    _match(2022, GROUP_STAGE, "F", "Belgium", "Morocco", 0, 2, "L"),
    _match(2022, GROUP_STAGE, "F", "Croatia", "Canada", 4, 1, "W"),
    _match(2022, GROUP_STAGE, "F", "Croatia", "Belgium", 0, 0, "D"),
    _match(2022, GROUP_STAGE, "F", "Morocco", "Canada", 2, 1, "W"),

    # --- Group G ---
    _match(2022, GROUP_STAGE, "G", "Switzerland", "Cameroon", 1, 0, "W"),
    _match(2022, GROUP_STAGE, "G", "Brazil", "Serbia", 2, 0, "W"),
    _match(2022, GROUP_STAGE, "G", "Cameroon", "Serbia", 3, 3, "D"),
    _match(2022, GROUP_STAGE, "G", "Brazil", "Switzerland", 1, 0, "W"),
    _match(2022, GROUP_STAGE, "G", "Brazil", "Cameroon", 0, 1, "L"),
    _match(2022, GROUP_STAGE, "G", "Serbia", "Switzerland", 2, 3, "L"),

    # --- Group H ---
    _match(2022, GROUP_STAGE, "H", "Uruguay", "Korea Republic", 0, 0, "D"),
    _match(2022, GROUP_STAGE, "H", "Portugal", "Ghana", 3, 2, "W"),
    _match(2022, GROUP_STAGE, "H", "Korea Republic", "Ghana", 2, 3, "L"),
    _match(2022, GROUP_STAGE, "H", "Portugal", "Uruguay", 2, 0, "W"),
    _match(2022, GROUP_STAGE, "H", "Ghana", "Uruguay", 0, 2, "L"),
    _match(2022, GROUP_STAGE, "H", "Korea Republic", "Portugal", 2, 1, "W"),
]

assert len(_WC_2022_GROUP) == 48, f"Expected 48 2022 group matches, got {len(_WC_2022_GROUP)}"

# ---------------------------------------------------------------------------
# WC 2022 Knockout (16 matches)
# Outcome = winner (AET/pens), never "D"
# ---------------------------------------------------------------------------

_WC_2022_KNOCKOUT: list[dict] = [
    # --- Round of 16 ---
    # Netherlands 3-1 USA
    _match(2022, LAST_16, None, "Netherlands", "United States", 3, 1, "W"),
    # Argentina 2-1 Australia (AET: 2-1)
    _match(2022, LAST_16, None, "Argentina", "Australia", 2, 1, "W"),
    # France 3-1 Poland
    _match(2022, LAST_16, None, "France", "Poland", 3, 1, "W"),
    # England 3-0 Senegal
    _match(2022, LAST_16, None, "England", "Senegal", 3, 0, "W"),
    # Japan 1-1 (Croatia won 3-1 on pens)
    _match(2022, LAST_16, None, "Japan", "Croatia", 1, 1, "L"),   # Croatia won
    # Brazil 4-1 Korea Republic (AET: 4-1)
    _match(2022, LAST_16, None, "Brazil", "Korea Republic", 4, 1, "W"),
    # Morocco 0-0 (Morocco won 3-0 on pens vs Spain)
    _match(2022, LAST_16, None, "Morocco", "Spain", 0, 0, "W"),   # Morocco won
    # Portugal 6-1 Switzerland
    _match(2022, LAST_16, None, "Portugal", "Switzerland", 6, 1, "W"),

    # --- Quarter-finals ---
    # Croatia 1-1 (Croatia won 4-2 on pens vs Brazil)
    _match(2022, QUARTER_FINALS, None, "Croatia", "Brazil", 1, 1, "W"),  # Croatia won
    # Netherlands 2-2 (Argentina won 4-3 on pens)
    _match(2022, QUARTER_FINALS, None, "Netherlands", "Argentina", 2, 2, "L"),  # Argentina won
    # Morocco 1-0 Portugal
    _match(2022, QUARTER_FINALS, None, "Morocco", "Portugal", 1, 0, "W"),
    # England 1-2 France
    _match(2022, QUARTER_FINALS, None, "England", "France", 1, 2, "L"),

    # --- Semi-finals ---
    # Argentina 3-0 Croatia
    _match(2022, SEMI_FINALS, None, "Argentina", "Croatia", 3, 0, "W"),
    # France 2-0 Morocco
    _match(2022, SEMI_FINALS, None, "France", "Morocco", 2, 0, "W"),

    # --- Third place ---
    # Croatia 2-1 Morocco
    _match(2022, THIRD_PLACE, None, "Croatia", "Morocco", 2, 1, "W"),

    # --- Final ---
    # Argentina 3-3 (Argentina won 4-2 on pens vs France)
    _match(2022, FINAL, None, "Argentina", "France", 3, 3, "W"),  # Argentina won
]

assert len(_WC_2022_KNOCKOUT) == 16, f"Expected 16 2022 knockout matches, got {len(_WC_2022_KNOCKOUT)}"

# ---------------------------------------------------------------------------
# Combined dataset
# ---------------------------------------------------------------------------

WC_HISTORICAL: list[dict] = (
    _WC_2018_GROUP
    + _WC_2018_KNOCKOUT
    + _WC_2022_GROUP
    + _WC_2022_KNOCKOUT
)

assert len(WC_HISTORICAL) == 128, f"Expected 128 total matches, got {len(WC_HISTORICAL)}"


# ---------------------------------------------------------------------------
# Filter helper
# ---------------------------------------------------------------------------

def get_matches(year: int | None = None, stage: str | None = None) -> list[dict]:
    """
    Return a filtered copy of WC_HISTORICAL.

    Parameters
    ----------
    year : int | None
        Filter to a specific tournament year (2018 or 2022). None returns all.
    stage : str | None
        Filter to a specific stage (e.g. "GROUP_STAGE", "LAST_16"). None returns all.

    Returns
    -------
    list[dict]
        Fresh deep-copies of matching records. Mutating the returned dicts
        does NOT affect WC_HISTORICAL.
    """
    result = []
    for match in WC_HISTORICAL:
        if year is not None and match["year"] != year:
            continue
        if stage is not None and match["stage"] != stage:
            continue
        result.append(deepcopy(match))
    return result
