"""Completed ten-second returns on the local UTC receipt clock."""
from collections import deque
from decimal import Decimal
from datetime import datetime, timezone
import math


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


class ShortMomentum:
    def __init__(self):
        self.started = None
        self.last_sample = None
        self.next_boundary = None
        # 182 prices define 181 returns: 180 baseline + one evaluated return.
        self.boundaries = deque(maxlen=182)

    def advance(self, now):
        if self.next_boundary is None:
            return
        if now < self.started or (self.last_sample and now < self.last_sample[0]):
            self.__init__()
            return
        # Large gaps must not create unbounded work.
        if now - self.next_boundary > 1830:
            self.__init__()
            return
        while self.next_boundary <= now:
            price = None
            if self.last_sample and 0 < self.next_boundary - self.last_sample[0] <= 2:
                price = self.last_sample[1]
            self.boundaries.append((self.next_boundary, price))
            self.next_boundary += 10

    def add(self, now, price):
        if self.last_sample and (now < self.last_sample[0] or now - self.last_sample[0] > 15):
            self.__init__()
        self.advance(now)
        if self.started is None:
            self.started = now
            self.next_boundary = (math.floor(now / 10) + 1) * 10
        self.last_sample = (now, Decimal(price))

    def calculate(self, now, live):
        self.advance(now)
        end = math.floor(now / 10) * 10
        prices = dict(self.boundaries)

        def change(right):
            opening, closing = prices.get(right - 10), prices.get(right)
            return None if opening is None or closing is None else (closing / opening - 1) * 100

        baseline = [change(end - offset * 10) for offset in range(180, 0, -1)]
        valid = [value for value in baseline if value is not None]
        current = change(end)
        history = {"required_intervals": 180, "valid_intervals": len(valid),
                   "missing_intervals": 180 - len(valid), "baseline_from": iso(end - 1810),
                   "baseline_to": iso(end - 10), "evaluated_from": iso(end - 10),
                   "evaluated_to": iso(end), "status": "unavailable", "percentile": None}
        result = {"time_basis": "local_receipt_utc", "period_seconds": 10,
                  "status": "unavailable", "windows": [], "change_pp": None,
                  "history": history}
        if not live or self.started is None:
            return result
        history["status"] = "warming_up" if self.started > end - 1810 else "missing_data"
        if len(valid) == 180 and current is not None:
            history["status"] = "ok"
            # Strict comparison: equal moves do not count as exceeded.
            history["percentile"] = round(100 * sum(abs(value) < abs(current) for value in valid) / 180, 2)
        if len(self.boundaries) < 4:
            result["status"] = "warming_up"
            return result
        changes = []
        for offset in (2, 1, 0):
            right = end - offset * 10
            value = change(right)
            changes.append(value)
            result["windows"].append({"from_time": iso(right - 10), "to_time": iso(right),
                "from_seconds_ago": round(now - right + 10, 2), "to_seconds_ago": round(now - right, 2),
                "percent": None if value is None else round(float(value), 4),
                "status": "missing_data" if value is None else "ok"})
        result["status"] = "ok" if all(value is not None for value in changes) else "missing_data"
        if changes[-1] is not None and changes[-2] is not None:
            result["change_pp"] = round(float(changes[-1] - changes[-2]), 4)
        return result
