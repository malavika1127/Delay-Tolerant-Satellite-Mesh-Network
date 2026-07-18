# Delay-Tolerant Satellite Mesh Network

A distributed **Delay-Tolerant Networking (DTN)** simulator that models a **20-satellite Low Earth Orbit (LEO) constellation** using **Contact Graph Routing (CGR)** over real orbital physics and **Linear Programming (LP)-based bandwidth prioritization**. The system implements a decentralized store-and-forward architecture and is benchmarked under random link-failure injection to evaluate fault tolerance.

---

## Features

- 20-satellite LEO constellation simulation
- Decentralized store-and-forward networking
- Contact Graph Routing (CGR) with earliest-arrival path computation
- Realistic orbital contact-window generation (~95-minute LEO orbital period)
- Persistent bundle storage using SQLite
- LP-based bandwidth scheduling with optimized greedy runtime implementation
- Random link-failure injection for resilience testing
- Live constellation and packet visualization
- Comprehensive unit and integration test suite

---

## System Architecture

```
orbit/
    Circular-orbit physics and contact-window generation
    (validated against real ~95-minute LEO orbital periods)

node/
    satellite.py      -> gRPC satellite node + simulation loop
    router.py         -> Contact Graph Routing (Earliest-Arrival Dijkstra)
    scheduler.py      -> LP + greedy bandwidth allocation
    storage.py        -> Persistent SQLite bundle queue

sim/
    clock.py
    message_generator.py
    chaos.py
    benchmark.py

viz/
    FastAPI backend + HTML Canvas visualization

tests/
    Unit and integration tests

results/
    contact_schedule.db
    benchmark_report.md
```

---

## Network Design

Each satellite (and ground station) runs as an independent **gRPC server** with its own persistent SQLite database.

There is **no centralized router**.

Every node independently:

- Computes its next hop using the shared deterministic contact schedule
- Stores bundles locally whenever no communication window exists
- Forwards data automatically once a valid contact window opens

Since communication opportunities are intermittent by design, **store-and-forward behavior is treated as the normal operating mode rather than a failure condition.**

---

## Routing

The network implements **Contact Graph Routing (CGR)**.

Routing decisions are computed using an **Earliest-Arrival Dijkstra algorithm**, where edges exist only during valid communication windows generated from orbital mechanics.

Each node independently computes routes without relying on centralized coordination.

---

## Bandwidth Scheduling

Bandwidth allocation is performed using a **Linear Programming formulation** that prioritizes higher-priority bundles.

For runtime efficiency, the live simulator uses an optimized greedy implementation.

Extensive testing confirms that, for the current priority-only optimization objective, the greedy scheduler produces solutions equivalent to the LP formulation across multiple bandwidth capacities.

---

## Technologies Used

- Python
- gRPC
- SQLite
- PuLP (Linear Programming)
- FastAPI
- Uvicorn

---

## Installation

```bash
pip install grpcio grpcio-tools pulp fastapi uvicorn --break-system-packages
```

Generate gRPC code:

```bash
python3 -m grpc_tools.protoc \
-I node/grpc_service \
--python_out=node/grpc_service \
--grpc_python_out=node/grpc_service \
node/grpc_service/mesh.proto
```

---

## Running the Project

Generate the orbital contact schedule:

```bash
python3 -m orbit.contact_schedule
```

Run Phase 1 tests:

```bash
python3 tests/test_kepler.py
```

Run Phase 2 tests:

```bash
python3 tests/test_phase2_integration.py
```

Run Phase 3 tests:

```bash
python3 tests/test_router.py
python3 tests/test_phase3_integration.py
```

Run Phase 4 tests:

```bash
python3 tests/test_scheduler.py
python3 tests/test_phase4_integration.py
```

Run the benchmark:

```bash
python3 -m sim.benchmark
```

Generate visualization data:

```bash
python3 -m viz.generate_viz_data
```

Launch the visualization server:

```bash
uvicorn viz.server:app --port 8080
```

---

## Benchmark Results

The benchmark evaluates network performance under random link failures using real simulation data.

### Delivery Performance

| Link Failure Rate | Delivery Success | Average Latency | 95th Percentile Latency |
|------------------:|----------------:|----------------:|------------------------:|
| 0% | 100% | 79 minutes | 193 minutes |
| 30% | 100% | 140 minutes | 274 minutes |

When bundles are allowed the full simulation duration, the network maintains **100% delivery success** even with **30% random link failures**, while latency degrades gracefully.

---

### Delivery Success with Time-To-Live Constraints

| TTL | 0% Failures | 30% Failures |
|-----:|------------:|-------------:|
| 2 Hours | 67.5% | 32.5% |
| 1 Hour | 47.5% | — |

A **2-hour TTL** exposes the trade-off between delivery guarantees and network resilience under constrained time.

A **1-hour TTL** is shorter than the constellation's approximately **95-minute orbital revisit period**, meaning many routes cannot physically complete within the deadline even in the absence of failures.

---

## Key Findings

- Maintains **100% delivery success** under up to **30% random link failures** when sufficient delivery time is available.
- Network latency increases gracefully as failure rates increase.
- Delivery success under strict TTL constraints is fundamentally limited by orbital geometry rather than routing correctness.
- The benchmark demonstrates realistic delay-tolerant networking behavior for intermittently connected satellite constellations.

---

## Project Limitations

- Circular orbit approximation (no eccentricity or perturbation modeling)
- Benchmark nodes execute as threads with independent gRPC servers rather than separate Docker containers
- Failure model includes only random, non-adversarial link disruptions
- Scheduler optimization currently targets priority-only objectives

---

## Future Work

- Docker Compose deployment for process isolation
- Multi-orbit and heterogeneous constellation support
- Dynamic topology updates
- Deadline-aware and cost-aware LP optimization
- Byzantine fault tolerance
- Congestion-aware routing
- Energy-aware scheduling
- Forward Error Correction (FEC)
- Real satellite TLE integration
- CCSDS-compatible DTN bundle support

---

## Testing

The project includes comprehensive unit and integration tests covering:

- Orbital mechanics
- Contact schedule generation
- Contact Graph Routing
- Bundle forwarding
- Scheduler correctness
- End-to-end message delivery
- Benchmark validation

All tests pass successfully.

---

## Project Structure

```
.
├── orbit/
├── node/
├── sim/
├── viz/
├── tests/
├── results/
└── README.md
```
