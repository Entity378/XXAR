import hashlib
import sqlite3
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from src.core.logger import get_logger
logger = get_logger(__name__)


OFFSET_BIN_CS = 10
DEFAULT_TOP_K = 200


class ConstellationIndex:

    def __init__(self, sqlite_path):
        self.path = Path(sqlite_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash TEXT UNIQUE NOT NULL,
                indexed_at TEXT
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS hashes (
                hash INTEGER NOT NULL,
                file_id INTEGER NOT NULL,
                t_anchor_cs INTEGER NOT NULL
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_hash ON hashes(hash)")

    def close(self):
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    @staticmethod
    def _file_hash(file_bytes):
        return hashlib.sha256(file_bytes).hexdigest()

    def has_file(self, file_bytes):
        fh = self._file_hash(file_bytes)
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM files WHERE file_hash = ? LIMIT 1", (fh,)
            ).fetchone()
        return row is not None

    def add_file(self, file_bytes, hashes):
        fh = self._file_hash(file_bytes)
        with self._lock:
            row = self._conn.execute(
                "SELECT file_id FROM files WHERE file_hash = ? LIMIT 1", (fh,)
            ).fetchone()
            if row is not None:
                return

            try:
                self._conn.execute("BEGIN IMMEDIATE")
                cur = self._conn.execute(
                    "INSERT INTO files (file_hash, indexed_at) VALUES (?, ?)",
                    (fh, datetime.now().isoformat()),
                )
                file_id = cur.lastrowid
                if hashes:
                    self._conn.executemany(
                        "INSERT INTO hashes (hash, file_id, t_anchor_cs) VALUES (?, ?, ?)",
                        [
                            (int(h), file_id, int(round(t * 100)))
                            for h, t in hashes
                        ],
                    )
                self._conn.execute("COMMIT")
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def query(self, query_hashes, top_k=DEFAULT_TOP_K, offset_bin_cs=OFFSET_BIN_CS):
        if not query_hashes:
            return []

        query_map = defaultdict(list)
        for h, t in query_hashes:
            query_map[int(h)].append(int(round(t * 100)))

        unique_hashes = list(query_map.keys())
        CHUNK = 900
        votes = defaultdict(lambda: defaultdict(int))

        with self._lock:
            for i in range(0, len(unique_hashes), CHUNK):
                chunk = unique_hashes[i:i + CHUNK]
                placeholders = ",".join("?" * len(chunk))
                cursor = self._conn.execute(
                    f"SELECT hash, file_id, t_anchor_cs FROM hashes WHERE hash IN ({placeholders})",
                    chunk,
                )
                for h, file_id, t_anchor_cs in cursor:
                    for t_q_cs in query_map[h]:
                        offset_bin = (t_anchor_cs - t_q_cs) // offset_bin_cs
                        votes[file_id][offset_bin] += 1

        if not votes:
            return []

        scored = []
        for file_id, bins in votes.items():
            best_bin, best_count = max(bins.items(), key=lambda kv: kv[1])
            scored.append((file_id, best_count, best_bin * offset_bin_cs))
        scored.sort(key=lambda r: r[1], reverse=True)
        top = scored[:top_k]

        if not top:
            return []

        file_ids = [f for f, _, _ in top]
        with self._lock:
            placeholders = ",".join("?" * len(file_ids))
            cursor = self._conn.execute(
                f"SELECT file_id, file_hash FROM files WHERE file_id IN ({placeholders})",
                file_ids,
            )
            id_to_hash = {fid: fh for fid, fh in cursor}

        return [
            (id_to_hash[fid], count, offset_cs * 0.01)
            for fid, count, offset_cs in top
            if fid in id_to_hash
        ]

    def stats(self):
        with self._lock:
            files_count = self._conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            hashes_count = self._conn.execute("SELECT COUNT(*) FROM hashes").fetchone()[0]
        return {"files": files_count, "hashes": hashes_count}
