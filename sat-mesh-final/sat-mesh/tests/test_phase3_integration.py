"""
Phase 3 integration test.

Four real node processes (A, B, C, D) chained by a synthetic contact schedule
where NO direct A-D link ever exists. A bundle is injected at A destined for D.
Nothing in this test tells any node where to forward -- each node independently
calls SatelliteNode.tick(), which uses the shared contact-graph adjacency to
compute its own next hop. If the bundle arrives at D, real distributed routing
worked, not a scripted handoff like Phase 2.

Schedule (simulated seconds):
  A-B open  [0,   50]
  B-C open  [60,  150]
  C-D open  [160, 250]
So the bundle MUST wait at each node for its next window -- proving
store-and-forward is actually happening, not just instant relay.
"""

import sys
import os
import time as wall_time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from node.satellite import SatelliteNode
from node.storage import Bundle
from node.router import build_adjacency
from sim.clock import SimClock

PORTS = {"A": 50061, "B": 50062, "C": 50063, "D": 50064}
ADDR = {k: f"localhost:{v}" for k, v in PORTS.items()}

SCHEDULE = [
    ("A", "B", 0.0, 50.0, 500.0),
    ("B", "C", 60.0, 150.0, 500.0),
    ("C", "D", 160.0, 250.0, 500.0),
]


def peers_online_for(node_id: str, current_time_s: float) -> dict[str, str]:
    """Which peers does node_id have an ACTIVE contact window with right now?"""
    online = {}
    for (a, b, start, end, bw) in SCHEDULE:
        if start <= current_time_s <= end:
            if a == node_id:
                online[b] = ADDR[b]
            elif b == node_id:
                online[a] = ADDR[a]
    return online


def run_test():
    clock = SimClock(speed_multiplier=25.0)  # 250 sim seconds -> 10 real seconds
    adjacency = build_adjacency(SCHEDULE)

    os.makedirs("results/node_state", exist_ok=True)
    for name in PORTS:
        p = f"results/node_state/phase3_{name}.db"
        if os.path.exists(p):
            os.remove(p)

    logs = []

    def make_logger(name):
        def log(msg):
            print(msg)
            logs.append(msg)
        return log

    nodes = {}
    for name, port in PORTS.items():
        nodes[name] = SatelliteNode(name, port, f"results/node_state/phase3_{name}.db", clock, log_fn=make_logger(name))
        nodes[name].start_server()

    wall_time.sleep(0.3)
    clock.start()

    # Inject bundle at A, destined for D. Nobody tells anyone the route.
    bundle = Bundle(
        bundle_id="ROUTED-001", source_id="A", dest_id="D", priority="telemetry",
        size_kb=30, created_at_s=clock.now(), ttl_s=1000.0,
    )
    nodes["A"].store.add(bundle)
    print(f"Injected bundle at A destined for D. No manual routing given.\n")

    # Drive the simulation: every real 0.3s, advance and let every node tick.
    last_print = -1
    while clock.now() < 260.0:
        t = clock.now()
        if int(t) // 20 != last_print:
            last_print = int(t) // 20
            print(f"--- sim_time={t:.1f}s ---")
        for name, node in nodes.items():
            online = peers_online_for(name, t)
            node.tick(online, adjacency, t)
        wall_time.sleep(0.2)

    clock.stop()

    # Verify: the bundle should now be marked delivered at D, having hopped A->B->C->D
    delivered = nodes["D"].store.get_by_id("ROUTED-001")
    assert delivered is not None, "Bundle never reached D at all"
    print(f"\nFinal bundle state at D: hop_count={delivered.hop_count}, path={delivered.path_so_far}")
    assert delivered.hop_count == 3, f"Expected 3 hops (A->B->C->D), got {delivered.hop_count}"
    assert delivered.path_so_far == ["B", "C", "D"], f"Unexpected path: {delivered.path_so_far}"

    delivered_log = any("DELIVERED" in line and "ROUTED-001" in line for line in logs)
    assert delivered_log, "No DELIVERED log line found for the bundle at D"

    # Confirm intermediate nodes no longer hold it (correctly forwarded onward)
    assert nodes["A"].store.count_pending() == 0
    assert nodes["B"].store.count_pending() == 0
    assert nodes["C"].store.count_pending() == 0

    print("\nPASS: bundle auto-routed A -> B -> C -> D purely via independent node.tick() "
          "calls and shared contact-graph adjacency -- no manual routing anywhere.")

    for node in nodes.values():
        node.stop_server()

    print("\nAll Phase 3 integration tests passed.")


if __name__ == "__main__":
    run_test()
    os._exit(0)
