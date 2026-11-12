"""The FastAPI application: trips, GPS ingest, the events WebSocket and /ask.

    TURNWISE_API_TOKEN=<secret> uvicorn backend.app:app_from_env --factory

Endpoints (contracts in docs/contracts/):
    POST /v1/trips                      create a trip: route it with Valhalla, start an engine
    POST /v1/trips/{id}/end             stop tracking this trip
    POST /v1/gps                        batch of GPS fixes          -> 202 {accepted, duplicates}
    WS   /v1/trips/{id}/events          off_route, decision_point_ahead, arrived, ...
    POST /v1/ask                        {trip_id, intent, slots}    -> {answer_key, facts}
    GET  /healthz
    GET  /field                         phone-browser test client (only with TURNWISE_FIELD_KIT=1)

Authentication is a single shared bearer token for now (a placeholder: per-driver
JWTs, roles and consent checks come with the security work). The server refuses to
start without a token rather than run open.
"""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from backend.db import make_engine, make_session_factory
from backend.persistence import TripPersistence, UnknownReference
from backend.recorder import TraceRecorder
from backend.registry import TripRegistry, TripState
from backend.schemas import (AskRequest, AskResponse, GpsAccepted, GpsBatch, TripCreate, TripCreated)
from backend.settings import Settings
from engine.trip import TripEngine
from engine.valhalla import fetch_bundle, http_transport

# Turns (origin, destination) into a route bundle. Replaceable, so tests need no Valhalla.
RouteProvider = Callable[[tuple[float, float], tuple[float, float]], dict]


WS_SUBPROTOCOL = "turnwise"


def _authorized(header: str | None, token: str) -> bool:
    scheme, _, value = (header or "").partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(value.encode(), token.encode())


def _ws_subprotocol_token_ok(ws: WebSocket, token: str) -> bool:
    """Browsers cannot set an Authorization header on a WebSocket, so a browser client sends
    the token as the second subprotocol: `new WebSocket(url, ["turnwise", token])`.
    (Not in the URL, which would end up in logs and history.)"""
    offered = ws.scope.get("subprotocols") or []
    return (len(offered) == 2 and offered[0] == WS_SUBPROTOCOL
            and secrets.compare_digest(offered[1].encode(), token.encode()))


