"""
Simplified circular-orbit propagator.

Deliberately NOT modeling eccentricity, perturbations, J2 drag, etc.
Every satellite is on a perfect circular orbit defined by:
    - altitude_km   : height above Earth's surface
    - inclination_deg : tilt of orbital plane vs equator
    - raan_deg      : right ascension of ascending node (rotates the plane around Earth's axis)
    - phase_deg     : starting position of the satellite within its orbit at t=0

This is intentionally simple. The interesting engineering is in routing/storage,
not orbital physics. Do not be tempted to add real perturbation models here.
"""

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0
EARTH_MU = 398600.4418  # km^3/s^2, standard gravitational parameter


@dataclass
class OrbitParams:
    sat_id: str
    altitude_km: float
    inclination_deg: float
    raan_deg: float
    phase_deg: float


@dataclass
class GroundStation:
    station_id: str
    lat_deg: float
    lon_deg: float


def orbital_period_seconds(altitude_km: float) -> float:
    """Circular orbit period from vis-viva simplification (a = r for circular orbits)."""
    r = EARTH_RADIUS_KM + altitude_km
    return 2 * math.pi * math.sqrt(r ** 3 / EARTH_MU)


def satellite_position(orbit: OrbitParams, t_seconds: float) -> tuple[float, float, float]:
    """
    Returns ECI-like Cartesian position (km) of the satellite at time t.
    Simplified: ignores Earth's rotation coupling to RAAN drift (RAAN treated as fixed).
    """
    r = EARTH_RADIUS_KM + orbit.altitude_km
    period = orbital_period_seconds(orbit.altitude_km)
    mean_motion = 2 * math.pi / period  # rad/s

    theta = math.radians(orbit.phase_deg) + mean_motion * t_seconds  # angle within orbital plane

    # Position in the orbital plane (before applying inclination/RAAN rotation)
    x_plane = r * math.cos(theta)
    y_plane = r * math.sin(theta)
    z_plane = 0.0

    incl = math.radians(orbit.inclination_deg)
    raan = math.radians(orbit.raan_deg)

    # Rotate by inclination around x-axis
    x1 = x_plane
    y1 = y_plane * math.cos(incl) - z_plane * math.sin(incl)
    z1 = y_plane * math.sin(incl) + z_plane * math.cos(incl)

    # Rotate by RAAN around z-axis
    x2 = x1 * math.cos(raan) - y1 * math.sin(raan)
    y2 = x1 * math.sin(raan) + y1 * math.cos(raan)
    z2 = z1

    return (x2, y2, z2)


def ground_station_position(gs: GroundStation, t_seconds: float, earth_rotation: bool = True) -> tuple[float, float, float]:
    """
    Returns Cartesian position (km) of a fixed ground station.
    If earth_rotation=True, accounts for Earth's rotation (~360deg/86164s sidereal day),
    which matters since satellites are computed in an Earth-centered-inertial-like frame.
    """
    lat = math.radians(gs.lat_deg)
    lon = math.radians(gs.lon_deg)

    if earth_rotation:
        sidereal_day = 86164.0905
        rotation_rad = 2 * math.pi * (t_seconds / sidereal_day)
        lon = lon + rotation_rad

    r = EARTH_RADIUS_KM  # assume sea-level, ignore altitude of ground station
    x = r * math.cos(lat) * math.cos(lon)
    y = r * math.cos(lat) * math.sin(lon)
    z = r * math.sin(lat)
    return (x, y, z)


def distance_km(p1: tuple[float, float, float], p2: tuple[float, float, float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(p1, p2)))


def line_of_sight_clear(p1: tuple[float, float, float], p2: tuple[float, float, float],
                          earth_radius: float = EARTH_RADIUS_KM, margin_km: float = 0.0) -> bool:
    """
    Checks whether the straight line between p1 and p2 is blocked by Earth.
    Simple sphere-intersection test: find the closest approach of the line segment
    to Earth's center: if that distance < earth_radius + margin, LOS is blocked.
    """
    p1v = p1
    p2v = p2
    dx = p2v[0] - p1v[0]
    dy = p2v[1] - p1v[1]
    dz = p2v[2] - p1v[2]
    seg_len_sq = dx * dx + dy * dy + dz * dz
    if seg_len_sq == 0:
        return True

    # Parametrize line as p1 + t*(p2-p1), find t minimizing distance to origin
    t = -(p1v[0] * dx + p1v[1] * dy + p1v[2] * dz) / seg_len_sq
    t = max(0.0, min(1.0, t))

    closest = (p1v[0] + t * dx, p1v[1] + t * dy, p1v[2] + t * dz)
    dist_to_center = math.sqrt(sum(c ** 2 for c in closest))

    return dist_to_center > (earth_radius + margin_km)


def elevation_angle_deg(gs_pos: tuple[float, float, float], sat_pos: tuple[float, float, float]) -> float:
    """
    Elevation angle of the satellite as seen from the ground station.
    Approximation: uses the ground station's radial direction (from Earth center)
    as the local "up" vector, which is accurate for a spherical Earth model.
    """
    gs_up = gs_pos  # radial direction IS the up vector for a point on a sphere
    gs_up_norm = math.sqrt(sum(c ** 2 for c in gs_up))
    up_unit = tuple(c / gs_up_norm for c in gs_up)

    to_sat = tuple(sat_pos[i] - gs_pos[i] for i in range(3))
    to_sat_norm = math.sqrt(sum(c ** 2 for c in to_sat))
    if to_sat_norm == 0:
        return 90.0
    to_sat_unit = tuple(c / to_sat_norm for c in to_sat)

    cos_zenith = sum(up_unit[i] * to_sat_unit[i] for i in range(3))
    zenith_angle = math.degrees(math.acos(max(-1.0, min(1.0, cos_zenith))))
    return 90.0 - zenith_angle
