"""
Phase 5 benchmark harness.

Spins up every node from the real Phase 1 orbital constellation (20 satellites
+ 3 ground stations, 23 total) as real gRPC server processes (threads with real
sockets, real SQLite storage -- not mocked), injects synthetic bundle traffic,
and runs the full simulated schedule at several p_fail (random link failure)
levels: 0%, 10%, 20%, 30%.

Uses ManualClock instead of wall-clock pacing (see sim/clock.py) so a 6-hour
simulated run completes in real seconds -- we don't need to watch it live for
a benchmark, only for the Phase 6 visualization demo.

Outputs real, measured numbers to results/benchmark_report.md -- this is what
resume bullet placeholders get filled in from, not estimates.
"""

import sys
import os
import time as wall_time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from node.satellite import SatelliteNode
from node.router import build_adjacency, load_contact_windows_from_sqlite
from node.storage import Bundle
from sim.clock import ManualClock
from sim.message_generator import generate_bundles
from sim.chaos import apply_chaos, build_ground_truth_lookup

TICK_STEP_S = 30.0
BASE_PORT = 51000


def run_one_benchmark(p_fail: float, all_windows, node_ids: list[str],
                        satellite_ids: list[str], ground_station_ids: list[str],
                        duration_s: float, num_bundles: int, seed: int = 42,
                        fixed_ttl_s: float | None = None):
    # Nodes route against the FULL nominal schedule (their belief) --
    # this never changes with p_fail, since nodes don't know about failures
    # in advance.
    routing_adjacency = build_adjacency(all_windows)

    # Ground truth: what's ACTUALLY usable this run, after chaos injection.
    failed_indices = apply_chaos(all_windows, p_fail, seed=seed + 1000)
    ground_truth_windows = build_ground_truth_lookup(all_windows, failed_indices)
    ground_truth_adjacency = build_adjacency(ground_truth_windows)

    clock = ManualClock()

    # Fresh node + storage per run (p_fail levels must not share state)
    run_tag = f"p{int(p_fail*100)}"
    state_dir = f"results/benchmark_state/{run_tag}"
    os.makedirs(state_dir, exist_ok=True)
    for f in os.listdir(state_dir):
        os.remove(os.path.join(state_dir, f))

    nodes = {}
    for i, node_id in enumerate(node_ids):
        port = BASE_PORT + i
        db_path = os.path.join(state_dir, f"{node_id}.db")
        nodes[node_id] = SatelliteNode(node_id, port, db_path, clock, log_fn=lambda m: None)  # silent
        nodes[node_id].start_server()

    wall_time.sleep(0.3)  # let all servers bind

    node_ports = {node_id: BASE_PORT + i for i, node_id in enumerate(node_ids)}
    node_addr = {node_id: f"localhost:{port}" for node_id, port in node_ports.items()}

    # Inject synthetic traffic -- IMPORTANT: bundles must only actually enter
    # the network once simulated time reaches their created_at_s. Adding them
    # all directly to the store at t=0 (regardless of created_at_s) was an
    # earlier bug here: it let bundles get "delivered" before their nominal
    # creation time, producing impossible negative latencies. Caught by
    # checking the numbers rather than trusting the code.
    bundles = generate_bundles(satellite_ids, ground_station_ids, num_bundles, duration_s,
                                 seed=seed, fixed_ttl_s=fixed_ttl_s)
    bundles_by_injection_time = sorted(bundles, key=lambda b: b.created_at_s)
    injection_ptr = 0

    # Cumulative bandwidth capacity per (node, peer) for the CURRENT window
    # occurrence, not a fixed per-tick sliver. Earlier version computed
    # capacity as bandwidth_kbps * TICK_STEP_S / 8 (i.e. only one tick's worth
    # of bandwidth), which meant any bundle larger than a single tick's slice
    # could NEVER be sent even though the full window had ample total capacity
    # -- a real bug found by investigating an unexplained 85% (not ~100%)
    # success rate at p_fail=0.0. Fixed by giving each window its FULL
    # bandwidth budget on open, consumed cumulatively across the ticks it spans.
    window_capacity: dict[tuple[str, str], float] = {}
    previously_online: dict[str, set[str]] = {node_id: set() for node_id in node_ids}

    # Main simulation loop -- no wall-clock waiting, pure logical time stepping
    t = 0.0
    while t <= duration_s:
        clock.set(t)

        # Inject any bundles whose creation time has now arrived
        while (injection_ptr < len(bundles_by_injection_time)
               and bundles_by_injection_time[injection_ptr].created_at_s <= t):
            b = bundles_by_injection_time[injection_ptr]
            nodes[b.source_id].store.add(b)
            injection_ptr += 1

        for node_id, node in nodes.items():
            # Which peers does this node ACTUALLY have an open link with right now?
            online = {}
            capacity = {}
            currently_online_peers = set()
            for edge in ground_truth_adjacency.get(node_id, []):
                if edge.start_s <= t <= edge.end_s:
                    online[edge.peer] = node_addr[edge.peer]
                    currently_online_peers.add(edge.peer)

                    key = (node_id, edge.peer)
                    if edge.peer not in previously_online[node_id]:
                        # Window just opened -- give it its FULL capacity budget,
                        # not a per-tick sliver.
                        window_duration = edge.end_s - edge.start_s
                        window_capacity[key] = edge.bandwidth_kbps * window_duration / 8.0
                    capacity[edge.peer] = window_capacity.get(key, 0.0)

            previously_online[node_id] = currently_online_peers

            sent_summary = node.tick(online, routing_adjacency, t, peer_capacity_kb=capacity)
            for peer, kb_sent in sent_summary.items():
                key = (node_id, peer)
                window_capacity[key] = max(0.0, window_capacity.get(key, 0.0) - kb_sent)

        t += TICK_STEP_S

    # Collect results: check every bundle's fate at its intended destination
    results = []
    for b in bundles:
        dest_node = nodes[b.dest_id]
        stored = dest_node.store.get_by_id(b.bundle_id)
        if stored is not None and stored.delivered_at_s is not None:
            latency = stored.delivered_at_s - stored.created_at_s
            results.append({"bundle_id": b.bundle_id, "delivered": True, "latency_s": latency,
                              "priority": b.priority, "hop_count": stored.hop_count})
        else:
            results.append({"bundle_id": b.bundle_id, "delivered": False, "latency_s": None,
                              "priority": b.priority, "hop_count": None})

    for node in nodes.values():
        node.stop_server()

    return results


