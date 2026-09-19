"""Versioned local receipt-price history; no trades or credentials are stored."""
import sqlite3
from pathlib import Path
from decimal import Decimal


class HistoryStore:
    def __init__(self, path):
        self.path = Path(path)

    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.execute('''CREATE TABLE IF NOT EXISTS receipt_boundaries_v1 (
            symbol TEXT NOT NULL, boundary INTEGER NOT NULL, price TEXT,
            started REAL NOT NULL, PRIMARY KEY(symbol, boundary))''')
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
                conn.execute('DELETE FROM receipt_boundaries_v1 WHERE boundary < ? OR boundary > ?', (now - 1830, now))
        finally:
            conn.close()

    def load(self, now):
        conn = self.connection()
        try:
            rows = conn.execute('''SELECT symbol, boundary, price, started
                FROM receipt_boundaries_v1 WHERE boundary >= ? AND boundary <= ?
                ORDER BY boundary''', (now - 1810, now)).fetchall()
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
