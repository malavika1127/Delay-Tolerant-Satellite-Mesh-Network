import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orbit.kepler import (
    OrbitParams, orbital_period_seconds, satellite_position,
    distance_km, line_of_sight_clear, EARTH_RADIUS_KM
)


def test_orbital_period_matches_known_leo_value():
    # Real LEO satellites at ~550km (Starlink-class) orbit in ~95 minutes
    period = orbital_period_seconds(550.0)
    period_min = period / 60
    assert 90 < period_min < 100, f"Expected ~95min period, got {period_min:.1f}min"


def test_satellite_returns_to_start_after_one_period():
    orbit = OrbitParams(sat_id="TEST", altitude_km=550.0, inclination_deg=53.0,
                          raan_deg=0.0, phase_deg=0.0)
    period = orbital_period_seconds(550.0)

    p0 = satellite_position(orbit, 0.0)
    p1 = satellite_position(orbit, period)  # full orbit later

    dist = distance_km(p0, p1)
    assert dist < 1.0, f"Satellite should return to ~same position after one period, drift={dist:.2f}km"


def test_two_satellites_same_plane_offset_are_never_at_same_position():
    orbit_a = OrbitParams(sat_id="A", altitude_km=550.0, inclination_deg=53.0, raan_deg=0.0, phase_deg=0.0)
    orbit_b = OrbitParams(sat_id="B", altitude_km=550.0, inclination_deg=53.0, raan_deg=0.0, phase_deg=72.0)

    pa = satellite_position(orbit_a, 0.0)
    pb = satellite_position(orbit_b, 0.0)
    assert distance_km(pa, pb) > 100  # should be well separated, same-plane 72deg apart


def test_line_of_sight_blocked_by_earth_for_antipodal_points():
    # Two satellites on exactly opposite sides of Earth should NOT have LOS
    r = EARTH_RADIUS_KM + 550.0
    p1 = (r, 0.0, 0.0)
    p2 = (-r, 0.0, 0.0)
    assert line_of_sight_clear(p1, p2) is False


def test_line_of_sight_clear_for_nearby_points():
    r = EARTH_RADIUS_KM + 550.0
    p1 = (r, 0.0, 0.0)
    p2 = (r * 0.999, 100.0, 0.0)  # very close by
    assert line_of_sight_clear(p1, p2) is True


if __name__ == "__main__":
    test_orbital_period_matches_known_leo_value()
    test_satellite_returns_to_start_after_one_period()
    test_two_satellites_same_plane_offset_are_never_at_same_position()
    test_line_of_sight_blocked_by_earth_for_antipodal_points()
    test_line_of_sight_clear_for_nearby_points()
    print("All Phase 1 tests passed.")
