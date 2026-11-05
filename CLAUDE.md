# CLAUDE.md — TurnWise

*TurnWise* is the project name (it replaces the earlier working name "Daari"). Trademark, Play Store and domain checks are still pending.

Voice-first navigation for commercial fleets in India: delivery, trucks, ambulances, school buses. It is a layer on top of existing map data. Drivers ask questions in their own language ("flyover or service road?", "left or right?", "how far?") and get instant, correct answers. They are warned within seconds of a wrong turn, instead of being silently rerouted. The fleet company gets a dashboard of deviations, delays and per-driver performance. **The fleet company is the customer; drivers are the users.**

## Working rules (read first)

- **Learning-first setup.** On this project, **do not install dependencies, build Docker images, start containers, or run migrations on your own the first time.** For each new setup step:
  1. Explain what it does and why: what a Docker image is, what PostGIS adds to Postgres, how Valhalla builds its routing tiles, how SQLAlchemy maps tables, and so on.
  2. Give me the exact commands.
  3. Let me run them myself.

  Once I've done a step once, you may run it directly afterwards. The goal: I understand and can run every part of this project without Claude.
- **Small steps.** Explain your reasoning briefly before large changes. Prefer small, reviewable commits on feature branches.
- **Tests.** Every feature in the route engine ships with tests that replay recorded GPS traces.

## Team and ownership

Two founders: **Aryaman** and **Ram**. Each owns some areas and reviews the other's pull requests. Nothing merges to `main` without the other's review.

**Aryaman: route engine, backend, security**

- `routing/` and `engine/`: Valhalla setup, map-matching, decision-point fact cards, wrong-way detection, landmarks, and replay tests on `traces/`.
- `backend/`:
  - **APIs:** trips, stops, drivers, vehicles, GPS ingest, and the live-location WebSocket.
  - **Data:** deviation log and report jobs.
- **Security and DPDP:**
  - Authentication and role-based access.
  - Consent at driver onboarding and GPS retention jobs.
  - Encryption at rest, the audit log, and secrets handling.

**Ram: voice, driver app, dashboard**

- `voice/`:
  - **Sarvam:** speech-to-text and text-to-speech clients.
  - **Answers:** intent router, the `templates/<lang>.yaml` files, the AI-model fallback, and caching of generated speech for templated answers.
  - **Monitoring:** latency and cost logging.
- `app/`: the Android driver app, covering GPS streaming, push-to-talk, audio playback, offline buffering and the alert UI.
- `dashboard/`: live map, trip timeline, deviation heatmap and reports.

**Shared**

- Recording test drives, including deliberate wrong turns.
- Auditing OpenStreetMap coverage on pilot routes.
- The demo video.
- Fleet outreach and audit reports.
- `docs/decisions.md`.

### Interface contracts (agree these first; change only together)

Keep them in `docs/contracts/`:

- `POST /v1/gps`: a batch of `{trip_id, ts, lat, lon, speed, heading, accuracy}` from the app.
- `WS /v1/trips/{id}/events`: the server pushes `off_route`, `decision_point_ahead` and `arrived` events.
- `POST /v1/ask`: `{trip_id, intent, slots}`, returning `{answer_key, facts}`. The voice layer turns `answer_key` and `facts` into speech.
- **Fact card JSON schema:** `{type, on_route, alternatives, distance_m, landmark, confidence}`.

### Milestones

- **Week 1:**
  - Agree the contracts.
  - Get Valhalla running on the Karnataka extract.
  - Record 5–10 drives.
- **Weeks 2–3:**
  - Aryaman: the engine passes replay tests.
  - Ram: the voice loop on a laptop (Kannada and Hindi, 6 templated intents).
- **Weeks 4–5:**
  - Aryaman: GPS ingest, events WebSocket, the `/ask` endpoint.
  - Ram: the Android app consuming them.
- **Week 6:** an end-to-end demo drive and the 60-second demo video. Start fleet outreach.
- **Weeks 7–8:**
  - Ram: the dashboard.
  - Aryaman: consent, retention, audit log, the cost guard.
  - First free 2-week fleet audit.

## Non-negotiable product rules

1. **The AI model never decides directions.** All navigation facts come from the deterministic route engine: which branch is on the route, distance to the next manoeuvre, wrong-way status. The model only (a) understands the driver's question and (b) phrases facts it was given. If a fact isn't available, the answer is "I'm not sure, follow the screen," never a guess.
2. **Wrong-way alerts never go through the AI model.** Use pure geometry and heading logic, with templated speech. Latency target: alert within ≤ 2 s of the deviation being certain.
3. **Latency budget for voice Q&A:** ≤ 1.5 s from end of speech to start of the spoken answer for the templated questions. The AI model path is allowed ≤ 3 s; if it's slower, fall back to "please repeat."
4. **Never stream audio continuously.** Use push-to-talk, or a wake word detected on the device. Send audio to Sarvam only while the driver is asking. (Continuous streaming costs about ₹235 per driver per day; the target is ≤ ₹5.)
5. **Driver location is personal data under the DPDP Act.**
   - Track only while on duty and on a trip, with consent recorded at onboarding.
   - Set a retention period (default 90 days for raw GPS; aggregates kept longer).
   - Access is role-based; every export and admin view is audit-logged.
   - Raw GPS is encrypted at rest.
6. **Respect map data licences.**
   - OpenStreetMap is ODbL: show attribution "© OpenStreetMap contributors". Understand the share-alike duty for derived databases before mixing OSM with other data.
   - Do not scrape, screen-read, or wrap the Google Maps app.
   - If Google's Navigation SDK or Routes API is added later, follow its terms; for example, Google content may not be shown on non-Google maps.

## Architecture

