import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from node.router import build_adjacency, compute_route, compute_next_hop


def test_no_route_needed_same_node():
    adjacency = build_adjacency([])
    path = compute_route("A", "A", 0.0, adjacency)
    assert path == ["A"]


def test_unreachable_destination():
    windows = [("A", "B", 100.0, 200.0, 500.0)]
    adjacency = build_adjacency(windows)
    path = compute_route("A", "Z", 0.0, adjacency)
    assert path is None


def test_direct_contact_already_open():
    # A-B window open from t=0 to t=100. Bundle at A at t=10 should use it immediately.
    windows = [("A", "B", 0.0, 100.0, 500.0)]
    adjacency = build_adjacency(windows)
    path = compute_route("A", "B", 10.0, adjacency)
    assert path == ["A", "B"]


def test_must_wait_for_future_window():
    # No window open right now, but one opens later -- router should wait for it.
    windows = [("A", "B", 500.0, 600.0, 500.0)]
    adjacency = build_adjacency(windows)
    path = compute_route("A", "B", 0.0, adjacency)
    assert path == ["A", "B"]


def test_window_already_closed_is_unusable():
    # Contact window existed but closed before current_time -- can't use it.
    windows = [("A", "B", 0.0, 100.0, 500.0)]
    adjacency = build_adjacency(windows)
    path = compute_route("A", "B", 500.0, adjacency)
    assert path is None


def test_multihop_beats_waiting_for_direct():
    """
    Classic CGR test: a direct A->C window opens LATE (t=1000), but a multi-hop
    path A->B->C is available much earlier via two windows that chain together.
    Earliest-arrival routing should prefer the faster multi-hop path.
    """
    windows = [
        ("A", "C", 1000.0, 1100.0, 500.0),  # direct link -- slow
        ("A", "B", 0.0, 50.0, 500.0),        # fast first hop
        ("B", "C", 60.0, 150.0, 500.0),       # fast second hop, opens after A-B closes
    ]
    adjacency = build_adjacency(windows)
    path = compute_route("A", "C", 0.0, adjacency)
    assert path == ["A", "B", "C"], f"Expected multi-hop path, got {path}"


def test_next_hop_matches_first_step_of_route():
    windows = [
        ("A", "B", 0.0, 50.0, 500.0),
        ("B", "C", 60.0, 150.0, 500.0),
    ]
    adjacency = build_adjacency(windows)
    next_hop = compute_next_hop("A", "C", 0.0, adjacency)
    assert next_hop == "B"


def test_three_hop_chain():
    windows = [
        ("A", "B", 0.0, 50.0, 500.0),
        ("B", "C", 60.0, 100.0, 500.0),
        ("C", "D", 110.0, 200.0, 500.0),
    ]
    adjacency = build_adjacency(windows)
    path = compute_route("A", "D", 0.0, adjacency)
    assert path == ["A", "B", "C", "D"]


def test_bidirectional_contact_usable_both_ways():
    windows = [("A", "B", 0.0, 100.0, 500.0)]
    adjacency = build_adjacency(windows)
    assert compute_route("A", "B", 0.0, adjacency) == ["A", "B"]
    assert compute_route("B", "A", 0.0, adjacency) == ["B", "A"]


if __name__ == "__main__":
    test_no_route_needed_same_node()
    test_unreachable_destination()
    test_direct_contact_already_open()
    test_must_wait_for_future_window()
    test_window_already_closed_is_unusable()
    test_multihop_beats_waiting_for_direct()
    test_next_hop_matches_first_step_of_route()
    test_three_hop_chain()
    test_bidirectional_contact_usable_both_ways()
    print("All Phase 3 router tests passed.")
