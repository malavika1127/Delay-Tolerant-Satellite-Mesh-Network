"""
Sweeps simulated time from t=0 to t=DURATION and tests every satellite-satellite
and satellite-ground pair for line-of-sight visibility. Coalesces consecutive
"visible" samples into contact windows and writes them to a SQLite table.

This schedule is computed ONCE up front. Every node uses the same schedule to
independently decide its own routing (no central router at runtime) -- that's
the key distributed-systems property this whole project demonstrates.
"""

import sqlite3
import math
from dataclasses import dataclass

from orbit.kepler import (
    satellite_position, ground_station_position, distance_km,
    line_of_sight_clear, elevation_angle_deg, EARTH_RADIUS_KM
)
from orbit.constellation_config import build_constellation, build_ground_stations

STEP_SECONDS = 10.0
MIN_ELEVATION_DEG = 10.0          # ground stations can't see satellites below this
MAX_INTER_SAT_RANGE_KM = 4000.0   # cap for sat-to-sat radio range (simplification)
MIN_ELEVATION_MARGIN_KM = 0.0     # extra Earth-blocking margin for sat-sat LOS


@dataclass
class ContactWindow:
    node_a: str
    node_b: str
    start_s: float
    end_s: float
    bandwidth_kbps: float


def bandwidth_from_distance(dist_km: float, max_range_km: float, max_bw_kbps: float = 2000.0,
                              min_bw_kbps: float = 50.0) -> float:
    """Simple linear falloff: closer = more bandwidth. Not physically precise, deliberately simple."""
    frac = max(0.0, 1.0 - (dist_km / max_range_km))
    return min_bw_kbps + frac * (max_bw_kbps - min_bw_kbps)


def generate_contact_schedule(duration_seconds: float, step_seconds: float = STEP_SECONDS) -> list[ContactWindow]:
    satellites = build_constellation()
    ground_stations = build_ground_stations()

    all_node_ids = [s.sat_id for s in satellites] + [g.station_id for g in ground_stations]
    n_steps = int(duration_seconds // step_seconds) + 1

    # visibility_state[(a,b)] = None or start_time of an ongoing window
    visibility_state: dict[tuple[str, str], float | None] = {}
    windows: list[ContactWindow] = []

    pairs = []
    for i in range(len(satellites)):
        for j in range(i + 1, len(satellites)):
            pairs.append((satellites[i].sat_id, satellites[j].sat_id, "sat-sat"))
    for s in satellites:
        for g in ground_stations:
            pairs.append((s.sat_id, g.station_id, "sat-gs"))

    for pair in pairs:
        visibility_state[(pair[0], pair[1])] = None

    sat_lookup = {s.sat_id: s for s in satellites}
    gs_lookup = {g.station_id: g for g in ground_stations}

    for step in range(n_steps):
        t = step * step_seconds

        sat_positions = {s.sat_id: satellite_position(s, t) for s in satellites}
        gs_positions = {g.station_id: ground_station_position(g, t) for g in ground_stations}

        for (a, b, kind) in pairs:
            if kind == "sat-sat":
                pa, pb = sat_positions[a], sat_positions[b]
                visible = (
                    line_of_sight_clear(pa, pb, margin_km=MIN_ELEVATION_MARGIN_KM)
                    and distance_km(pa, pb) <= MAX_INTER_SAT_RANGE_KM
                )
                dist = distance_km(pa, pb)
            else:  # sat-gs
                pa, pb = sat_positions[a], gs_positions[b]
                elev = elevation_angle_deg(pb, pa)
                visible = elev >= MIN_ELEVATION_DEG
                dist = distance_km(pa, pb)

            key = (a, b)
            currently_open = visibility_state[key]

            if visible and currently_open is None:
                visibility_state[key] = t  # window opens
            elif not visible and currently_open is not None:
                # window closes -- record it
                bw = bandwidth_from_distance(dist, MAX_INTER_SAT_RANGE_KM if kind == "sat-sat" else 2000.0)
                windows.append(ContactWindow(a, b, currently_open, t, bw))
                visibility_state[key] = None

    # Close out any windows still open at the end of the simulation
    for (a, b), start in visibility_state.items():
        if start is not None:
            windows.append(ContactWindow(a, b, start, duration_seconds, 500.0))

    return windows


def write_schedule_to_sqlite(windows: list[ContactWindow], db_path: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contact_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_a TEXT NOT NULL,
            node_b TEXT NOT NULL,
            start_s REAL NOT NULL,
            end_s REAL NOT NULL,
            bandwidth_kbps REAL NOT NULL
        )
    """)
    cur.execute("DELETE FROM contact_windows")
    cur.executemany(
        "INSERT INTO contact_windows (node_a, node_b, start_s, end_s, bandwidth_kbps) VALUES (?, ?, ?, ?, ?)",
        [(w.node_a, w.node_b, w.start_s, w.end_s, w.bandwidth_kbps) for w in windows]
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    import time as time_mod
    DURATION = 6 * 3600  # 6 simulated hours for a quick first run

    t0 = time_mod.time()
    windows = generate_contact_schedule(DURATION)
    t1 = time_mod.time()

    print(f"Generated {len(windows)} contact windows over {DURATION/3600:.1f}h in {t1-t0:.2f}s (wall clock)")

    write_schedule_to_sqlite(windows, "results/contact_schedule.db")
    print("Wrote schedule to results/contact_schedule.db")

    # quick sanity summary
    sat_gs_windows = [w for w in windows if w.node_b.startswith("GS-")]
    sat_sat_windows = [w for w in windows if not w.node_b.startswith("GS-")]
    print(f"  sat-sat windows: {len(sat_sat_windows)}")
    print(f"  sat-ground windows: {len(sat_gs_windows)}")
    if windows:
        avg_dur = sum(w.end_s - w.start_s for w in windows) / len(windows)
        print(f"  avg window duration: {avg_dur:.1f}s")
