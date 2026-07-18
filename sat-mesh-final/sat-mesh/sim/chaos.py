"""
Chaos injection: randomly suppresses a fraction of scheduled contact windows so
they never actually open, even though nodes' routing logic still believes the
full nominal schedule is correct (this is the realistic case -- you don't know
in advance a link will fail from weather, hardware fault, etc.).

Design choice: nodes route using the FULL nominal schedule (their belief).
The orchestrator uses this chaos-affected "ground truth" schedule to decide
what peers are ACTUALLY online at each tick. When a node's chosen next-hop
contact turns out to be down, the bundle simply waits -- and once that
window's end_s passes, the router (Dijkstra with the end_s < time_here check)
naturally stops considering it and finds an alternate path using later
windows. This is what actually forces genuine re-routing under failure,
not just a relabeling of the same path.
"""

import random


def apply_chaos(windows: list[tuple[str, str, float, float, float]],
                  p_fail: float, seed: int = 7) -> set[int]:
    """
    Returns a set of window INDICES (into the original `windows` list) that are
    "failed" -- i.e. never actually usable, despite appearing in the nominal
    schedule nodes route against.
    """
    rng = random.Random(seed)
    failed_indices = set()
    for i in range(len(windows)):
        if rng.random() < p_fail:
            failed_indices.add(i)
    return failed_indices


def build_ground_truth_lookup(windows: list[tuple[str, str, float, float, float]],
                                 failed_indices: set[int]) -> list[tuple[str, str, float, float, float]]:
    """Returns only the windows that actually work (failed ones excluded)."""
    return [w for i, w in enumerate(windows) if i not in failed_indices]
