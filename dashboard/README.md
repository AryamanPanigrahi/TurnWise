# dashboard/ — fleet dashboard

The full dashboard (live map, trip timeline, deviation heatmap, reports) is
Weeks 7–8 and needs the backend. Until then this folder has one tool that is
useful now:

## Trace viewer

Look at a recorded drive on a map before committing it: the track coloured by
speed, gaps in the fixes, and the events you wrote in `.expected.json`. Drag
the slider to scrub through the drive (times shown in IST).

**Why a local web server:** the page loads `trace.js` as a JavaScript module,
which browsers refuse to do from a `file://` page. OpenStreetMap's tile
servers also require pages to identify themselves, which `file://` pages can't.
`python -m http.server` serves the folder on your laptop only.

```bash
python -m http.server 8000 --directory dashboard/trace-viewer
```

Open http://localhost:8000 and drop a `traces/*.jsonl` file (and its
`.expected.json`) onto the page. The files are read in the browser and never
uploaded; only map tiles are fetched from OpenStreetMap.

Tests for the trace maths (Node 18+, no packages to install):

```bash
cd dashboard && npm test
```

Map data © OpenStreetMap contributors (ODbL). Leaflet is loaded from unpkg,
so there's no build step.
