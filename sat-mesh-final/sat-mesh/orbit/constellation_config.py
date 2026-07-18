"""
Defines the constellation layout: 20 satellites in a simplified Walker-delta pattern
(4 orbital planes x 5 satellites each), plus 3 fixed ground stations.

A Walker-delta constellation is the standard way real LEO constellations (Iridium,
Starlink) space satellites evenly for coverage. We use a simplified version:
evenly spaced RAANs across planes, evenly spaced phase offsets within each plane.
"""

from orbit.kepler import OrbitParams, GroundStation

NUM_PLANES = 4
SATS_PER_PLANE = 5
ALTITUDE_KM = 550.0       # typical LEO altitude (Starlink-like)
INCLINATION_DEG = 53.0    # typical LEO inclination for good coverage


def build_constellation() -> list[OrbitParams]:
    satellites = []
    for plane_idx in range(NUM_PLANES):
        raan = (360.0 / NUM_PLANES) * plane_idx
        for sat_idx in range(SATS_PER_PLANE):
            phase = (360.0 / SATS_PER_PLANE) * sat_idx
            sat_id = f"SAT-{plane_idx:02d}-{sat_idx:02d}"
            satellites.append(OrbitParams(
                sat_id=sat_id,
                altitude_km=ALTITUDE_KM,
                inclination_deg=INCLINATION_DEG,
                raan_deg=raan,
                phase_deg=phase,
            ))
    return satellites


def build_ground_stations() -> list[GroundStation]:
    # Three widely spread ground stations for realistic sparse connectivity
    return [
        GroundStation(station_id="GS-BLR", lat_deg=12.97, lon_deg=77.59),   # Bangalore
        GroundStation(station_id="GS-SVL", lat_deg=37.39, lon_deg=-122.08),  # Silicon Valley
        GroundStation(station_id="GS-SGP", lat_deg=1.35, lon_deg=103.82),   # Singapore
    ]
