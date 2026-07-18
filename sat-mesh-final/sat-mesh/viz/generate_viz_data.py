"""
Precomputes everything the visualization frontend needs, as a single JSON file:
  - satellite/ground-station positions sampled every SAMPLE_STEP_S seconds,
    projected from 3D orbital coordinates down to a 2D top-down view
  - the full contact window schedule (for drawing links as they open/close)
  - one real, actually-routed packet path with real per-hop arrival times
    (computed by node/router.py, not scripted for the demo)

This is intentionally a static precompute + playback model rather than a live
gRPC-backed viewer: the FastAPI server in viz/server.py just serves this file.
Wiring the viewer to a LIVE running node cluster (so the "kill a node" chaos
button in the UI reflects a real process being killed, not a replayed log) is
listed as a clear next step, not silently implied to already work.
"""

import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orbit.kepler import satellite_position, ground_station_position, EARTH_RADIUS_KM
from orbit.constellation_config import build_constellation, build_ground_stations
from node.router import load_contact_windows_from_sqlite, build_adjacency, compute_route_with_times

SAMPLE_STEP_S = 60.0
DURATION_S = 6 * 3600


def project_to_2d(pos_3d: tuple[float, float, float]) -> tuple[float, float]:
    """Simple top-down orthographic projection (drop Z). Fine for a 2D demo view."""
    return (pos_3d[0], pos_3d[1])


def build_viz_data(demo_source: str, demo_dest: str, demo_start_time: float = 0.0) -> dict:
    satellites = build_constellation()
    ground_stations = build_ground_stations()

    windows = load_contact_windows_from_sqlite("results/contact_schedule.db")
    adjacency = build_adjacency(windows)

    # Sample positions over time
    n_samples = int(DURATION_S // SAMPLE_STEP_S) + 1
    position_frames = []
    for i in range(n_samples):
        t = i * SAMPLE_STEP_S
        frame = {"t": t, "positions": {}}
        for s in satellites:
            p = satellite_position(s, t)
            frame["positions"][s.sat_id] = project_to_2d(p)
        for g in ground_stations:
            p = ground_station_position(g, t)
            frame["positions"][g.station_id] = project_to_2d(p)
        position_frames.append(frame)

    # Real routed packet path for the demo
    path_with_times = compute_route_with_times(demo_source, demo_dest, demo_start_time, adjacency)

    return {
        "meta": {
            "duration_s": DURATION_S,
            "sample_step_s": SAMPLE_STEP_S,
            "earth_radius_km": EARTH_RADIUS_KM,
        },
        "satellites": [s.sat_id for s in satellites],
        "ground_stations": [g.station_id for g in ground_stations],
        "position_frames": position_frames,
        "contact_windows": [
            {"a": w[0], "b": w[1], "start": w[2], "end": w[3], "bandwidth_kbps": w[4]}
            for w in windows
        ],
        "demo_packet": {
            "source": demo_source,
            "dest": demo_dest,
            "path": [{"node": n, "arrival_s": t} for n, t in path_with_times] if path_with_times else None,
        },
    }


if __name__ == "__main__":
    print("Computing visualization data from real orbital + routing data...")
    data = build_viz_data("SAT-00-00", "GS-SGP", 0.0)
    print(f"  {len(data['position_frames'])} position frames "
          f"({data['meta']['duration_s']/3600:.0f}h @ {data['meta']['sample_step_s']:.0f}s steps)")
    print(f"  {len(data['contact_windows'])} contact windows")
    print(f"  Demo packet route: {[hop['node'] for hop in data['demo_packet']['path']]}")

    os.makedirs("viz", exist_ok=True)
    out_path = "viz/frontend/viz_data.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f)
    print(f"Wrote {out_path} ({os.path.getsize(out_path)/1024:.0f} KB)")
