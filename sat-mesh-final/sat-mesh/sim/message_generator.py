"""
Generates synthetic bundle traffic for benchmarking: random satellite sources,
ground-station destinations (the realistic case -- satellites downlinking data),
with a realistic priority mix (mostly telemetry, some commands, occasional
large imagery transfers).
"""

import random
from node.storage import Bundle

PRIORITY_MIX = [
    ("telemetry", 0.55, (10, 40)),   # (priority, probability weight, size_kb range)
    ("command", 0.25, (2, 10)),
    ("imagery", 0.20, (200, 800)),
]


def generate_bundles(satellite_ids: list[str], ground_station_ids: list[str],
                       num_bundles: int, horizon_s: float, seed: int = 42,
                       fixed_ttl_s: float | None = None) -> list[Bundle]:
    """
    fixed_ttl_s: if given, every bundle gets this TTL regardless of when it's
    created (models realistic time-critical traffic, e.g. "this telemetry is
    only useful for the next hour"). If None (default), TTL stretches to the
    full remaining horizon -- a much more forgiving, "eventually fine" traffic
    model, useful as a best-case baseline but not representative of real
    time-sensitive constraints.
    """
    rng = random.Random(seed)
    bundles = []

    weights = [w for (_, w, _) in PRIORITY_MIX]
    for i in range(num_bundles):
        priority, _, size_range = rng.choices(PRIORITY_MIX, weights=weights, k=1)[0]
        size_kb = rng.randint(*size_range)
        source = rng.choice(satellite_ids)
        dest = rng.choice(ground_station_ids)
        created_at = rng.uniform(0, horizon_s * 0.3)  # injected across the first 30% of the run
        ttl = fixed_ttl_s if fixed_ttl_s is not None else (horizon_s - created_at)

        bundles.append(Bundle(
            bundle_id=f"BUNDLE-{i:04d}",
            source_id=source,
            dest_id=dest,
            priority=priority,
            size_kb=size_kb,
            created_at_s=created_at,
            ttl_s=ttl,
        ))

    return bundles
