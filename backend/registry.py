"""Live trips, in memory: one TripEngine per active trip, plus its event log and listeners.

This is the seam where Redis goes later (live positions, pub/sub across several
server processes). The router code only talks to `TripRegistry`, so swapping the
storage does not touch the endpoints.

DPDP (CLAUDE.md rule 5): raw GPS is NOT stored here. We keep the engine's state,
the last fix time, a short window of fix times for de-duplication, and the event
log (which holds distances and road names, not coordinates).
"""

from __future__ import annotations

import asyncio
import secrets
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

from engine.trip import TripEngine
from engine.wrong_way import Event

SEEN_WINDOW = 2000     # how many recent fix times to remember for de-duplication


def stop_id(trip_id: str, seq: int) -> str:
    """Public id of a trip's stop: "stp_<trip hex>_<seq>" (seq 0 = origin, last = destination)."""
    return f"stp_{trip_id.removeprefix('trp_')}_{seq}"


def _epoch(ts: str) -> float:
    return datetime.fromisoformat(ts[:-1] + "+00:00").astimezone(timezone.utc).timestamp()


@dataclass
class IngestResult:
    accepted: int = 0
    duplicates: int = 0
    late: int = 0


@dataclass
class TripState:
    trip_id: str
    engine: TripEngine
    backlog: int
    active: bool = True
    seq: int = 0
    last_t: float | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    log: deque = field(default_factory=deque)
    subscribers: set = field(default_factory=set)
    _seen: set = field(default_factory=set)
    _seen_order: deque = field(default_factory=deque)

    def remember(self, t: float) -> None:
        self._seen.add(t)
        self._seen_order.append(t)
        if len(self._seen_order) > SEEN_WINDOW:
            self._seen.discard(self._seen_order.popleft())


# Called AFTER an event has been published to listeners: (trip_id, message, the GPS fix that caused it).
EventSink = Callable[[str, dict, dict], Awaitable[None]]


class TripRegistry:
    def __init__(self, event_backlog: int = 500, sink: EventSink | None = None):
        self._trips: dict[str, TripState] = {}
        self._backlog = event_backlog
        self.sink = sink            # e.g. the database writer; must not raise
        self.fix_sink: Callable[[str, dict], None] | None = None   # dev trace recorder: every processed fix

    # -- lifecycle -------------------------------------------------------------------
    def create(self, engine: TripEngine) -> TripState:
        trip_id = "trp_" + secrets.token_hex(8)           # unguessable
        state = TripState(trip_id, engine, self._backlog, log=deque(maxlen=self._backlog))
        self._trips[trip_id] = state
        return state

    def get(self, trip_id: str) -> TripState | None:
        return self._trips.get(trip_id)

    def discard(self, trip_id: str) -> None:
        """Forget a trip that never really started (e.g. it could not be recorded)."""
        self._trips.pop(trip_id, None)

    def end(self, state: TripState) -> None:
        """Stop tracking: no more fixes accepted, listeners told to disconnect."""
        state.active = False
        for q in list(state.subscribers):
            q.put_nowait(None)

    # -- GPS in -------------------------------------------------------------------------
    async def ingest(self, state: TripState, points: list[dict]) -> IngestResult:
        """Feed a batch (any order, may repeat) into the trip's engine, oldest first."""
        result = IngestResult()
        async with state.lock:                            # one batch at a time per trip
            for p in sorted(points, key=lambda p: _epoch(p["ts"])):
                t = _epoch(p["ts"])
                if t in state._seen:
                    result.duplicates += 1
                    continue
                state.remember(t)
                result.accepted += 1
                if state.last_t is not None and t <= state.last_t:
                    result.late += 1                      # engine needs time to move forward
                    continue
                state.last_t = t
                if self.fix_sink is not None:
                    self.fix_sink(state.trip_id, p)
                for event in state.engine.update(p):
                    message = self.publish(state, event)
                    if self.sink is not None:           # after publishing: alerts never wait for storage
                        await self.sink(state.trip_id, message, p)
        return result

    # -- events out -------------------------------------------------------------------
    def publish(self, state: TripState, event: Event) -> dict:
        state.seq += 1
        data = event.data
        if event.event == "arrived":
            # events.md: arrived carries the stop that was reached. A trip has origin (0) and
            # destination (1) for now, so arriving always means the destination stop.
            data = {"stop_id": stop_id(state.trip_id, 1), **data}
        message = {"event": event.event, "trip_id": state.trip_id, "ts": event.ts,
                   "seq": state.seq, "data": data}
        state.log.append(message)
        for q in list(state.subscribers):
            q.put_nowait(message)
        return message

    def subscribe(self, state: TripState, last_seq: int = 0) -> tuple[list[dict], asyncio.Queue]:
        """Events the client missed (seq > last_seq), plus a queue for new ones."""
        q: asyncio.Queue = asyncio.Queue()
        missed = [m for m in state.log if m["seq"] > last_seq]
        state.subscribers.add(q)
        return missed, q

    def unsubscribe(self, state: TripState, q: asyncio.Queue) -> None:
        state.subscribers.discard(q)
