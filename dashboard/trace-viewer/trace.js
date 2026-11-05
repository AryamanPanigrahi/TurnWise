// Pure functions for the trace viewer: no DOM, no network, so they run under
// `node --test` as well as in the browser.

const EARTH_R_M = 6371008.8;
export const MAX_GAP_S = 5;

export function haversineM(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const p1 = lat1 * r, p2 = lat2 * r, dp = (lat2 - lat1) * r, dl = (lon2 - lon1) * r;
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_R_M * Math.asin(Math.sqrt(a));
}

/** Parse a traces/*.jsonl file into points sorted by time. Bad lines are reported, not thrown. */
export function parseTrace(text) {
  const points = [];
  const errors = [];
  text.split(/\r?\n/).forEach((line, i) => {
    if (!line.trim()) return;
    try {
      const p = JSON.parse(line);
      const t = Date.parse(p.ts);
      if (typeof p.lat !== "number" || typeof p.lon !== "number" || Number.isNaN(t)) {
        throw new Error("needs lat, lon and ts");
      }
      points.push({ ...p, t });
    } catch (e) {
      errors.push(`line ${i + 1}: ${e.message}`);
    }
  });
  points.sort((a, b) => a.t - b.t);
  return { points, errors };
}

/** Distance, duration, top speed and gaps longer than MAX_GAP_S. */
export function stats(points) {
  let distanceM = 0, maxSpeed = 0;
  const gaps = [];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    distanceM += haversineM(a.lat, a.lon, b.lat, b.lon);
    const dt = (b.t - a.t) / 1000;
    if (dt > MAX_GAP_S) gaps.push({ index: i, seconds: dt });
  }
  for (const p of points) if (p.speed != null && p.speed > maxSpeed) maxSpeed = p.speed;
  const durationS = points.length ? (points[points.length - 1].t - points[0].t) / 1000 : 0;
  return { points: points.length, distanceM, durationS, maxSpeedMps: maxSpeed, gaps };
}

/** Index of the point closest in time to `t` (ms). Points must be sorted. */
export function nearestIndex(points, t) {
  let lo = 0, hi = points.length - 1;
  if (hi < 0) return -1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (points[mid].t < t) lo = mid + 1; else hi = mid;
  }
  if (lo > 0 && Math.abs(points[lo - 1].t - t) <= Math.abs(points[lo].t - t)) return lo - 1;
  return lo;
}

/** Attach each expected event to the nearest trace point. */
export function placeEvents(points, expected) {
  const events = (expected && Array.isArray(expected.events)) ? expected.events : [];
  return events.map((ev) => {
    const t = Date.parse(ev.ts);
    const i = Number.isNaN(t) ? -1 : nearestIndex(points, t);
    return { ...ev, t, index: i, point: i >= 0 ? points[i] : null };
  });
}

/** Speed (m/s) to a colour band. Null speed is grey. */
export function speedBand(speed) {
  if (speed == null) return "unknown";
  const kmh = speed * 3.6;
  if (kmh < 10) return "crawl";
  if (kmh < 30) return "slow";
  if (kmh < 50) return "medium";
  return "fast";
}

/** Split the track into runs of the same speed band, for drawing coloured polylines. */
export function segmentsBySpeed(points) {
  const segs = [];
  for (let i = 1; i < points.length; i++) {
    const band = speedBand(points[i].speed);
    const last = segs[segs.length - 1];
    if (last && last.band === band) last.coords.push([points[i].lat, points[i].lon]);
    else segs.push({ band, coords: [[points[i - 1].lat, points[i - 1].lon], [points[i].lat, points[i].lon]] });
  }
  return segs;
}

/** Shown in IST, stored in UTC (CLAUDE.md conventions). */
export function formatIst(t) {
  const d = new Date(t + 5.5 * 3600 * 1000);
  return d.toISOString().slice(11, 19) + " IST";
}
