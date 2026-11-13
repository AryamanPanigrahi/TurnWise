"""Track Sarvam spend per driver per day and alert above the cap (default ₹5).

The "day" is the IST calendar day (India has no DST, so a fixed +05:30 offset
is exact). In-memory for now; move to Redis when the backend exists so every
worker shares the totals.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from typing import Callable

IST = timezone(timedelta(hours=5, minutes=30), "IST")

AlertFn = Callable[[str, date, float, float], None]  # (driver_id, ist_day, spent, cap)


def ist_day(ts: datetime) -> date:
    if ts.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware (store UTC)")
    return ts.astimezone(IST).date()


class CostGuard:
    def __init__(self, cap_inr: float, on_exceeded: AlertFn | None = None):
        self.cap = cap_inr
        self.on_exceeded = on_exceeded
        self._spent: dict[tuple[str, date], float] = {}
        self._alerted: set[tuple[str, date]] = set()
        self._lock = threading.Lock()

    def add(self, driver_id: str, inr: float, ts: datetime) -> float:
        """Record spend; returns the driver's total for that IST day."""
        if inr < 0:
            raise ValueError("cost must be >= 0")
        key = (driver_id, ist_day(ts))
        with self._lock:
            total = self._spent.get(key, 0.0) + inr
            self._spent[key] = total
            fire = total > self.cap and key not in self._alerted
            if fire:
                self._alerted.add(key)
        if fire and self.on_exceeded:  # once per driver per day; outside the lock
            self.on_exceeded(driver_id, key[1], total, self.cap)
        return total

    def spent(self, driver_id: str, ts: datetime) -> float:
        return self._spent.get((driver_id, ist_day(ts)), 0.0)

    def over_cap(self, driver_id: str, ts: datetime) -> bool:
        return self.spent(driver_id, ts) > self.cap
