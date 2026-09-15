"""Price returns over complete windows of closed one-minute candles."""

from decimal import Decimal

from bitunix import iso_time

MINUTE_MS = 60_000
PERIODS = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}


def calculate_price_changes(candles: list[dict], as_of_ms: int) -> dict:
    # Anchor to the expected latest closed minute, not an older available row.
    reference_time = as_of_ms // MINUTE_MS * MINUTE_MS
    closed = {
        candle["close_time_ms"]: candle
        for candle in candles
        if candle["is_closed"] and candle["close_time_ms"] <= reference_time
    }
    reference = closed.get(reference_time)
    changes = {}
    for label, minutes in PERIODS.items():
        start = reference_time - minutes * MINUTE_MS
        expected_times = range(start, reference_time + 1, MINUTE_MS)
        missing = [timestamp for timestamp in expected_times if timestamp not in closed]
        result = {
            "percent": None,
            "status": "insufficient_data" if missing else "ok",
            "from_time": iso_time(start),
            "to_time": iso_time(reference_time),
            "missing_count": len(missing),
            "warning_count": 0,
        }
        if not missing:
            opening_price = Decimal(closed[start]["close"])
            ending_price = Decimal(reference["close"])
            # Candle service validates prices; keep the formula safe in isolation.
            if not opening_price.is_finite() or not ending_price.is_finite() or opening_price <= 0 or ending_price <= 0:
                result["status"] = "invalid_price"
            else:
                result["percent"] = float(round((ending_price / opening_price - 1) * 100, 4))
                result["warning_count"] = sum(bool(closed[timestamp].get("warnings")) for timestamp in expected_times)
        changes[label] = result
    return {
        "reference_time": iso_time(reference_time),
        "reference_price": reference["close"] if reference else None,
        "latest_available_close_time": iso_time(max(closed)) if closed else None,
        "changes": changes,
    }
