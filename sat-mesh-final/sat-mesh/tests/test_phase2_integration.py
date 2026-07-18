"""
Phase 2 integration test.

Spins up two real SatelliteNode processes (well, threads with real gRPC servers,
not separate OS processes yet -- that comes with Docker in Phase 5) and proves:
  1. A bundle can be pushed from node A to node B over a real gRPC call.
  2. B's storage actually persists it.
  3. B can then forward it onward to a third node (simulating multi-hop).
  4. An expired bundle is correctly rejected.

This is deliberately still "manual" routing (we tell each node exactly where to
forward) -- Phase 3 replaces this manual step with real contact-graph routing.
"""

import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from node.satellite import SatelliteNode
from node.storage import Bundle
from sim.clock import SimClock


def run_test():
    clock = SimClock(speed_multiplier=1.0)
    clock.start()

    os.makedirs("results/node_state", exist_ok=True)
    for f in ["A.db", "B.db", "C.db"]:
        p = f"results/node_state/{f}"
        if os.path.exists(p):
            os.remove(p)

    node_a = SatelliteNode("SAT-A", 50051, "results/node_state/A.db", clock)
    node_b = SatelliteNode("SAT-B", 50052, "results/node_state/B.db", clock)
    node_c = SatelliteNode("GS-C", 50053, "results/node_state/C.db", clock)

    node_a.start_server()
    node_b.start_server()
    node_c.start_server()
    time.sleep(0.5)  # let servers bind

    # --- Test 1: A creates a bundle and pushes it to B ---
    bundle = Bundle(
        bundle_id="MSG-001", source_id="SAT-A", dest_id="GS-C",
        priority="telemetry", size_kb=20, created_at_s=clock.now(), ttl_s=600.0,
    )
    ok = node_a.push_bundle_to_peer("localhost:50052", bundle)
    assert ok, "A->B push should succeed"

    b_pending = node_b.store.all_pending()
    assert len(b_pending) == 1, f"Expected 1 bundle in B's store, got {len(b_pending)}"
    assert b_pending[0].bundle_id == "MSG-001"
    assert b_pending[0].hop_count == 1
    assert b_pending[0].path_so_far == ["SAT-B"]
    print("PASS: A -> B handoff, persisted correctly, hop_count incremented")

    # --- Test 2: B forwards it on to C (multi-hop) ---
    forwarded_bundle = b_pending[0]
    ok2 = node_b.push_bundle_to_peer("localhost:50053", forwarded_bundle)
    assert ok2, "B->C push should succeed"

    c_pending = node_c.store.all_pending()
    assert len(c_pending) == 1
    assert c_pending[0].hop_count == 2
    assert c_pending[0].path_so_far == ["SAT-B", "GS-C"]
    b_pending_after = node_b.store.all_pending()
    assert len(b_pending_after) == 0, "B should have removed the bundle after forwarding"
    print("PASS: B -> C multi-hop forward, path_so_far correctly tracked, B's queue cleared")

    # --- Test 3: expired bundle is rejected ---
    expired_bundle = Bundle(
        bundle_id="MSG-002", source_id="SAT-A", dest_id="GS-C",
        priority="imagery", size_kb=500, created_at_s=clock.now() - 1000.0, ttl_s=10.0,  # already expired
    )
    ok3 = node_a.push_bundle_to_peer("localhost:50052", expired_bundle)
    assert ok3 is False, "expired bundle push should be rejected"
    print("PASS: expired bundle correctly rejected")

    # --- Test 4: restart simulation -- kill node B's object, reload from same db file ---
    node_b.stop_server()
    del node_b
    node_b_restarted = SatelliteNode("SAT-B", 50052, "results/node_state/B.db", clock)
    # B's store should still be empty since we already forwarded MSG-001 out
    assert node_b_restarted.store.count_pending() == 0
    print("PASS: node B restart reloads storage correctly (state matches pre-crash)")

    node_a.stop_server()
    node_c.stop_server()
    clock.stop()
    print("\nAll Phase 2 integration tests passed.")


if __name__ == "__main__":
    run_test()
    # gRPC's internal server threads are non-daemon by default and can keep the
    # process alive after all servers report stopped. Force exit once tests pass
    # rather than let CI/scripts hang waiting on threads with nothing left to do.
    os._exit(0)
