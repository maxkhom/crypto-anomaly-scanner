"""Short price moves measured by local receipt time, not exchange candle time."""
from collections import deque
from decimal import Decimal


class ShortMomentum:
    def __init__(self):
        # Retain the last received price per local second; memory stays bounded.
        self.samples = deque(maxlen=120)
        self.started = None

    def add(self, now, price):
        if self.samples and now - self.samples[-1][0] > 15:
            self.__init__()
        if self.started is None:
            self.started = now
        if self.samples and int(self.samples[-1][0]) == int(now):
            self.samples.pop()
        self.samples.append((now, Decimal(price)))

    def calculate(self, now, live):
        result = {"time_basis": "local_receipt_clock", "period_seconds": 10,
                  "status": "unavailable", "windows": [], "change_pp": None}
        if not live or self.started is None:
            return result
        # Boundaries are relative to the first received trade in this connection.
        end = self.started + int((now - self.started) // 10) * 10
        if end - self.started < 40:
            result["status"] = "warming_up"
            return result

        def boundary_price(boundary):
            eligible = [(stamp, price) for stamp, price in self.samples if stamp <= boundary]
            if not eligible or boundary - eligible[-1][0] > 2:
                return None
            return eligible[-1][1]

        changes = []
        for offset in (2, 1, 0):
            right = end - offset * 10
            left = right - 10
            opening, closing = boundary_price(left), boundary_price(right)
            change = None if opening is None or closing is None else (closing / opening - 1) * 100
            changes.append(change)
            result["windows"].append({
                "from_seconds_ago": round(now - left, 2),
                "to_seconds_ago": round(now - right, 2),
                "percent": None if change is None else round(float(change), 4),
                "status": "missing_data" if change is None else "ok",
            })
        result["status"] = "ok" if all(x is not None for x in changes) else "missing_data"
        if changes[-1] is not None and changes[-2] is not None:
            result["change_pp"] = round(float(changes[-1] - changes[-2]), 4)
        return result
