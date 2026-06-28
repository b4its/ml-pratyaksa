import sqlite3
import json
from datetime import datetime, timedelta

class OfflineBuffer:
    def __init__(self, db_path="offline_buffer.db", ttl_hours=72):
        self.ttl = ttl_hours
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_table()

    def _create_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS buffer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                payload TEXT,
                sent INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()

    def store(self, payload: dict):
        ts = datetime.utcnow().isoformat()
        self.conn.execute("INSERT INTO buffer (timestamp, payload) VALUES (?, ?)",
                        (ts, json.dumps(payload)))
        self.conn.commit()

    def get_unsent(self, limit=100):
        cur = self.conn.execute(
            "SELECT id, timestamp, payload FROM buffer WHERE sent=0 ORDER BY id LIMIT ?",
            (limit,))
        return cur.fetchall()

    def mark_sent(self, ids):
        self.conn.executemany("UPDATE buffer SET sent=1 WHERE id=?", [(i,) for i in ids])
        self.conn.commit()

    def cleanup(self):
        cutoff = (datetime.utcnow() - timedelta(hours=self.ttl)).isoformat()
        self.conn.execute("DELETE FROM buffer WHERE timestamp < ?", (cutoff,))
        self.conn.commit()