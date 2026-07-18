import sys
import os
from dataclasses import dataclass
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from node.scheduler import allocate_lp, allocate_greedy, weighted_value, PRIORITY_WEIGHTS


@dataclass
class FakeBundle:
    bundle_id: str
    priority: str
    size_kb: float


def test_everything_fits_gets_fully_sent():
    bundles = [
        FakeBundle("B1", "command", 50),
        FakeBundle("B2", "telemetry", 30),
        FakeBundle("B3", "imagery", 20),
    ]
    alloc = allocate_lp(bundles, capacity_kb=1000)  # way more capacity than needed
    for b in bundles:
        assert alloc[b.bundle_id] == pytest_approx(1.0)


def pytest_approx(x, tol=1e-4):
    class Approx:
        def __eq__(self, other):
            return abs(other - x) < tol
    return Approx()


def test_command_beats_imagery_under_pressure():
    """
    Core priority-scheduling claim: with tight capacity, command traffic must
    be fully allocated before imagery gets anything.
    """
    bundles = [
        FakeBundle("CMD", "command", 40),
        FakeBundle("IMG", "imagery", 40),
    ]
    # Capacity only fits ONE of the two fully
    alloc = allocate_lp(bundles, capacity_kb=40)
    assert alloc["CMD"] > 0.99, f"Command should be fully sent, got {alloc['CMD']}"
    assert alloc["IMG"] < 0.01, f"Imagery should get nothing when capacity is exhausted by command, got {alloc['IMG']}"


def test_partial_fill_on_cutoff_bundle():
    """
    Capacity fits command fully plus HALF of telemetry -- the LP should split
    exactly the lower-priority bundle at the cutoff, not fudge both.
    """
    bundles = [
        FakeBundle("CMD", "command", 30),
        FakeBundle("TEL", "telemetry", 40),
    ]
    alloc = allocate_lp(bundles, capacity_kb=50)  # 30 (all of CMD) + 20 (half of TEL) = 50
    assert alloc["CMD"] > 0.99
    assert abs(alloc["TEL"] - 0.5) < 0.01, f"Expected TEL ~50% sent, got {alloc['TEL']}"


def test_greedy_matches_lp_objective_value():
    """
    The key claim from scheduler.py's docstring: because priority weight is the
    only differentiator in this objective, a correctly-implemented greedy
    fallback achieves the SAME optimal objective value as the LP -- not an
    approximation. This test actually proves that claim rather than asserting it.
    """
    bundles = [
        FakeBundle("A", "command", 25),
        FakeBundle("B", "command", 35),
        FakeBundle("C", "telemetry", 20),
        FakeBundle("D", "telemetry", 15),
        FakeBundle("E", "imagery", 60),
        FakeBundle("F", "imagery", 10),
    ]
    for capacity in [10, 30, 55, 75, 100, 140, 200]:
        lp_alloc = allocate_lp(bundles, capacity_kb=capacity)
        greedy_alloc = allocate_greedy(bundles, capacity_kb=capacity)

        lp_value = weighted_value(bundles, lp_alloc)
        greedy_value = weighted_value(bundles, greedy_alloc)

        assert abs(lp_value - greedy_value) < 0.01, (
            f"At capacity={capacity}: LP value={lp_value:.2f} but greedy value={greedy_value:.2f} -- "
            f"these should match exactly per the fractional-knapsack property"
        )
    print("  (verified across 7 different capacity levels)")


def test_zero_capacity_allocates_nothing():
    bundles = [FakeBundle("X", "command", 10)]
    alloc = allocate_lp(bundles, capacity_kb=0)
    assert alloc["X"] < 0.01


def test_empty_bundle_list():
    assert allocate_lp([], capacity_kb=100) == {}
    assert allocate_greedy([], capacity_kb=100) == {}


if __name__ == "__main__":
    test_everything_fits_gets_fully_sent()
    print("PASS: everything fits -> fully sent")
    test_command_beats_imagery_under_pressure()
    print("PASS: command beats imagery under capacity pressure")
    test_partial_fill_on_cutoff_bundle()
    print("PASS: partial fill lands exactly on the lower-priority cutoff bundle")
    test_greedy_matches_lp_objective_value()
    print("PASS: greedy fallback matches LP's optimal objective value")
    test_zero_capacity_allocates_nothing()
    print("PASS: zero capacity -> zero allocation")
    test_empty_bundle_list()
    print("PASS: empty bundle list handled")
    print("\nAll Phase 4 scheduler tests passed.")
