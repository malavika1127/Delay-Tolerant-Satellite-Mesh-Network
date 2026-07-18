"""
Contact-graph routing (CGR-style, simplified).

The key idea: unlike normal networking where you discover routes reactively,
here the FULL FUTURE connectivity schedule is already known (orbits are
deterministic). So instead of routing on "what's connected right now," we route
on "what path gets this bundle to its destination soonest, given everything we
know about future contact windows."

This is implemented as an earliest-arrival variant of Dijkstra over a
time-expanded graph: each ContactWindow is a directed edge available only
during [start_s, end_s]. A bundle sitting at a node can "wait" for a future
window (that's the store-and-forward part) or use one that's already open.

Simplification carried over from Phase 1/2 (documented, not hidden): we treat
a contact window as offering effectively-instant transfer once it's open --
actual transmission-time-vs-bandwidth modeling is Phase 4's job (the LP
scheduler). Here, "arrival time via this edge" = max(current_time, window.start),
provided that's still <= window.end (i.e., you have to actually catch the window
before it closes).
"""

import heapq
import sqlite3
from dataclasses import dataclass


@dataclass
class ContactEdge:
    peer: str
    start_s: float
    end_s: float
    bandwidth_kbps: float


def load_contact_windows_from_sqlite(db_path: str) -> list[tuple[str, str, float, float, float]]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT node_a, node_b, start_s, end_s, bandwidth_kbps FROM contact_windows").fetchall()
    conn.close()
    return rows


def build_adjacency(windows: list[tuple[str, str, float, float, float]]) -> dict[str, list[ContactEdge]]:
    """
    Contact windows are bidirectional (a real ISL or downlink works both ways).
    Builds an adjacency list: node_id -> list of ContactEdge to its peers.
    """
    adjacency: dict[str, list[ContactEdge]] = {}
    for (a, b, start, end, bw) in windows:
        adjacency.setdefault(a, []).append(ContactEdge(peer=b, start_s=start, end_s=end, bandwidth_kbps=bw))
        adjacency.setdefault(b, []).append(ContactEdge(peer=a, start_s=start, end_s=end, bandwidth_kbps=bw))
    return adjacency


def compute_route(source: str, dest: str, current_time_s: float,
                   adjacency: dict[str, list[ContactEdge]]) -> list[str] | None:
    """
    Earliest-arrival Dijkstra. Returns the full path [source, ..., dest] that
    minimizes arrival time at dest, or None if dest is unreachable within the
    known contact schedule horizon.
    """
    if source == dest:
        return [source]

    earliest: dict[str, float] = {source: current_time_s}
    prev: dict[str, str] = {}
    # priority queue of (arrival_time, node)
    pq: list[tuple[float, str]] = [(current_time_s, source)]
    visited: set[str] = set()

    while pq:
        time_here, node = heapq.heappop(pq)

        if node in visited:
            continue
        visited.add(node)

        if node == dest:
            break

        for edge in adjacency.get(node, []):
            if edge.peer in visited:
                continue
            # Can only use this contact if it hasn't already closed by the time
            # we'd be ready to send (we might need to wait for it to open).
            if edge.end_s < time_here:
                continue
            depart_time = max(time_here, edge.start_s)
            if depart_time > edge.end_s:
                continue  # window closes before we could actually catch it
            arrival_time = depart_time  # simplified: instant transfer once window is open

            if arrival_time < earliest.get(edge.peer, float("inf")):
                earliest[edge.peer] = arrival_time
                prev[edge.peer] = node
                heapq.heappush(pq, (arrival_time, edge.peer))

    if dest not in earliest:
        return None  # unreachable within the schedule horizon

    # reconstruct path
    path = [dest]
    while path[-1] != source:
        path.append(prev[path[-1]])
    path.reverse()
    return path


def compute_next_hop(source: str, dest: str, current_time_s: float,
                       adjacency: dict[str, list[ContactEdge]]) -> str | None:
    """Convenience wrapper: just the immediate next node to forward to, or None."""
    path = compute_route(source, dest, current_time_s, adjacency)
    if path is None or len(path) < 2:
        return None
    return path[1]


def compute_route_with_times(source: str, dest: str, current_time_s: float,
                                adjacency: dict[str, list[ContactEdge]]) -> list[tuple[str, float]] | None:
    """
    Same earliest-arrival Dijkstra as compute_route, but also returns the
    arrival time at each hop -- e.g. [(A, 0.0), (B, 480.0), (C, 900.0)].
    Used for visualization/animation timing, where knowing WHEN the packet
    reaches each node matters, not just the path itself.
    """
    if source == dest:
        return [(source, current_time_s)]

    earliest: dict[str, float] = {source: current_time_s}
    prev: dict[str, str] = {}
    pq: list[tuple[float, str]] = [(current_time_s, source)]
    visited: set[str] = set()

    while pq:
        time_here, node = heapq.heappop(pq)
        if node in visited:
            continue
        visited.add(node)
        if node == dest:
            break
        for edge in adjacency.get(node, []):
            if edge.peer in visited or edge.end_s < time_here:
                continue
            depart_time = max(time_here, edge.start_s)
            if depart_time > edge.end_s:
                continue
            arrival_time = depart_time
            if arrival_time < earliest.get(edge.peer, float("inf")):
                earliest[edge.peer] = arrival_time
                prev[edge.peer] = node
                heapq.heappush(pq, (arrival_time, edge.peer))

    if dest not in earliest:
        return None

    path = [(dest, earliest[dest])]
    while path[-1][0] != source:
        node = path[-1][0]
        parent = prev[node]
        path.append((parent, earliest[parent]))
    path.reverse()
    return path
