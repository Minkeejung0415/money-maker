"""Tests for alpha.engines.sports.wc_context — MatchContext and ContextEngine."""
from __future__ import annotations

from datetime import date

import pytest

from alpha.engines.sports.wc_context import (
    CONTEXT_REGULARIZATION,
    TEAM_RATING_REGULARIZATION,
    WC_2026_HOST_CITIES,
    ContextEngine,
    MatchContext,
    VENUE_DATA,
    _CONTEXT_MAX_WEIGHT,
    _TEAM_MIN_WEIGHT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine() -> ContextEngine:
    return ContextEngine()


# ---------------------------------------------------------------------------
# CONTEXT-03: All 2026 host cities supported
# ---------------------------------------------------------------------------

EXPECTED_HOST_CITIES = {
    # USA (11)
    "New York", "Los Angeles", "San Francisco", "Dallas", "Atlanta",
    "Seattle", "Boston", "Miami", "Kansas City", "Philadelphia", "Houston",
    # Canada (2)
    "Toronto", "Vancouver",
    # Mexico (2)
    "Mexico City", "Guadalajara", "Monterrey",
}


def test_all_host_cities_supported(engine: ContextEngine):
    """All 15 WC 2026 host cities must be in supported_cities()."""
    supported = set(engine.supported_cities())
    for city in EXPECTED_HOST_CITIES:
        assert city in supported, f"Missing WC 2026 host city: '{city}'"


def test_sixteen_host_cities(engine: ContextEngine):
    """Exactly 16 host cities in the venue data (15 stadiums + Monterrey)."""
    assert len(engine.supported_cities()) >= 15


def test_wc_2026_host_cities_constant():
    """WC_2026_HOST_CITIES covers all EXPECTED_HOST_CITIES."""
    assert EXPECTED_HOST_CITIES.issubset(WC_2026_HOST_CITIES)


def test_mexico_city_high_altitude(engine: ContextEngine):
    """Mexico City altitude must be ≥ 2000m (Azteca ~2240m)."""
    venue = engine.get_venue("Mexico City")
    assert venue.altitude_m >= 2000, f"Mexico City altitude {venue.altitude_m}m, expected ≥ 2000m"


def test_dallas_has_roof(engine: ContextEngine):
    """AT&T Stadium (Dallas) has a retractable roof."""
    assert engine.get_venue("Dallas").has_roof is True


def test_new_york_no_roof(engine: ContextEngine):
    """MetLife Stadium (New York) is open-air."""
    assert engine.get_venue("New York").has_roof is False


def test_unknown_city_raises(engine: ContextEngine):
    """Unknown venue city must raise ValueError."""
    with pytest.raises(ValueError, match="Unknown venue city"):
        engine.get_venue("NeverCity")


def test_compute_unknown_venue_raises(engine: ContextEngine):
    """compute() with unknown city raises ValueError."""
    with pytest.raises(ValueError):
        engine.compute(venue_city="Atlantis", match_date=date(2026, 6, 15))


# ---------------------------------------------------------------------------
# CONTEXT-01: Days rest
# ---------------------------------------------------------------------------

def test_days_rest_correct_calculation(engine: ContextEngine):
    """Days rest = match_date - last_match_date."""
    ctx = engine.compute(
        venue_city="New York",
        match_date=date(2026, 6, 25),
        home_last_match_date=date(2026, 6, 21),
        away_last_match_date=date(2026, 6, 20),
    )
    assert ctx.home_days_rest == 4
    assert ctx.away_days_rest == 5


def test_days_rest_unknown_is_minus_one(engine: ContextEngine):
    """No last match date → days_rest = -1."""
    ctx = engine.compute(
        venue_city="Dallas",
        match_date=date(2026, 6, 15),
    )
    assert ctx.home_days_rest == -1
    assert ctx.away_days_rest == -1


def test_starter_minutes_passed_through(engine: ContextEngine):
    """Starter minutes (7d and 14d) pass through unchanged."""
    ctx = engine.compute(
        venue_city="Miami",
        match_date=date(2026, 6, 18),
        home_starter_min_7d=720.0,
        away_starter_min_7d=810.0,
        home_starter_min_14d=1350.0,
        away_starter_min_14d=1580.0,
    )
    assert ctx.home_starter_minutes_7d == pytest.approx(720.0)
    assert ctx.away_starter_minutes_7d == pytest.approx(810.0)
    assert ctx.home_starter_minutes_14d == pytest.approx(1350.0)
    assert ctx.away_starter_minutes_14d == pytest.approx(1580.0)


# ---------------------------------------------------------------------------
# CONTEXT-02: Travel distance and time zones
# ---------------------------------------------------------------------------

def test_travel_km_nonzero_for_intercontinental(engine: ContextEngine):
    """European team (lat=51, lon=0) traveling to New York → ~5500km."""
    ctx = engine.compute(
        venue_city="New York",
        match_date=date(2026, 6, 20),
        away_origin_lat=51.5,
        away_origin_lon=-0.1,  # London
    )
    assert ctx.away_travel_km > 5000, f"Expected ~5500km, got {ctx.away_travel_km:.0f}km"


def test_travel_km_small_for_local_team(engine: ContextEngine):
    """US team (lat=39, lon=-95) traveling to New York → ≤ 3000km."""
    ctx = engine.compute(
        venue_city="New York",
        match_date=date(2026, 6, 20),
        home_origin_lat=38.9,
        home_origin_lon=-77.0,  # Washington DC
    )
    assert ctx.home_travel_km < 400, f"DC to NYC should be ~350km, got {ctx.home_travel_km:.0f}km"


def test_time_zones_crossed_europe_to_us(engine: ContextEngine):
    """European team crossing to US East Coast → ~5-6 time zones."""
    ctx = engine.compute(
        venue_city="New York",
        match_date=date(2026, 6, 20),
        away_origin_lat=51.5,
        away_origin_lon=0.0,  # London (UTC+0)
    )
    assert 4 <= ctx.away_time_zones <= 7


def test_travel_direction_east_for_west_to_east(engine: ContextEngine):
    """Team traveling from Los Angeles (west) to New York (east) → 'east'."""
    ctx = engine.compute(
        venue_city="New York",
        match_date=date(2026, 6, 20),
        away_origin_lat=34.0,
        away_origin_lon=-118.2,  # LA
    )
    assert ctx.travel_direction == "east"


def test_travel_direction_west_for_east_to_west(engine: ContextEngine):
    """Team traveling from Europe (east, lon≈10) to LA (west, lon=-118) → 'west'."""
    ctx = engine.compute(
        venue_city="Los Angeles",
        match_date=date(2026, 6, 20),
        away_origin_lat=48.9,
        away_origin_lon=2.3,  # Paris
    )
    assert ctx.travel_direction == "west"


# ---------------------------------------------------------------------------
# CONTEXT-03: Venue and kick-off context
# ---------------------------------------------------------------------------

def test_kickoff_local_hour_conversion(engine: ContextEngine):
    """Kick-off at 20:00 UTC in New York (UTC-5) → 15:00 local."""
    ctx = engine.compute(
        venue_city="New York",
        match_date=date(2026, 6, 15),
        kickoff_utc_hour=20,
    )
    assert ctx.kickoff_local_hour == 15


def test_venue_altitude_present(engine: ContextEngine):
    """Venue altitude should be > 0 for Mexico City match."""
    ctx = engine.compute(
        venue_city="Mexico City",
        match_date=date(2026, 6, 22),
    )
    assert ctx.venue_altitude_m >= 2000


def test_venue_roof_present_for_covered_stadium(engine: ContextEngine):
    """Dallas (AT&T Stadium) should set venue_has_roof = True."""
    ctx = engine.compute(
        venue_city="Dallas",
        match_date=date(2026, 6, 18),
    )
    assert ctx.venue_has_roof is True


def test_venue_city_stored_in_context(engine: ContextEngine):
    """venue_city field stores the city name."""
    ctx = engine.compute(venue_city="Atlanta", match_date=date(2026, 7, 1))
    assert ctx.venue_city == "Atlanta"


# ---------------------------------------------------------------------------
# CONTEXT-04: Context features regularized more heavily than team features
# ---------------------------------------------------------------------------

def test_context_regularization_less_than_team():
    """All context regularization weights < minimum team rating weight."""
    assert _CONTEXT_MAX_WEIGHT < _TEAM_MIN_WEIGHT, (
        f"Context max weight {_CONTEXT_MAX_WEIGHT} must be < "
        f"team min weight {_TEAM_MIN_WEIGHT}"
    )


def test_all_context_weights_positive():
    """All context regularization weights are positive."""
    for k, v in CONTEXT_REGULARIZATION.items():
        assert v > 0, f"Context weight '{k}' is non-positive: {v}"


def test_all_team_weights_greater_than_context_max():
    """Every team rating regularization weight exceeds the max context weight."""
    for k, v in TEAM_RATING_REGULARIZATION.items():
        assert v > _CONTEXT_MAX_WEIGHT, (
            f"Team weight '{k}'={v} should exceed context max {_CONTEXT_MAX_WEIGHT}"
        )


def test_context_feature_dict_keys():
    """to_feature_dict() returns all expected context feature keys."""
    ctx = MatchContext()
    feats = ctx.to_feature_dict()
    expected = {
        "home_days_rest", "away_days_rest",
        "home_starter_min_7d", "away_starter_min_7d",
        "home_starter_min_14d", "away_starter_min_14d",
        "home_travel_km", "away_travel_km",
        "home_time_zones", "away_time_zones",
        "venue_altitude_m", "venue_has_roof", "kickoff_local_hour",
    }
    assert expected == set(feats.keys())


def test_context_feature_dict_all_floats():
    """to_feature_dict() values are all floats."""
    ctx = MatchContext(venue_has_roof=True)
    for k, v in ctx.to_feature_dict().items():
        assert isinstance(v, float), f"Feature '{k}' is {type(v).__name__}, expected float"
