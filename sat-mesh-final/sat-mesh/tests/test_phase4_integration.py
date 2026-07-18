"""
Phase 4 integration test.

Node A holds THREE bundles for B (command, telemetry, imagery), all queued at
once. The A-B contact window's bandwidth is deliberately too small to fit all
three in one tick. Nothing manually picks which one goes first -- tick() calls
the greedy scheduler (backed by the same objective the LP proves optimal),
and we verify command wins, then telemetry, with imagery starved out entirely
under this capacity, exactly matching the earlier unit-test proof but now
exercised over real node processes and real gRPC calls.
"""

import sys
import os
import time as wall_time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from node.satellite import SatelliteNode
from node.storage import Bundle
from node.router import build_adjacency
from sim.clock import SimClock

PORTS = {"A": 50071, "B": 50072}
ADDR = {k: f"localhost:{v}" for k, v in PORTS.items()}
SCHEDULE = [("A", "B", 0.0, 100.0, 500.0)]  # single long-lived window, capacity is the real constraint


def run_test():
    clock = SimClock(speed_multiplier=30.0)
    adjacency = build_adjacency(SCHEDULE)

    os.makedirs("results/node_state", exist_ok=True)
    for name in PORTS:
        p = f"results/node_state/phase4_{name}.db"
        if os.path.exists(p):
            os.remove(p)

    logs = []

    def make_logger(name):
        def log(msg):
            print(msg)
            logs.append(msg)
        return log

    node_a = SatelliteNode("A", PORTS["A"], "results/node_state/phase4_A.db", clock, log_fn=make_logger("A"))
    node_b = SatelliteNode("B", PORTS["B"], "results/node_state/phase4_B.db", clock, log_fn=make_logger("B"))
    node_a.start_server()
    node_b.start_server()
    wall_time.sleep(0.3)
    clock.start()

    # Three bundles competing for the same window. Capacity below is set so
    # only ~1.x of these fit -- forces real prioritization, not just "everything
    # gets through eventually so priority doesn't matter."
    bundles = [
        Bundle(bundle_id="IMG-1", source_id="A", dest_id="B", priority="imagery",
               size_kb=40, created_at_s=0.0, ttl_s=500.0),
        Bundle(bundle_id="CMD-1", source_id="A", dest_id="B", priority="command",
               size_kb=30, created_at_s=0.0, ttl_s=500.0),
        Bundle(bundle_id="TEL-1", source_id="A", dest_id="B", priority="telemetry",
               size_kb=20, created_at_s=0.0, ttl_s=500.0),
    ]
    for b in bundles:
        node_a.store.add(b)
    print("Queued 3 competing bundles at A (imagery=40kb, command=30kb, telemetry=20kb) "
          "for a window with only 50kb capacity this tick.\n")

    # Capacity: 50kb -- fits CMD(30) + TEL(20) = 50 exactly, IMG(40) gets nothing.
    peer_capacity = {"B": 50.0}

    # First tick: window is open immediately (t=0), capacity-constrained forwarding happens.
    online = {"B": ADDR["B"]}
    node_a.tick(online, adjacency, clock.now(), peer_capacity_kb=peer_capacity)
    wall_time.sleep(0.5)  # let the gRPC calls land

    b_pending = {b.bundle_id: b for b in node_b.store.all_pending()}
    a_pending_ids = {b.bundle_id for b in node_a.store.all_pending()}

    print(f"\nAfter capacity-constrained tick:")
    print(f"  Delivered to B: {sorted(b_pending.keys())}")
    print(f"  Still held at A: {sorted(a_pending_ids)}")

    assert "CMD-1" in b_pending, "Command bundle should have been sent (highest priority)"
    assert "TEL-1" in b_pending, "Telemetry bundle should have been sent (fits after command)"
    assert "IMG-1" not in b_pending, "Imagery should NOT have been sent -- capacity exhausted by higher priority"
    assert "IMG-1" in a_pending_ids, "Imagery bundle should still be held at A, waiting for more capacity"

    print("\nPASS: under tight capacity, command + telemetry sent, imagery correctly held back "
          "-- matches the LP's proven-optimal allocation, not an arbitrary send order.")

    # Second tick with fresh capacity: imagery should now go through since nothing competes with it.
    peer_capacity_2 = {"B": 100.0}
    node_a.tick(online, adjacency, clock.now(), peer_capacity_kb=peer_capacity_2)
    wall_time.sleep(0.5)

    b_pending_after = {b.bundle_id for b in node_b.store.all_pending()} | \
                       {b.bundle_id for b in [node_b.store.get_by_id(bid) for bid in ["IMG-1", "CMD-1", "TEL-1"]] if b}
    assert node_b.store.get_by_id("IMG-1") is not None, "Imagery should arrive once capacity frees up"
    print("PASS: imagery delivered on the next tick once capacity was available -- nothing was lost, just delayed.")

    node_a.stop_server()
    node_b.stop_server()
    clock.stop()
    print("\nAll Phase 4 integration tests passed.")


if __name__ == "__main__":
    run_test()
    os._exit(0)
