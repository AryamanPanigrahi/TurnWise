# app/ — the Android driver app

Kotlin (see `docs/decisions.md` 0008). Two Gradle modules:

| Module | What | Status |
|---|---|---|
| `core/` | Pure Kotlin, no Android imports: GPS batching and offline buffer, the `/v1/gps` uploader, the trip events client, the push-to-talk / speaker state machine. | Done, 16 JVM tests |
| `android/` | Activities, location service, mic, audio playback. Thin: it feeds `core` and does what `core` tells it to. | Create it yourself in Android Studio: [docs/setup/android-app.md](../docs/setup/android-app.md) |

Keeping the logic in `core` means it is tested in seconds on a laptop, without
an emulator, the same way the engine is replay-tested.

```bash
cd app
./gradlew :core:test
```

## What `core` decides

- **GPS only while allowed** (`TrackingGate`): consent recorded, on duty, and
  the fix belongs to the active trip (DPDP, CLAUDE.md rule 5).
- **Offline buffer** (`GpsBuffer`): keeps fixes oldest-first, at most 600 per
  upload (contract limit), forgets them only after the server accepts them,
  and drops the oldest past 8 hours so storage can't fill up.
- **Uploads** (`GpsUploader`): `202` → done; `422` → drop that batch; `401`,
  `403`, `409` → stop and fix login or trip state; network error or `5xx` →
  retry after 2 s, 4 s, 8 s… up to 5 min.
- **Trip events** (`TripEvent`, `EventSequencer`): parses the WebSocket
  envelopes in `docs/contracts/events.md`, ignores unknown fields and event
  types, and acts on each `seq` once, even after a reconnect replays events.
- **Push-to-talk** (`PushToTalk`): the mic is on only between press and release
  (rule 4), taps under 0.3 s are discarded, clips stop at 25 s (Sarvam's REST
  speech-to-text accepts at most 30 s), and a wrong-way alert interrupts
  everything (rule 2).
