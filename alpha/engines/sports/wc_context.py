"""
wc_context.py — Context features for WC 2026 match prediction.

Provides:
    - VenueInfo: WC 2026 host city/stadium data
    - MatchContext: computed context features for a matchup
    - ContextEngine: computes MatchContext from schedule + team origins

CONTEXT-01: Days rest and expected-starter minutes (7 and 14 day windows)
CONTEXT-02: Intercontinental travel distance, time zones, east/west direction
CONTEXT-03: Venue context — all 2026 host cities with altitude, roof, kick-off
CONTEXT-04: Context features regularized more heavily than team/player features
             (enforced via CONTEXT_REGULARIZATION vs TEAM_REGULARIZATION weights)

All 2026 WC host cities are embedded (15 cities: 11 US, 2 Canada, 2 Mexico).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Optional


# ---------------------------------------------------------------------------
# WC 2026 venue data (CONTEXT-03)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VenueInfo:
    """
    Stadium and city context for a WC 2026 match venue.

    Attributes
    ----------
    name : str
        Stadium name.
    city : str
        Host city (key for lookup in VENUE_DATA).
    country : str
        Host country.
    latitude : float
        Venue latitude (decimal degrees, positive = N).
    longitude : float
        Venue longitude (decimal degrees, positive = E).
    altitude_m : float
        Altitude above sea level in metres.
    has_roof : bool
        True if venue has a (retractable) roof.
    utc_offset : int
        UTC offset in hours for the local timezone.
    """
    name: str
    city: str
    country: str
    latitude: float
    longitude: float
    altitude_m: float
    has_roof: bool
    utc_offset: int  # standard (non-DST) UTC offset


# All 15 WC 2026 host cities with verified venue data
VENUE_DATA: dict[str, VenueInfo] = {
    # --- United States (11 cities) ---
    "New York": VenueInfo(
        name="MetLife Stadium", city="New York", country="USA",
        latitude=40.81, longitude=-74.07, altitude_m=5, has_roof=False, utc_offset=-5,
    ),
    "Los Angeles": VenueInfo(
        name="SoFi Stadium", city="Los Angeles", country="USA",
        latitude=33.95, longitude=-118.34, altitude_m=82, has_roof=True, utc_offset=-8,
    ),
    "San Francisco": VenueInfo(
        name="Levi's Stadium", city="San Francisco", country="USA",
        latitude=37.40, longitude=-121.97, altitude_m=15, has_roof=False, utc_offset=-8,
    ),
    "Dallas": VenueInfo(
        name="AT&T Stadium", city="Dallas", country="USA",
        latitude=32.75, longitude=-97.09, altitude_m=175, has_roof=True, utc_offset=-6,
    ),
    "Atlanta": VenueInfo(
        name="Mercedes-Benz Stadium", city="Atlanta", country="USA",
        latitude=33.76, longitude=-84.40, altitude_m=260, has_roof=True, utc_offset=-5,
    ),
    "Seattle": VenueInfo(
        name="Lumen Field", city="Seattle", country="USA",
        latitude=47.60, longitude=-122.33, altitude_m=6, has_roof=False, utc_offset=-8,
    ),
    "Boston": VenueInfo(
        name="Gillette Stadium", city="Boston", country="USA",
        latitude=42.09, longitude=-71.26, altitude_m=33, has_roof=False, utc_offset=-5,
    ),
    "Miami": VenueInfo(
        name="Hard Rock Stadium", city="Miami", country="USA",
        latitude=25.96, longitude=-80.24, altitude_m=2, has_roof=False, utc_offset=-5,
    ),
    "Kansas City": VenueInfo(
        name="Arrowhead Stadium", city="Kansas City", country="USA",
        latitude=39.05, longitude=-94.48, altitude_m=270, has_roof=False, utc_offset=-6,
    ),
    "Philadelphia": VenueInfo(
        name="Lincoln Financial Field", city="Philadelphia", country="USA",
        latitude=39.90, longitude=-75.17, altitude_m=8, has_roof=False, utc_offset=-5,
    ),
    "Houston": VenueInfo(
        name="NRG Stadium", city="Houston", country="USA",
        latitude=29.68, longitude=-95.41, altitude_m=13, has_roof=True, utc_offset=-6,
    ),
    # --- Canada (2 cities) ---
    "Toronto": VenueInfo(
        name="BMO Field", city="Toronto", country="Canada",
        latitude=43.63, longitude=-79.42, altitude_m=76, has_roof=False, utc_offset=-5,
    ),
    "Vancouver": VenueInfo(
        name="BC Place", city="Vancouver", country="Canada",
        latitude=49.28, longitude=-123.11, altitude_m=1, has_roof=True, utc_offset=-8,
    ),
    # --- Mexico (2 cities) ---
    "Mexico City": VenueInfo(
        name="Estadio Azteca", city="Mexico City", country="Mexico",
        latitude=19.30, longitude=-99.15, altitude_m=2240, has_roof=False, utc_offset=-6,
    ),
    "Guadalajara": VenueInfo(
        name="Estadio Akron", city="Guadalajara", country="Mexico",
        latitude=20.69, longitude=-103.47, altitude_m=1556, has_roof=False, utc_offset=-6,
    ),
    "Monterrey": VenueInfo(
        name="Estadio BBVA", city="Monterrey", country="Mexico",
        latitude=25.67, longitude=-100.47, altitude_m=538, has_roof=False, utc_offset=-6,
    ),
}

# ---------------------------------------------------------------------------
# Regularization weights — CONTEXT-04
# ---------------------------------------------------------------------------

# Context features are regularized MORE heavily (smaller effective weights)
# than team ratings. These multipliers are applied on top of any model
# coefficients to enforce the constraint CONTEXT-04.
CONTEXT_REGULARIZATION: dict[str, float] = {
    "home_days_rest": 0.008,
    "away_days_rest": 0.008,
    "home_starter_min_7d": 0.005,
    "away_starter_min_7d": 0.005,
    "home_starter_min_14d": 0.004,
    "away_starter_min_14d": 0.004,
    "home_travel_km": 0.003,
    "away_travel_km": 0.003,
    "home_time_zones": 0.006,
    "away_time_zones": 0.006,
    "venue_altitude_m": 0.010,
    "venue_has_roof": 0.005,
    "kickoff_local_hour": 0.004,
}

TEAM_RATING_REGULARIZATION: dict[str, float] = {
    "elo_diff": 0.120,
    "xg_attack": 0.090,
    "xg_defense": 0.090,
    "fifa_sum": 0.050,
    "host_flag": 0.060,
}

# Max regularization weight for any context feature (upper bound for CONTEXT-04 test)
_CONTEXT_MAX_WEIGHT: float = max(CONTEXT_REGULARIZATION.values())
# Min regularization weight for team features (lower bound for CONTEXT-04 test)
_TEAM_MIN_WEIGHT: float = min(TEAM_RATING_REGULARIZATION.values())


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class MatchContext:
    """
    Context features for a WC 2026 match.

    Attributes
    ----------
    home_days_rest : int
        Days since home team's last match (-1 if unknown).
    away_days_rest : int
    home_starter_minutes_7d : float
        Cumulative match-minutes played by expected starters in last 7 days.
    away_starter_minutes_7d : float
    home_starter_minutes_14d : float
    away_starter_minutes_14d : float
    home_travel_km : float
        Great-circle distance from team's home country to venue (km).
    away_travel_km : float
    home_time_zones : int
        Absolute number of time zones crossed by home team.
    away_time_zones : int
    travel_direction : str
        "east", "west", or "same" (based on away team travel direction).
    venue_altitude_m : float
        Venue altitude above sea level (metres).
    venue_has_roof : bool
    kickoff_local_hour : int
        Kick-off time in venue's local hour (0–23).
    venue_city : str
    """
    home_days_rest: int = -1
    away_days_rest: int = -1
    home_starter_minutes_7d: float = 0.0
    away_starter_minutes_7d: float = 0.0
    home_starter_minutes_14d: float = 0.0
    away_starter_minutes_14d: float = 0.0
    home_travel_km: float = 0.0
    away_travel_km: float = 0.0
    home_time_zones: int = 0
    away_time_zones: int = 0
    travel_direction: str = "same"
    venue_altitude_m: float = 0.0
    venue_has_roof: bool = False
    kickoff_local_hour: int = 20
    venue_city: str = ""

    def to_feature_dict(self) -> dict[str, float]:
        """Return context features as a numeric dict (floats, booleans cast to 0/1)."""
        return {
            "home_days_rest": float(self.home_days_rest),
            "away_days_rest": float(self.away_days_rest),
            "home_starter_min_7d": self.home_starter_minutes_7d,
            "away_starter_min_7d": self.away_starter_minutes_7d,
            "home_starter_min_14d": self.home_starter_minutes_14d,
            "away_starter_min_14d": self.away_starter_minutes_14d,
            "home_travel_km": self.home_travel_km,
            "away_travel_km": self.away_travel_km,
            "home_time_zones": float(self.home_time_zones),
            "away_time_zones": float(self.away_time_zones),
            "venue_altitude_m": self.venue_altitude_m,
            "venue_has_roof": float(self.venue_has_roof),
            "kickoff_local_hour": float(self.kickoff_local_hour),
        }


# ---------------------------------------------------------------------------
# Context engine
# ---------------------------------------------------------------------------

class ContextEngine:
    """
    Compute MatchContext features from match schedule and team origin data.

    Parameters
    ----------
    venues : dict[str, VenueInfo]
        Venue lookup by city name. Defaults to VENUE_DATA (all 2026 cities).
    """

    def __init__(self, venues: Optional[dict[str, VenueInfo]] = None) -> None:
        self._venues: dict[str, VenueInfo] = venues if venues is not None else VENUE_DATA

    def compute(
        self,
        venue_city: str,
        match_date: date,
        kickoff_utc_hour: int = 20,
        home_last_match_date: Optional[date] = None,
        away_last_match_date: Optional[date] = None,
        home_starter_min_7d: float = 0.0,
        away_starter_min_7d: float = 0.0,
        home_starter_min_14d: float = 0.0,
        away_starter_min_14d: float = 0.0,
        home_origin_lat: Optional[float] = None,
        home_origin_lon: Optional[float] = None,
        away_origin_lat: Optional[float] = None,
        away_origin_lon: Optional[float] = None,
    ) -> MatchContext:
        """
        Compute MatchContext for a match.

        Parameters
        ----------
        venue_city : str
            Host city name (must be in supported_cities()).
        match_date : date
            Match date for days-rest calculation.
        kickoff_utc_hour : int
            Kick-off hour in UTC (default 20 = 8pm UTC).
        home_last_match_date : date, optional
            Date of home team's last match. None = unknown.
        away_last_match_date : date, optional
        home_starter_min_7d : float
            Minutes played by home starters in prior 7 days.
        away_starter_min_7d : float
        home_starter_min_14d : float
        away_starter_min_14d : float
        home_origin_lat, home_origin_lon : float, optional
            Home team's origin coordinates (e.g. capital city). None = unknown.
        away_origin_lat, away_origin_lon : float, optional

        Returns
        -------
        MatchContext
        """
        venue = self._venues.get(venue_city)
        if venue is None:
            raise ValueError(
                f"Unknown venue city '{venue_city}'. "
                f"Supported: {sorted(self._venues)}"
            )

        # CONTEXT-01: days rest
        home_rest = self._days_rest(home_last_match_date, match_date)
        away_rest = self._days_rest(away_last_match_date, match_date)

        # CONTEXT-02: travel
        if home_origin_lat is not None and home_origin_lon is not None:
            home_km = _haversine_km(home_origin_lat, home_origin_lon,
                                    venue.latitude, venue.longitude)
            home_tz = abs(round((home_origin_lon - venue.longitude) / 15))
        else:
            home_km = 0.0
            home_tz = 0

        if away_origin_lat is not None and away_origin_lon is not None:
            away_km = _haversine_km(away_origin_lat, away_origin_lon,
                                    venue.latitude, venue.longitude)
            away_tz = abs(round((away_origin_lon - venue.longitude) / 15))
            # East/west direction for away team
            lon_delta = venue.longitude - away_origin_lon
            if abs(lon_delta) < 15:
                direction = "same"
            elif lon_delta > 0:
                direction = "east"
            else:
                direction = "west"
        else:
            away_km = 0.0
            away_tz = 0
            direction = "same"

        # CONTEXT-03: kick-off in local time
        kickoff_local = (kickoff_utc_hour + venue.utc_offset) % 24

        return MatchContext(
            home_days_rest=home_rest,
            away_days_rest=away_rest,
            home_starter_minutes_7d=home_starter_min_7d,
            away_starter_minutes_7d=away_starter_min_7d,
            home_starter_minutes_14d=home_starter_min_14d,
            away_starter_minutes_14d=away_starter_min_14d,
            home_travel_km=home_km,
            away_travel_km=away_km,
            home_time_zones=home_tz,
            away_time_zones=away_tz,
            travel_direction=direction,
            venue_altitude_m=venue.altitude_m,
            venue_has_roof=venue.has_roof,
            kickoff_local_hour=kickoff_local,
            venue_city=venue_city,
        )

    def get_venue(self, city: str) -> VenueInfo:
        """Return VenueInfo for a city. Raises ValueError if not found."""
        if city not in self._venues:
            raise ValueError(f"Unknown venue city: '{city}'")
        return self._venues[city]

    def supported_cities(self) -> list[str]:
        """Return sorted list of all supported WC 2026 host cities."""
        return sorted(self._venues.keys())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _days_rest(last_match: Optional[date], current_match: date) -> int:
        """Return days since last match, or -1 if unknown."""
        if last_match is None:
            return -1
        delta = (current_match - last_match).days
        return max(0, delta)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance between two lat/lon points in km."""
    R = 6371.0  # Earth radius km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# Expected WC 2026 host cities (for validation)
WC_2026_HOST_CITIES: frozenset[str] = frozenset(VENUE_DATA.keys())