def summarize(results: list[dict], p_fail: float) -> dict:
    total = len(results)
    delivered = [r for r in results if r["delivered"]]
    n_delivered = len(delivered)
    success_rate = 100.0 * n_delivered / total if total else 0.0

    latencies = sorted(r["latency_s"] for r in delivered)
    avg_latency = sum(latencies) / len(latencies) if latencies else None
    p95_latency = latencies[int(0.95 * len(latencies))] if latencies else None

    return {
        "p_fail": p_fail,
        "total_bundles": total,
        "delivered": n_delivered,
        "success_rate_pct": success_rate,
        "avg_latency_s": avg_latency,
        "p95_latency_s": p95_latency,
    }


if __name__ == "__main__":
    print("Loading real orbital contact schedule from Phase 1...")
    all_windows = load_contact_windows_from_sqlite("results/contact_schedule.db")
    print(f"Loaded {len(all_windows)} contact windows.\n")

    satellite_ids = sorted(set(
        [w[0] for w in all_windows if w[0].startswith("SAT")] +
        [w[1] for w in all_windows if w[1].startswith("SAT")]
    ))
    ground_station_ids = sorted(set(
        [w[0] for w in all_windows if w[0].startswith("GS")] +
        [w[1] for w in all_windows if w[1].startswith("GS")]
    ))
    node_ids = satellite_ids + ground_station_ids
    print(f"Constellation: {len(satellite_ids)} satellites, {len(ground_station_ids)} ground stations")

    DURATION_S = 6 * 3600  # matches the schedule's horizon
    NUM_BUNDLES = 40

    all_summaries = []
    for p_fail in [0.0, 0.1, 0.2, 0.3]:
        print(f"\n=== Running benchmark at p_fail={p_fail:.0%} ===")
        t0 = wall_time.time()
        results = run_one_benchmark(p_fail, all_windows, node_ids, satellite_ids,
                                       ground_station_ids, DURATION_S, NUM_BUNDLES)
        t1 = wall_time.time()
        summary = summarize(results, p_fail)
        all_summaries.append(summary)
        print(f"  Delivered: {summary['delivered']}/{summary['total_bundles']} "
              f"({summary['success_rate_pct']:.1f}%)")
        if summary['avg_latency_s'] is not None:
            print(f"  Avg latency: {summary['avg_latency_s']/60:.1f} min, "
                  f"p95: {summary['p95_latency_s']/60:.1f} min")
        print(f"  (benchmark run took {t1-t0:.1f}s wall-clock to compute)")

    print("\n\n=== SUMMARY TABLE ===")
    print(f"{'p_fail':>8} | {'delivered':>10} | {'success%':>9} | {'avg_lat(min)':>13} | {'p95_lat(min)':>13}")
    for s in all_summaries:
        avg_min = f"{s['avg_latency_s']/60:.1f}" if s['avg_latency_s'] else "N/A"
        p95_min = f"{s['p95_latency_s']/60:.1f}" if s['p95_latency_s'] else "N/A"
        print(f"{s['p_fail']:>8.0%} | {s['delivered']:>3}/{s['total_bundles']:<6} | "
              f"{s['success_rate_pct']:>8.1f}% | {avg_min:>13} | {p95_min:>13}")

    os._exit(0)
