# traces/ — recorded test drives

Week 1 goal: **5–10 real drives**, including deliberate wrong turns and
flyover/service-road forks. The route engine's replay tests (Aryaman, `engine/`)
read these files, so their format matters more than the drives being perfect.

## What a trace is

Two files per drive, same name:

- `<name>.jsonl` — one GPS fix per line, exactly the fields of a
  `POST /v1/gps` point ([docs/contracts/gps.md](../docs/contracts/gps.md)):
  ```json
  {"trip_id": "trace_2026-11-07_mgroad-ecity_01", "ts": "2026-11-07T04:30:05.000Z", "lat": 12.97615, "lon": 77.6061, "speed": 11.1, "heading": 0.0, "accuracy": 4.0}
  ```
  Using the same shape as the app means replay tests feed the engine what it
  will really get.
- `<name>.expected.json` — what the engine *should* say on this drive. You
  write this by hand after the drive:
  ```json
  {
    "trace": "2026-11-07_mgroad-ecity_01.jsonl",
    "clean": false,
    "notes": "Missed the left after Silk Board on purpose, U-turned at the petrol pump.",
    "events": [
      {"event": "off_route", "ts": "2026-11-07T04:41:12Z", "note": "missed left after Silk Board"},
      {"event": "back_on_route", "ts": "2026-11-07T04:44:30Z"},
      {"event": "decision_point_ahead", "ts": "2026-11-07T04:50:02Z",
       "fact": {"type": "flyover_vs_service", "on_route": "flyover"}}
    ]
  }
  ```
  - `clean: true` means no wrong turns: the engine must raise **zero**
    `off_route` events (the "no false alarms" test).
  - For `off_route`, `ts` is the moment the wrong turn became certain (you
    were clearly on the other road). The engine passes if it alerts within
    2 s of it (CLAUDE.md product rule 2).
  - `event` is one of `off_route`, `back_on_route`, `decision_point_ahead`,
    `arrived` (same names as [events.md](../docs/contracts/events.md)).
  - This file is a **proposal**: Aryaman owns the replay tests and may want
    more fields (e.g. tolerance per event). Agree before recording many drives.

Name drives `YYYY-MM-DD_<from>-<to>_<nn>`, all lowercase, e.g.
`2026-11-07_mgroad-ecity_01`.

## Recording

1. On an Android phone, install **GPSLogger** (open source, by mendhak, on
   F-Droid and the Play Store). Settings:
   - Logging details → log to GPX (CSV also works).
   - Performance → log every **1 second**, distance filter **0**, accuracy
     filter off (we want the noisy points too; the engine must cope with them).
2. Mount the phone on the dashboard, where the app will be. Start logging
   *before* you set off and stop *after* you arrive.
3. While driving (passenger takes notes, never the driver): write down the
   clock time of every deliberate wrong turn, every flyover/service-road
   fork, and where you got back on route.
4. Mix it up: at least 2 clean drives, at least 3 with a deliberate wrong
   turn, and at least 2 through a flyover with a parallel service road.

## Converting

From the repo root, with the virtual environment active (see
[docs/setup/voice-demo.md](../docs/setup/voice-demo.md) steps 1–2):

```bash
python -m tools.gpx_to_trace ~/Downloads/20261107.gpx traces/2026-11-07_mgroad-ecity_01.jsonl
```

This sorts the points, drops duplicates, fills in speed/heading where the
logger left them out (heading is null when stationary, as the contract says),
checks the result, and creates an empty `.expected.json` for you to fill in.
Add `--clean` for a drive without wrong turns.

Then check everything in this folder:

```bash
python -m tools.trace_check
```

It fails on contract errors or a missing/invalid `.expected.json`, and warns
about gaps longer than 5 s, GPS jumps, and recordings slower than 1 Hz.

## Privacy (DPDP)

Even founders' drives are location data.

- **Trim the ends.** `gpx_to_trace` drops points within **200 m** of the start
  and end by default (`--trim-start-m`, `--trim-end-m`), so home and office
  locations don't land in git. Start and finish away from home if you can.
- Only record drives by people who agreed to it. No drives of real fleet
  drivers go in this folder.
- Keep the raw `.gpx` files out of the repo; only the trimmed `.jsonl` goes in.

## Replay files and tolerances (added by Aryaman, engine side)

The engine's replay tests (`python -m engine.harness`, or `pytest tests/engine`)
need one more file per drive, plus optional tolerances in `.expected.json`.

- `<name>.route.json` — the route the driver was *supposed* to follow:
  `{"source": "valhalla", "route": [[lat, lon], ...]}`. Save it once from
  Valhalla's `/route` polyline when you record, so tests never call Valhalla.
  A drive without this file is skipped (listed as `SKIP`), not failed.
- Optional per-event `"early_s"` / `"late_s"` in `.expected.json` events: how
  many seconds before / after `ts` the engine's event may come. Defaults for
  `off_route` are 5 s early and 2 s late (the product rule); `back_on_route` is
  10 s either way.
- `decision_point_ahead` and `arrived` are accepted but skipped until the engine
  can produce them.
- `synthetic_*` drives are generated by `python -m engine.make_fixtures`; don't
  edit them by hand.
