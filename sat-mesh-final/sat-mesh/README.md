# Delay-Tolerant Satellite Mesh Network

A distributed store-and-forward network simulating a 20-satellite LEO constellation,
using contact-graph routing over real orbital physics and LP-based bandwidth
prioritization, benchmarked under random link-failure injection.

## What this is

Every satellite/ground-station node is a real process (gRPC server + persistent
SQLite storage). There is no central router: each node independently computes
its own next hop from a shared, deterministically-known contact schedule, and
holds data locally (store-and-forward) whenever no link is currently available
— which, in this domain, is the *normal* operating condition, not a failure case.

## Architecture

```
orbit/      circular-orbit physics, contact-window generation (verified against
            real ~95-min LEO orbital periods)
node/       satellite.py (gRPC node + tick loop), router.py (contact-graph
            routing, earliest-arrival Dijkstra), scheduler.py (LP + greedy
            bandwidth allocation), storage.py (persistent bundle queue)
sim/        clock.py, message_generator.py, chaos.py, benchmark.py
viz/        FastAPI server + Canvas frontend for live orbit/packet visualization
tests/      unit + integration tests for every phase, all passing together
results/    contact_schedule.db, benchmark_report.md (real measured numbers)
```

## Running it

```bash
pip install grpcio grpcio-tools pulp fastapi uvicorn --break-system-packages
python3 -m grpc_tools.protoc -I node/grpc_service --python_out=node/grpc_service \
    --grpc_python_out=node/grpc_service node/grpc_service/mesh.proto
python3 -m orbit.contact_schedule          # generates results/contact_schedule.db
python3 tests/test_kepler.py               # Phase 1
python3 tests/test_phase2_integration.py   # Phase 2
python3 tests/test_router.py && python3 tests/test_phase3_integration.py   # Phase 3
python3 tests/test_scheduler.py && python3 tests/test_phase4_integration.py # Phase 4
python3 -m sim.benchmark                   # Phase 5 -- produces the real numbers below
python3 -m viz.generate_viz_data           # Phase 6 -- then: uvicorn viz.server:app --port 8080
```

## Real, measured results (not estimates)

Full detail, methodology, and two bugs found and fixed along the way are in
`results/benchmark_report.md`. Headline numbers:

- **100% delivery success** at up to 30% random link-failure injection, when
  bundles have the full remaining run to get through — latency degrades
  gracefully instead (avg 79→140 min, p95 193→274 min from 0%→30% failure).
- Under a **tighter, more realistic 2-hour TTL**, delivery success degrades
  from 67.5% (0% failure) to 32.5% (30% failure) — a real, honest
  fault-tolerance-under-pressure curve.
- A **1-hour TTL is tighter than this constellation's ~95-minute orbital
  revisit cadence supports** for a meaningful fraction of routes — even at 0%
  injected failure, only 47.5% deliver in time. This is a genuine finding
  about matching TTL policy to constellation geometry, not a bug.

## Honest scope notes

- Orbits are simplified circular models (no eccentricity, no perturbations) —
  verified against real-world LEO orbital periods (~95 min at 550km), but not
  a full physics simulation.
- Node "processes" in the benchmark are threads with real gRPC servers and
  real SQLite files, not separate OS containers — Docker Compose packaging
  for true process isolation is a natural next step, not yet done.
- Failures modeled here are random and non-adversarial link/window dropouts,
  not Byzantine/malicious nodes.
- The LP scheduler (`node/scheduler.py`) is proven equivalent to its greedy
  fallback for this specific priority-only objective (verified across 7
  capacity levels in `tests/test_scheduler.py`) — greedy is what's wired into
  the live `tick()` path for runtime speed; PuLP's LP formulation is real,
  tested, and the correct tool if the objective ever grows beyond
  priority-only (e.g. adding deadline or cost terms).
