"""Field-test kit: a phone-browser driver client for testing before the Android app exists.

Enabled only when `TURNWISE_FIELD_KIT=1`. It adds:

    GET  /field                        the page (backend/static/field.html)
    GET  /field/api/trips/{id}/route   the planned route and decision points, to draw on the map
    POST /field/api/say                turn an answer or an event into a sentence, via voice/templates

The page uses the SAME contract endpoints as the real app (/v1/trips, /v1/gps, /v1/ask and
the events WebSocket), so a field test exercises the real pipeline. Speech on the phone is
the browser's built-in voice: a stand-in for Sarvam TTS, good enough to hear the alerts.

Rule 1 still holds here: the sentences come from the engine's facts through Ram's
templates. Nothing in this file decides a direction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from backend.registry import TripState
from engine.trip import BRANCH_TYPES, BRANCHES, SIDE
from voice.answer import render_alert, render_answer
from voice.templates import available_languages

PAGE = Path(__file__).parent / "static" / "field.html"


class SayRequest(BaseModel):
    lang: str = "en"
    # either an answer from POST /v1/ask ...
    answer_key: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    # ... or an event from the WebSocket
    event: Literal["off_route", "back_on_route", "decision_point_ahead", "arrived"] | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class SayResponse(BaseModel):
    text: str | None          # None = nothing worth saying aloud
    template: str | None = None


def sentence_for_event(lang: str, event: str, data: dict) -> tuple[str | None, str | None]:
    """The spoken line for a pushed event, or (None, None) to stay silent."""
    if event in ("off_route", "back_on_route"):
        r = render_alert(lang, event, data)              # templated only, never the AI model (rule 2)
        return r.text, r.template_key
    if event == "decision_point_ahead":
        if data.get("type") in BRANCH_TYPES and data.get("on_route") in BRANCHES:
            r = render_answer(lang, f"which_branch.{data['on_route']}", data)
        elif SIDE.get(data.get("maneuver")) in ("left", "right"):
            # "straight" is skipped on purpose: its template ("Go straight for 90 metres") means
            # "keep going", which is the wrong thing to say about a fork 90 m ahead.
            r = render_answer(lang, f"left_or_right.{SIDE[data['maneuver']]}", data)
        else:
            return None, None
        # An unprompted "I'm not sure" helps nobody: stay silent when the facts are too weak.
        return (None, None) if r.fell_back else (r.text, r.template_key)
    return None, None                                    # arrived: shown on screen, no template yet


def install(app: FastAPI, require_auth: Callable, active_trip: Callable[[str], TripState]) -> None:
    router = APIRouter()

    @router.get("/field", response_class=HTMLResponse, include_in_schema=False)
    def page():
        # The page itself holds no secrets; every API call it makes carries the bearer token.
        return HTMLResponse(PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})

    @router.get("/field/api/languages", dependencies=[Depends(require_auth)])
    def languages():
        return {"languages": available_languages()}

    @router.get("/field/api/trips/{trip_id}/route", dependencies=[Depends(require_auth)])
    def route(trip_id: str):
        engine = active_trip(trip_id).engine
        return {
            "route": [[lat, lon] for lat, lon in engine.route],
            "length_m": engine.length_m,
            "decision_points": [{"at_m": round(p.at_m), **p.fact_card(0)} for p in engine.points],
        }

    @router.post("/field/api/say", response_model=SayResponse, dependencies=[Depends(require_auth)])
    def say(body: SayRequest):
        if body.lang not in available_languages():
            raise HTTPException(422, f"no templates for language '{body.lang}'")
        if body.event:
            text, key = sentence_for_event(body.lang, body.event, body.data)
            return SayResponse(text=text, template=key)
        if body.answer_key:
            r = render_answer(body.lang, body.answer_key, body.facts)
            if body.answer_key == "am_i_wrong.off_route" and r.fell_back:
                # The engine knows the driver is off route but not yet how to recover, and the
                # answer template needs a distance. Say the generic wrong-way alert, not "not sure".
                r = render_alert(body.lang, "off_route", {})
            return SayResponse(text=r.text, template=r.template_key)
        raise HTTPException(422, "send either answer_key or event")

    app.include_router(router)
