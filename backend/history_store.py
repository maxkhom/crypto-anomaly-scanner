"""Versioned local receipt-price history; no trades or credentials are stored."""
import sqlite3
import json
import math
from pathlib import Path
from decimal import Decimal
from short_momentum import BOUNDARY_RETENTION_SECONDS


class HistoryStore:
    def __init__(self, path):
        self.path = Path(path)

    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.execute('''CREATE TABLE IF NOT EXISTS receipt_boundaries_v1 (
            symbol TEXT NOT NULL, boundary INTEGER NOT NULL, price TEXT,
            started REAL NOT NULL, PRIMARY KEY(symbol, boundary))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS anomaly_events_v1 (
            id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, interval_end TEXT NOT NULL,
            rule_version TEXT NOT NULL, payload TEXT NOT NULL,
            UNIQUE(symbol, interval_end, rule_version))''')
        return conn

    def save(self, snapshots, now):
        conn = self.connection()
        try:
            with conn:
                for symbol, started, rows in snapshots:
                    if started is None:
                        continue
                    conn.executemany('''INSERT INTO receipt_boundaries_v1 VALUES (?, ?, ?, ?)
                        ON CONFLICT(symbol, boundary) DO UPDATE SET price=excluded.price, started=excluded.started''',
                        [(symbol, int(stamp), price, started) for stamp, price in rows])
                conn.execute('DELETE FROM receipt_boundaries_v1 WHERE boundary < ? OR boundary > ?',
                             (math.floor(now / 10) * 10 - BOUNDARY_RETENTION_SECONDS, now))
        finally:
            conn.close()

    def load(self, now):
        conn = self.connection()
        try:
            rows = conn.execute('''SELECT symbol, boundary, price, started
                FROM receipt_boundaries_v1 WHERE boundary >= ? AND boundary <= ?
                ORDER BY boundary''', (math.floor(now / 10) * 10 - BOUNDARY_RETENTION_SECONDS, now)).fetchall()
            result = {}
            for symbol, stamp, price, started in rows:
                value = None if price is None else Decimal(price)
                if stamp % 10 or started > stamp or (value is not None and (not value.is_finite() or value <= 0)):
                    raise ValueError('Invalid saved price history')
                item = result.setdefault(symbol, {"started": started, "rows": []})
                item["rows"].append((stamp, value))
            return result
        finally:
            conn.close()

    def save_events(self, events):
        if not events:
            return
        conn = self.connection()
        try:
            with conn:
                conn.executemany('INSERT OR IGNORE INTO anomaly_events_v1 (symbol, interval_end, rule_version, payload) VALUES (?, ?, ?, ?)',
                    [(event['symbol'], event['interval_end'], event['rule_version'], json.dumps(event)) for event in events])
        finally:
            conn.close()

    def list_events(self, limit=50):
        conn = self.connection()
        try:
            total = conn.execute('SELECT COUNT(*) FROM anomaly_events_v1').fetchone()[0]
            rows = conn.execute('SELECT id, payload FROM anomaly_events_v1 ORDER BY interval_end DESC, id DESC LIMIT ?', (limit,)).fetchall()
            return {'total': total, 'count': len(rows), 'items': [dict(json.loads(payload), id=identifier) for identifier, payload in rows]}
        finally:
            conn.close()
