# Benchmark Report — Delay-Tolerant Satellite Mesh Network

All numbers below are **measured**, from real runs of the actual constellation
(20 satellites + 3 ground stations, 23 real gRPC node processes, real routing,
real LP/greedy bandwidth scheduling) against the real orbital contact schedule
generated in Phase 1. Nothing here is estimated or assumed.

Run script: `sim/benchmark.py`. Reproducible via the seeds noted below.

---

## Setup

- Constellation: 20 satellites (4 orbital planes × 5 satellites, 550km altitude,
  53° inclination), 3 ground stations (Bangalore, Silicon Valley, Singapore)
- Contact schedule horizon: 6 simulated hours (21,600s), 375 real contact windows
  computed from circular-orbit physics (verified against the real ~95-minute
  LEO orbital period in Phase 1 tests)
- Traffic: 40 synthetic bundles, random satellite source → random ground-station
  destination, priority mix 55% telemetry / 25% command / 20% imagery, injected
  across the first 30% of the run
- Failure model: a random fraction (`p_fail`) of individual contact window
  *occurrences* are silently suppressed — nodes still route as if the full
  nominal schedule holds (they don't know about failures in advance); only the
  ground-truth availability check knows a given window didn't actually happen
- Seed: 42 (traffic), 1042+ (failure injection, varies by p_fail)

---

## Finding 1 — Generous TTL (bundle useful for the rest of the 6-hour run)

| p_fail | Delivered | Success rate | Avg latency | p95 latency |
|---|---|---|---|---|
| 0% | 40/40 | 100.0% | 79.3 min | 193.0 min |
| 10% | 40/40 | 100.0% | 84.5 min | 194.4 min |
| 20% | 40/40 | 100.0% | 107.7 min | 233.2 min |
| 30% | 40/40 | 100.0% | 140.4 min | 274.1 min |

**Reading this honestly:** delivery success stays at 100% even under 30% random
link failure — this is real store-and-forward + contact-graph rerouting doing
its job, not a ceiling effect from a broken benchmark (verified separately: a
capacity-modeling bug that had been silently blocking large bundles was found
and fixed before these numbers were produced — see `Bugs found` below).
**What this result does NOT show** is a breaking point, because a TTL spanning
nearly the whole 6-hour horizon gives bundles enormous room to wait out
failures and catch a later contact window. Latency, not success rate, is where
the cost of failure actually shows up here: avg latency degrades 79→140 min
(+77%) and p95 degrades 193→274 min (+42%) from 0% to 30% failure — a real,
measurable fault-tolerance cost, just not a delivery-rate one.

## Finding 2 — Moderate TTL (2 hours), escalating failure

| p_fail | Delivered | Success rate | Avg latency |
|---|---|---|---|
| 0% | 27/40 | 67.5% | 41.1 min |
| 10% | 26/40 | 65.0% | 43.2 min |
| 20% | 21/40 | 52.5% | 47.8 min |
| 30% | 13/40 | 32.5% | 36.7 min |
| 50% | 9/40 | 22.5% | 28.0 min |

This is the degradation curve missing from Finding 1 — once TTL is tightened
to something a real time-sensitive telemetry stream might actually use,
failure rate has a large, direct effect on success rate: roughly halving
between 20% and 30% injected failure.

## Finding 3 — Tight TTL (1 hour), escalating failure

| p_fail | Delivered | Success rate |
|---|---|---|
| 0% | 19/40 | 47.5% |
| 10% | 18/40 | 45.0% |
| 20% | 14/40 | 35.0% |
| 30% | 9/40 | 22.5% |
| 50% | 8/40 | 20.0% |
| 70% | 6/40 | 15.0% |

**Important honest caveat:** even at **0% injected failure**, only 47.5% of
bundles deliver within a 1-hour TTL. This is not a bug — it's a real
constraint of this constellation's geometry: the satellites' orbital period is
~95 minutes, so a satellite that just missed a ground-station contact window
may not get another opportunity for the better part of an hour, on top of
however long a multi-hop path takes. **A 1-hour TTL is simply tighter than
this constellation's natural contact cadence supports for a meaningful
fraction of source/destination pairs.** This is a genuinely useful finding for
a real DTN design (bundle TTL has to be set with orbital revisit cadence in
mind, not chosen arbitrarily) and is worth stating exactly this way if asked
about it — not smoothed over.

---

## Bugs found and fixed during this benchmark (kept here on purpose)

1. **Negative latency bug:** bundles were being added to their source node's
   storage at simulation start (t=0) regardless of their randomized
   `created_at_s`, so some appeared "delivered" before their nominal creation
   time. Fixed by only injecting a bundle once simulated time reaches its
   actual `created_at_s`.
2. **Capacity-modeling bug:** bandwidth capacity was computed per 30-second
   tick slice rather than for the full contact window, which meant any bundle
   larger than what fits in a single 30-second slice (e.g. a 791KB imagery
   bundle on a ~198kbps link) could never be sent — even though the full
   ~480-second window had ample total capacity. This silently capped Finding 1
   at 85% instead of the correct 100% at p_fail=0%. Fixed by tracking
   cumulative capacity per window occurrence instead of a fixed per-tick
   sliver.

Both were caught by checking that a 0%-failure baseline actually behaved like
one should (100% delivery, no negative numbers), not by assuming the code was
correct because it ran without crashing.

---

## What's NOT yet benchmarked here

- Node process crashes (kill + restart) — proven separately in Phase 2/3
  integration tests (zero data loss across restart), but not yet folded into
  this same benchmark run with quantified recovery time.
- Throughput at higher bundle counts / larger constellations (this run used
  40 bundles / 23 nodes — enough to demonstrate the mechanism, not to stress-test
  scale).
- LP scheduler (`allocate_lp`) vs. greedy fallback compared head-to-head in this
  live setting (their equivalence is proven analytically and unit-tested in
  Phase 4, but not re-verified inside this specific benchmark run).

These are reasonable next steps if a more exhaustive benchmark section is
wanted, but are not required to support the current resume bullet — everything
claimed there is backed by a number in this file.
