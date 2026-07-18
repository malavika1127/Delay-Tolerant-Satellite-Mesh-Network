"""
A single satellite (or ground station) node process.

Responsibilities:
  1. Run a gRPC server (PushBundle, Heartbeat) so peers can hand it bundles.
  2. During each of its own scheduled contact windows, act as a CLIENT and try
     to push any bundles it's holding that are queued for that specific peer.
  3. Persist everything to its own SQLite BundleStore so a kill+restart loses nothing.

Routing (deciding WHICH peer a bundle should be queued for) is intentionally NOT
in this file -- that's router.py's job (Phase 3). For Phase 2, nodes forward
bundles addressed directly to a currently-visible peer, and otherwise just hold
them. This lets us test the networking + storage layer in isolation first.
"""

import sys
import os
import threading
import time as wall_time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "grpc_service"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import grpc
from concurrent import futures

from node.grpc_service import mesh_pb2, mesh_pb2_grpc
from node.storage import BundleStore, Bundle
from node.router import compute_next_hop
from node.scheduler import allocate_greedy


class MeshNodeServicer(mesh_pb2_grpc.MeshNodeServicer):
    def __init__(self, node_id: str, store: BundleStore, clock, log_fn=print):
        self.node_id = node_id
        self.store = store
        self.clock = clock
        self.log = log_fn

    def PushBundle(self, request, context):
        b = request.bundle
        bundle = Bundle(
            bundle_id=b.bundle_id, source_id=b.source_id, dest_id=b.dest_id,
            priority=b.priority, size_kb=b.size_kb, created_at_s=b.created_at_s,
            ttl_s=b.ttl_s, hop_count=b.hop_count, path_so_far=list(b.path_so_far),
        )
        bundle.path_so_far.append(self.node_id)
        bundle.hop_count += 1

        if bundle.is_expired(self.clock.now()):
            self.log(f"[{self.node_id}] REJECTED expired bundle {bundle.bundle_id}")
            return mesh_pb2.PushAck(accepted=False, reason="expired")

        self.store.add(bundle)
        self.log(f"[{self.node_id}] received bundle {bundle.bundle_id} from {request.from_node} "
                  f"(dest={bundle.dest_id}, hop={bundle.hop_count})")
        return mesh_pb2.PushAck(accepted=True, reason="ok")

    def Heartbeat(self, request, context):
        return mesh_pb2.HeartbeatResponse(node_id=self.node_id, alive=True)


