"""
Simulated clock authority.

The core problem: multiple independent processes (satellite nodes) need to agree
on "simulated time" so contact windows open/close consistently everywhere. If each
process just ran its own wall-clock-scaled timer, tiny scheduling jitter between
processes would cause them to disagree about whether a window is open right now --
which would look exactly like a routing bug, but would actually be a clock-sync bug.

Solution used here: ONE process (the sim driver / test harness) owns simulated
time and advances it explicitly in discrete ticks. All nodes query this single
authority via a tiny local HTTP endpoint rather than each keeping their own timer.
This trades realism (real distributed systems don't have a shared clock oracle)
for determinism and debuggability, which matters more for a demo/benchmark project.
Documented here explicitly so it doesn't get mistaken for "real" distributed time sync.
"""

import threading
import time as wall_time
from dataclasses import dataclass


@dataclass
class ClockState:
    sim_seconds: float = 0.0
    running: bool = False


class SimClock:
    """
    In-process clock authority. In the single-process test harness (Phase 2 local
    testing) all nodes share this object directly. In the full Docker Compose
    version (Phase 5+), this gets wrapped by a tiny FastAPI endpoint that all
    containers poll instead -- same interface, different transport.
    """

    def __init__(self, speed_multiplier: float = 60.0):
        """
        speed_multiplier: how many simulated seconds pass per real second.
        Default 60x means 1 real second = 1 simulated minute, so a 6-hour
        simulated run takes 6 real minutes -- fast enough to iterate on,
        slow enough to watch happen live if needed.
        """
        self._state = ClockState()
        self._speed = speed_multiplier
        self._lock = threading.Lock()
        self._wall_start = None

    def start(self):
        with self._lock:
            self._state.running = True
            self._wall_start = wall_time.time()
            self._state.sim_seconds = 0.0

    def now(self) -> float:
        """Current simulated time in seconds since sim start."""
        with self._lock:
            if not self._state.running:
                return self._state.sim_seconds
            elapsed_wall = wall_time.time() - self._wall_start
            return elapsed_wall * self._speed

    def stop(self):
        # Compute the final sim time BEFORE acquiring the lock -- now() acquires
        # the same lock internally, and Lock() is non-reentrant, so calling
        # self.now() while already holding self._lock would deadlock forever.
        final_time = self.now()
        with self._lock:
            self._state.sim_seconds = final_time
            self._state.running = False

    def sleep_until(self, target_sim_seconds: float):
        """Blocks the calling thread (real time) until simulated time reaches target."""
        while True:
            current = self.now()
            if current >= target_sim_seconds:
                return
            remaining_sim = target_sim_seconds - current
            remaining_wall = remaining_sim / self._speed
            wall_time.sleep(min(remaining_wall, 0.5))  # check in small increments


class ManualClock:
    """
    A clock with no wall-time coupling at all -- the caller explicitly sets
    the current simulated time every tick via `.set(t)`.

    Used for Phase 5 benchmarking instead of SimClock: when running e.g. 20+
    node processes across hours of simulated time, we don't need or want to
    actually wait in real time for each contact window (that's only useful for
    the live visualization demo in Phase 6). This lets a multi-hour simulated
    run complete in real seconds, bounded only by actual gRPC call overhead.
    """

    def __init__(self):
        self._t = 0.0

    def now(self) -> float:
        return self._t

    def set(self, t: float):
        self._t = t