def create_app(settings: Settings | None = None, route_provider: RouteProvider | None = None,
               registry: TripRegistry | None = None, persistence: TripPersistence | None = None,
               on_shutdown: Callable[[], object] | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if not settings.api_token:
        raise RuntimeError("TURNWISE_API_TOKEN is not set; refusing to start an open server")
    if route_provider is None:
        transport = http_transport(settings.valhalla_url)
        route_provider = lambda origin, dest: fetch_bundle(transport, origin, dest)  # noqa: E731

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if persistence is not None:
            await persistence.startup()                     # make sure the fleet row exists
        yield
        if on_shutdown is not None:
            await on_shutdown()

    app = FastAPI(title="TurnWise", version="0.1", lifespan=lifespan)
    app.state.registry = registry or TripRegistry(settings.event_backlog)
    recorder = TraceRecorder(settings.record_dir) if settings.record_dir else None

    async def on_event(trip_id: str, message: dict, fix: dict) -> None:
        if recorder is not None:
            recorder.event(trip_id, message)
        if persistence is not None:
            await persistence.on_event(trip_id, message, fix)

    if persistence is not None or recorder is not None:
        app.state.registry.sink = on_event
    if recorder is not None:
        app.state.registry.fix_sink = recorder.fix

    def require_auth(request: Request) -> None:
        if not _authorized(request.headers.get("authorization"), settings.api_token):
            raise HTTPException(401, "missing or invalid bearer token", headers={"WWW-Authenticate": "Bearer"})

    def active_trip(trip_id: str) -> TripState:
        """The trip, or 403 (unknown ids look the same as someone else's trip) / 409 (ended)."""
        state = app.state.registry.get(trip_id)
        if state is None:
            raise HTTPException(403, "trip not found for this driver")
        if not state.active:
            raise HTTPException(409, "trip is not active")
        return state

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/v1/trips", status_code=201, response_model=TripCreated, dependencies=[Depends(require_auth)])
    async def create_trip(body: TripCreate):
        origin, dest = (body.origin.lat, body.origin.lon), (body.destination.lat, body.destination.lon)
        try:
            bundle = await run_in_threadpool(route_provider, origin, dest)
            engine = TripEngine(bundle)
        except Exception:                      # routing service down, no route found, ...
            raise HTTPException(502, "could not plan a route") from None
        state = app.state.registry.create(engine)
        if persistence is not None:
            try:
                await persistence.trip_created(
                    trip_id=state.trip_id, route=engine.route, route_length_m=engine.length_m,
                    started_at=datetime.now(timezone.utc), driver_id=body.driver_id, vehicle_id=body.vehicle_id)
            except UnknownReference as missing:
                app.state.registry.discard(state.trip_id)
                raise HTTPException(422, f"unknown {missing} for this fleet") from None
            except Exception:                  # database down: do not start a trip we cannot record
                app.state.registry.discard(state.trip_id)
                raise HTTPException(503, "could not record the trip") from None
        if recorder is not None:
            recorder.start(state.trip_id, bundle)
        return TripCreated(trip_id=state.trip_id, length_m=engine.length_m, decision_points=len(engine.points))

    @app.post("/v1/trips/{trip_id}/end", status_code=204, dependencies=[Depends(require_auth)])
    async def end_trip(trip_id: str):
        state = active_trip(trip_id)
        app.state.registry.end(state)
        if persistence is not None:
            last_fix = datetime.fromtimestamp(state.last_t, timezone.utc) if state.last_t else None
            await persistence.trip_ended(trip_id, datetime.now(timezone.utc), last_fix)

    @app.post("/v1/gps", status_code=202, response_model=GpsAccepted, dependencies=[Depends(require_auth)])
    async def ingest_gps(batch: GpsBatch):
        state = active_trip(batch.points[0].trip_id)
        result = await app.state.registry.ingest(state, [p.model_dump() for p in batch.points])
        return GpsAccepted(accepted=result.accepted, duplicates=result.duplicates, late=result.late)

    @app.post("/v1/ask", response_model=AskResponse, dependencies=[Depends(require_auth)])
    async def ask(body: AskRequest):
        state = active_trip(body.trip_id)
        return AskResponse(**state.engine.ask(body.intent, body.slots))

    @app.websocket("/v1/trips/{trip_id}/events")
    async def events(ws: WebSocket, trip_id: str, last_seq: int = 0):
        # Authenticate before accepting: a bad client never gets a socket.
        state = app.state.registry.get(trip_id)
        by_header = _authorized(ws.headers.get("authorization"), settings.api_token)
        by_subprotocol = _ws_subprotocol_token_ok(ws, settings.api_token)
        if not (by_header or by_subprotocol) or state is None or not state.active:
            await ws.close(code=1008)          # policy violation
            return
        await ws.accept(subprotocol=WS_SUBPROTOCOL if by_subprotocol else None)
        missed, queue = app.state.registry.subscribe(state, last_seq)
        listener = asyncio.ensure_future(ws.receive())      # completes when the client disconnects
        try:
            for message in missed:
                await ws.send_json(message)
            while True:
                getter = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({getter, listener}, return_when=asyncio.FIRST_COMPLETED)
                if listener in done:
                    getter.cancel()
                    break
                message = getter.result()
                if message is None:            # trip ended
                    await ws.close(code=1000)
                    break
                await ws.send_json(message)
        except WebSocketDisconnect:
            pass
        finally:
            listener.cancel()
            app.state.registry.unsubscribe(state, queue)

    if settings.field_kit:
        from backend import field              # imports voice/, which the core API does not need
        field.install(app, require_auth, active_trip)

    return app


def app_from_env() -> FastAPI:
    """Entry point for `uvicorn backend.app:app_from_env --factory`."""
    settings = Settings.from_env()
    if not settings.database_url:
        return create_app(settings)            # no DATABASE_URL: trips live in memory only
    engine = make_engine(settings.database_url)
    persistence = TripPersistence(make_session_factory(engine), settings.fleet_name)
    return create_app(settings, persistence=persistence, on_shutdown=engine.dispose)