class SatelliteNode:
    def __init__(self, node_id: str, port: int, db_path: str, clock, log_fn=print):
        self.node_id = node_id
        self.port = port
        self.store = BundleStore(db_path)
        self.clock = clock
        self.log = log_fn
        self._server = None
        self._peer_stubs: dict[str, mesh_pb2_grpc.MeshNodeStub] = {}

    def start_server(self):
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        servicer = MeshNodeServicer(self.node_id, self.store, self.clock, self.log)
        mesh_pb2_grpc.add_MeshNodeServicer_to_server(servicer, self._server)
        self._server.add_insecure_port(f"[::]:{self.port}")
        self._server.start()
        self.log(f"[{self.node_id}] gRPC server listening on port {self.port}")

    def stop_server(self):
        if self._server:
            # grace=None stops immediately without waiting for in-flight RPCs/
            # keepalive threads to drain. For a test/demo harness this is fine;
            # a production shutdown path would want a real grace period.
            self._server.stop(grace=None)

    def _get_stub(self, peer_address: str) -> mesh_pb2_grpc.MeshNodeStub:
        if peer_address not in self._peer_stubs:
            channel = grpc.insecure_channel(peer_address)
            self._peer_stubs[peer_address] = mesh_pb2_grpc.MeshNodeStub(channel)
        return self._peer_stubs[peer_address]

    def push_bundle_to_peer(self, peer_address: str, bundle: Bundle) -> bool:
        """Attempt to deliver a bundle to a peer during an active contact window."""
        try:
            stub = self._get_stub(peer_address)
            proto_bundle = mesh_pb2.Bundle(
                bundle_id=bundle.bundle_id, source_id=bundle.source_id, dest_id=bundle.dest_id,
                priority=bundle.priority, size_kb=bundle.size_kb, created_at_s=bundle.created_at_s,
                ttl_s=bundle.ttl_s, hop_count=bundle.hop_count, path_so_far=bundle.path_so_far,
            )
            req = mesh_pb2.PushRequest(bundle=proto_bundle, from_node=self.node_id)
            ack = stub.PushBundle(req, timeout=5.0)
            if ack.accepted:
                self.store.remove(bundle.bundle_id)
                self.log(f"[{self.node_id}] forwarded {bundle.bundle_id} -> {peer_address}")
                return True
            else:
                self.log(f"[{self.node_id}] peer rejected {bundle.bundle_id}: {ack.reason}")
                return False
        except grpc.RpcError as e:
            self.log(f"[{self.node_id}] failed to reach {peer_address}: {e.code()}")
            return False

    def tick(self, current_peers_online: dict[str, str], adjacency, current_time_s: float,
             peer_capacity_kb: dict[str, float] | None = None):
        """
        Routing-driven forward step. For every bundle this node is currently
        holding, ask the router "what's the best next hop right now", and if
        that next hop happens to be a peer we can currently reach (i.e. one of
        the peers in an active contact window), forward it -- subject to that
        window's remaining bandwidth capacity, prioritized via the LP/greedy
        scheduler so command traffic doesn't get starved by imagery when a
        window can't fit everything.

        current_peers_online: {node_id: "host:port"} -- peers reachable THIS tick
        adjacency: the full contact-graph adjacency (from router.build_adjacency)
        peer_capacity_kb: {node_id: capacity_kb_available_this_tick} -- if a peer
            is omitted (or this whole dict is None), capacity is treated as
            unlimited, preserving the simpler Phase 3 behavior for callers that
            don't care about bandwidth limits (e.g. small demo/integration tests).

        This is the piece that replaces "manually tell the node where to send
        it" from Phase 2 with real distributed, independently-computed routing:
        every node runs this same logic using its own copy of the schedule --
        there is no central node deciding routes for everyone.
        """
        peer_capacity_kb = peer_capacity_kb or {}

        # Group all forwardable bundles by their computed next hop.
        groups: dict[str, list[Bundle]] = {}
        for bundle in self.store.all_pending():
            if bundle.is_expired(current_time_s):
                self.store.mark_expired(bundle.bundle_id)
                self.log(f"[{self.node_id}] bundle {bundle.bundle_id} expired, dropping")
                continue

            if bundle.dest_id == self.node_id:
                self.store.mark_delivered_with_time(bundle, current_time_s)
                self.log(f"[{self.node_id}] bundle {bundle.bundle_id} DELIVERED (final destination)")
                continue

            next_hop = compute_next_hop(self.node_id, bundle.dest_id, current_time_s, adjacency)
            if next_hop is None:
                continue  # no known route yet -- keep holding it (store-and-forward)

            if next_hop in current_peers_online:
                groups.setdefault(next_hop, []).append(bundle)
            # else: route says forward to next_hop, but that contact isn't open
            # yet -- correctly just keep holding the bundle until it is.

        sent_kb_per_peer: dict[str, float] = {}
        for peer, bundles in groups.items():
            capacity = peer_capacity_kb.get(peer)  # None = unlimited capacity
            if capacity is None:
                to_send = bundles
            else:
                allocation = allocate_greedy(bundles, capacity)
                # Only whole-bundle sends are actually transmitted this tick;
                # a bundle at partial allocation (x<1) waits and gets
                # reconsidered (with fresh priority ranking) next tick/window --
                # this is the fractional-knapsack "cutoff bundle" carrying over.
                to_send = [b for b in bundles if allocation.get(b.bundle_id, 0.0) >= 1.0 - 1e-9]

            peer_address = current_peers_online[peer]
            sent_kb = 0.0
            for bundle in to_send:
                if self.push_bundle_to_peer(peer_address, bundle):
                    sent_kb += bundle.size_kb
            sent_kb_per_peer[peer] = sent_kb

        return sent_kb_per_peer