```
Driver phone (Android)
  GPS (1 Hz) ──────────────► Route Engine (backend)
  push-to-talk audio ─► Sarvam STT ─► Intent ─► Answer builder ─► Sarvam TTS ─► speaker
                                         ▲            ▲
                                         │            └─ facts from Route Engine
                                  templates first, AI model fallback
Route Engine ─► wrong-way alerts (templated TTS, no AI)
Everything ──► Fleet backend ─► dashboard, deviation log, reports
```

### Components

1. **Routing — `routing/`**
   - Self-hosted **Valhalla** on **OpenStreetMap** extracts (start with the Karnataka extract).
   - Valhalla gives the route, the manoeuvres, and per-edge attributes: `bridge`, `tunnel`, `layer`, `highway=service`, lane counts where they're tagged.
2. **Route Engine — `engine/`** (core intellectual property, pure Python, heavily tested):
   - **Map-matching:** snap noisy GPS to the road graph. Use Valhalla `trace_attributes` or an HMM-based matcher.
   - **Decision points:** for every upcoming fork, flyover ramp or junction on the route, precompute a fact card, e.g. `{type: "flyover_vs_service", on_route: "flyover", distance_m, landmark}`.
   - **Wrong-way detection:** the matched edge is not on the route, or the heading is more than 90° off for at least N seconds or M metres. Emit `{event: "off_route", recovery: "u-turn in 300 m"}`.
   - **Landmarks:** nearby OSM POIs (fuel pumps, temples, hospitals, big shops) to describe turns.
3. **Voice — `voice/`**
   - **Sarvam speech-to-text:** streaming WebSocket, used only during push-to-talk.
   - **Intent:** a small set of templated intents first (`which_branch`, `left_or_right`, `distance_to_next`, `am_i_wrong`, `repeat`, `eta`). For unknown questions, fall back to a Sarvam AI model with a strict prompt: "answer ONLY from these facts."
   - **Sarvam Bulbul text-to-speech**, in the driver's chosen language (Kannada, Hindi, Tamil, Telugu, English…).
   - **Prompts and templates** are versioned in `voice/templates/<lang>.yaml`.
4. **Backend — `backend/`**
   - FastAPI, PostgreSQL + PostGIS, Redis (live positions, pub/sub), Celery for reports.
   - Covers trips, stops, drivers, vehicles, the deviation log, and live location over WebSocket.
5. **Driver app — `app/`**
   - Android (Kotlin, or Flutter if decided).
   - Map view, push-to-talk button, offline buffer for GPS while the network drops, and on-device wake word (optional, later).
6. **Fleet dashboard — `dashboard/`**
   - Live map, trip timeline, deviation heatmap, kilometres and minutes lost per driver, CSV/PDF reports.

## Stack

Python 3.11, FastAPI, SQLAlchemy 2 (async), PostgreSQL 16 + PostGIS, Redis, Celery, Valhalla (Docker), Sarvam API, Android (Kotlin or Flutter), Docker Compose, pytest.

## Repo layout (target)

```
routing/      Valhalla config, OSM extract download script, tile build notes
engine/       map matching, decision points, wrong-way detection, landmarks
voice/        Sarvam clients (STT/TTS/LLM), intent router, templates/<lang>.yaml
backend/      FastAPI app, models, routers, services, migrations (Alembic)
dashboard/    web UI
app/          Android driver app
traces/       recorded GPS traces (.gpx / .jsonl) with expected events, for tests
tests/        unit + replay tests
docs/         decisions (ADRs), setup notes written as I learn each step
```

## Build phases

1. **Routing and engine on recorded data. No app, no voice.**
   - Record 5–10 real drives with a GPS logger app, including deliberate wrong turns and flyover/service-road forks.
   - Replay them through the engine. Done when every wrong turn is flagged within 2 s with no false alarms on clean drives, and every flyover fork gets a correct fact card.
2. **Voice loop.** Push-to-talk on a laptop mic, then Sarvam speech-to-text, intent, facts, and Bulbul text-to-speech, for the 6 templated intents in Kannada and Hindi. Measure latency.
3. **Android driver app.** GPS streaming, push-to-talk, playback, offline buffer.
4. **Fleet backend and dashboard.** Trips, deviation log, reports.
5. **Pilot hardening.** Consent flow, retention jobs, audit log, cost monitoring per driver per day.

## Commands (fill in as each step is learned — see Working rules)

```bash
# routing: see routing/README.md (download + clip OSM extract, build tiles, run Valhalla in Docker)
#          docker start valhalla   |   docker stop valhalla
# backend: docker compose up -d db redis ; alembic upgrade head ; uvicorn backend.main:app --reload
# tests:   pytest -q   (replay tests use traces/)
```

## Conventions

- **Secrets:** `.env` only. Never commit `SARVAM_API_KEY`, DB passwords or signing keys. Provide `.env.example`.
- **Units:** metres and seconds internally; convert only at the voice layer.
- **Time:** store UTC; show IST.
- **Code split:** the engine functions are pure and deterministic, with no network calls, so they can be replay-tested.
- **Every voice answer is logged** (intent, facts used, latency, cost) without storing raw audio, so I can debug accuracy and spending.
- **Cost guard:** track Sarvam spend per driver per day, and alert if it exceeds ₹5.
- **Keep it simple:** pick boring, well-documented tools. No new dependency without a one-line reason in `docs/decisions.md`.

## Open questions

- **Valhalla vs OSRM:** Valhalla gives richer edge attributes for flyover detection; OSRM is faster. Start with Valhalla.
- **Kotlin vs Flutter** for the driver app.
- **OSM coverage:** how complete are OSM flyover and landmark tags on the pilot city's routes? Audit before promising features.
- **First pilot segment:** delivery 3PL, cement or FMCG distribution, ambulances, or school buses.
