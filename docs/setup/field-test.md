# Field test with a phone (before the Android app exists)

The field kit is a web page served by the backend. Opened in a phone browser it does what the
driver app will do: stream GPS, show and speak alerts, and ask the five questions. It uses the
real contract endpoints, so it tests the real engine. Each test is also recorded for replay.

## What you need

- The laptop, with Docker running, and the phone. Both inside the Bengaluru map area
  (routing/README.md: lon 77.35 to 77.90, lat 12.75 to 13.25). Routes outside it fail.
- `.env` with `TURNWISE_API_TOKEN` (see `.env.example`).

## Start (PowerShell, repo root)

```powershell
docker start valhalla
```
```powershell
.venv\Scripts\python.exe -m backend.fieldserver
```

It prints an `https://<laptop-ip>:8443/field` address and the token. On the phone:

1. Connect the laptop to the **phone's hotspot** (for a drive) or put both on the same Wi-Fi (at a desk).
2. Open the address. Accept the certificate warning (Advanced, Proceed): the certificate is
   self-signed, made on your laptop. Browsers only give GPS to https pages, hence the certificate.
3. Windows may ask to allow Python through the firewall: allow on Private networks.
4. Paste the token, allow location, tap a destination on the map, press **Start trip**.
5. Keep the page in front and the screen on (the page asks the phone to stay awake).
6. Press **End trip** when done.

At a desk you can tick **Simulate the drive**: first tap is the start, second the destination.
"Take a wrong turn" pushes the simulated car off the route.

## Walking or driving?

| | Walking | Two-wheeler / car |
|---|---|---|
| App plumbing: GPS upload, events, questions, speech | yes | yes |
| Wrong-turn alert by distance | yes, but slow: you must be about 20 to 40 m down the wrong street (20 to 30 s on foot) | yes, this is the real test of the 2 s rule |
| Wrong-direction alert (heading rule) | **no**: it needs 2 m/s (7 km/h); walking is about 1.4 m/s | yes |
| Flyover / underpass questions | **no**: you cannot walk onto a flyover | yes |
| ETA | meaningless (uses your walking speed) | yes |
| GPS behaviour at speed, under flyovers, between tall buildings | no | yes |
| Hearing alerts over engine and traffic noise | no | yes |

So: **walk first** (15 minutes, near home) to prove the phone, page, GPS and alerts work end to
end. Then **drive** for the tests that count. Routes are planned for cars, so on foot follow the
blue line even where it avoids a one-way street. A passenger handles the phone; never the driver.

## Suggested drive plan (matches traces/README.md)

1. Clean drive, 3 to 5 km: expect announcements at about 400 m and 100 m before turns, no alerts.
2. Same route, one deliberate wrong turn, then U-turn back: expect "Wrong way" within a couple of
   seconds of clearly being on the other road, then "back on route".
3. A route over a flyover with a road below (Electronic City, Silk Board, Hebbal): ask
   "Flyover or service road?" about 300 m before; check the answer and the announcement.
4. Passenger notes the clock time of every wrong turn and every wrong or late announcement.

## After the test

Recordings are in `traces/local/` (git-ignored): `<trip>.jsonl` (GPS), `<trip>.route.json` (the
planned route), `<trip>.events.jsonl` (what the engine said). To make one a permanent test: copy
the three files into `traces/` under a proper name, write `<name>.expected.json` from the notes,
trim the first and last 200 m so home and office are not in git, and run
`python -m engine.harness`. Only record people who agreed to it.
