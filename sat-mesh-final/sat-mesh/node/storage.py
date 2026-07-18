"""
Persistent, per-node bundle storage. Backed by SQLite so a node can be killed
and restarted without losing queued bundles -- this is the concrete evidence
behind the "zero data loss across restarts" fault-tolerance claim.

Each node owns exactly one BundleStore, pointed at its own file
(e.g. results/node_state/SAT-00-00.db). Nodes never share a storage file.
"""

import sqlite3
import json
from dataclasses import dataclass, asdict, field


@dataclass
class Bundle:
    bundle_id: str
    source_id: str
    dest_id: str
    priority: str          # "command" | "telemetry" | "imagery"
    size_kb: int
    created_at_s: float
    ttl_s: float
    hop_count: int = 0
    path_so_far: list = field(default_factory=list)
    delivered_at_s: float | None = None   # set when the bundle reaches its destination

    def is_expired(self, current_sim_time: float) -> bool:
        return current_sim_time > (self.created_at_s + self.ttl_s)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(s: str) -> "Bundle":
        d = json.loads(s)
        return Bundle(**d)


class BundleStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_schema()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_schema(self):
        conn = self._connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bundles (
                bundle_id TEXT PRIMARY KEY,
                dest_id TEXT NOT NULL,
                data_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',  -- pending | delivered | expired
                queued_for_peer TEXT                       -- next-hop node id, set by router
            )
        """)
        conn.commit()
        conn.close()

    def add(self, bundle: Bundle):
        """Insert a new bundle, or overwrite if the same id already exists (idempotent)."""
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO bundles (bundle_id, dest_id, data_json, status) VALUES (?, ?, ?, 'pending')",
            (bundle.bundle_id, bundle.dest_id, bundle.to_json())
        )
        conn.commit()
        conn.close()

    def set_next_hop(self, bundle_id: str, peer_id: str | None):
        conn = self._connect()
        conn.execute("UPDATE bundles SET queued_for_peer = ? WHERE bundle_id = ?", (peer_id, bundle_id))
        conn.commit()
        conn.close()

    def pending_for_peer(self, peer_id: str) -> list[Bundle]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT data_json FROM bundles WHERE status = 'pending' AND queued_for_peer = ?",
            (peer_id,)
        ).fetchall()
        conn.close()
        return [Bundle.from_json(r[0]) for r in rows]

    def all_pending(self) -> list[Bundle]:
        conn = self._connect()
        rows = conn.execute("SELECT data_json FROM bundles WHERE status = 'pending'").fetchall()
        conn.close()
        return [Bundle.from_json(r[0]) for r in rows]

    def mark_delivered(self, bundle_id: str):
        conn = self._connect()
        conn.execute("UPDATE bundles SET status = 'delivered' WHERE bundle_id = ?", (bundle_id,))
        conn.commit()
        conn.close()

    def mark_delivered_with_time(self, bundle: "Bundle", delivered_at_s: float):
        """
        Unlike mark_delivered() (which only flips the status column), this also
        writes delivered_at_s into the stored bundle data so latency can
        actually be computed later (delivered_at_s - created_at_s). Needed
        because bundles are stored as a JSON blob, not individual columns.
        """
        bundle.delivered_at_s = delivered_at_s
        conn = self._connect()
        conn.execute(
            "UPDATE bundles SET data_json = ?, status = 'delivered' WHERE bundle_id = ?",
            (bundle.to_json(), bundle.bundle_id)
        )
        conn.commit()
        conn.close()

    def mark_expired(self, bundle_id: str):
        conn = self._connect()
        conn.execute("UPDATE bundles SET status = 'expired' WHERE bundle_id = ?", (bundle_id,))
        conn.commit()
        conn.close()

    def remove(self, bundle_id: str):
        """Used after a bundle has been successfully forwarded to a peer."""
        conn = self._connect()
        conn.execute("DELETE FROM bundles WHERE bundle_id = ?", (bundle_id,))
        conn.commit()
        conn.close()

    def get_by_id(self, bundle_id: str) -> Bundle | None:
        conn = self._connect()
        row = conn.execute("SELECT data_json, status FROM bundles WHERE bundle_id = ?", (bundle_id,)).fetchone()
        conn.close()
        if row is None:
            return None
        return Bundle.from_json(row[0])

    def count_pending(self) -> int:
        conn = self._connect()
        n = conn.execute("SELECT COUNT(*) FROM bundles WHERE status = 'pending'").fetchone()[0]
        conn.close()
        return n
