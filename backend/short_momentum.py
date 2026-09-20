"""Completed ten-second returns on the local UTC receipt clock."""
from collections import deque
from decimal import Decimal
from datetime import datetime, timezone
import math
from price_acceleration import calculate_price_acceleration
from anomaly_score import calculate_anomaly_score

PRICE_BASELINE_COUNT = 180
PRICE_LOOKBACK_SECONDS = 45 * 60
# Search the 45 minutes BEFORE the evaluated interval; retain its two endpoints too.
BOUNDARY_RETENTION_SECONDS = PRICE_LOOKBACK_SECONDS + 10
MAX_BOUNDARIES = BOUNDARY_RETENTION_SECONDS // 10 + 1

def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


class ShortMomentum:
    def __init__(self):
        self.started = None
        self.last_sample = None
        self.next_boundary = None
        self.boundaries = deque(maxlen=MAX_BOUNDARIES)

    def advance(self, now):
        if self.next_boundary is None:
            return
        if now < self.started or (self.last_sample and now < self.last_sample[0]):
            self.__init__()
            return
        # Large gaps must not create unbounded work.
        if now - self.next_boundary > BOUNDARY_RETENTION_SECONDS + 10:
            self.boundaries.clear()
            self.next_boundary = math.floor(now / 10) * 10 - BOUNDARY_RETENTION_SECONDS
        while self.next_boundary <= now:
            price = None
            if self.last_sample and 0 < self.next_boundary - self.last_sample[0] <= 2:
                price = self.last_sample[1]
            self.boundaries.append((self.next_boundary, price))
            self.next_boundary += 10

    def add(self, now, price):
        if self.last_sample and now < self.last_sample[0]:
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

        selected = []
        skipped = 0
        # Newest first; missing adjacent prices never become a longer return.
        for offset in range(1, PRICE_LOOKBACK_SECONDS // 10 + 1):
            right = end - offset * 10
            value = change(right)
            if value is None:
                skipped += 1
                continue
            selected.append((right, value))
            if len(selected) == PRICE_BASELINE_COUNT:
                break
        valid = [value for _, value in selected]
        current = change(end)
        oldest = selected[-1][0] - 10 if selected else None
        newest = selected[0][0] if selected else None
        history = {"version": "price_latest_valid_45m_v2", "selection_method": "latest_valid_returns",
                   "required_intervals": PRICE_BASELINE_COUNT, "valid_intervals": len(valid),
                   "missing_intervals": PRICE_BASELINE_COUNT - len(valid),
                   "skipped_intervals": skipped, "max_lookback_seconds": PRICE_LOOKBACK_SECONDS,
                   "search_from": iso(end - BOUNDARY_RETENTION_SECONDS), "search_to": iso(end - 10),
                   "baseline_from": iso(oldest) if oldest is not None else None,
                   "baseline_to": iso(newest) if newest is not None else None,
                   "baseline_span_seconds": newest - oldest if selected else None,
                   "baseline_age_seconds": end - 10 - oldest if selected else None,
                   "evaluated_from": iso(end - 10), "evaluated_to": iso(end),
                   "current_return_status": "ok" if current is not None else "missing_data",
                   "status": "unavailable", "reason": "feed_unavailable", "percentile": None}
        acceleration = calculate_price_acceleration(
            [change(end - offset * 10) for offset in range(181, -1, -1)],
            live and self.started is not None,
            self.started is None or self.started > end - 1820,
        )
        acceleration.update(baseline_from=iso(end - 1810), baseline_to=iso(end - 10),
                            baseline_support_from=iso(end - 1820),
                            evaluated_from=iso(end - 10), evaluated_to=iso(end))
        result = {"time_basis": "local_receipt_utc", "period_seconds": 10,
                  "status": "unavailable", "windows": [], "change_pp": None,
                  "history": history, "price_acceleration": acceleration,
                  "anomaly_score": calculate_anomaly_score({'price_acceleration': acceleration})}
        if not live or self.started is None:
            return result
        history["status"] = "warming_up" if self.started > end - 1810 else "missing_data"
        history["reason"] = "missing_current_return" if current is None else "insufficient_valid_returns"
        if len(valid) == PRICE_BASELINE_COUNT and current is not None:
            history["status"] = "ok"
            history["reason"] = None
            # Strict comparison: equal moves do not count as exceeded.
            history["percentile"] = round(100 * sum(abs(value) < abs(current) for value in valid) / PRICE_BASELINE_COUNT, 2)
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
