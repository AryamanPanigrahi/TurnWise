import { test } from "node:test";
import assert from "node:assert/strict";
import {
  formatIst, haversineM, nearestIndex, parseTrace, placeEvents, segmentsBySpeed, speedBand, stats,
} from "./trace.js";

const line = (s, lat, speed = 11) =>
  JSON.stringify({ trip_id: "t", ts: `2026-11-07T04:30:${String(s).padStart(2, "0")}.000Z`,
                   lat, lon: 77.6, speed, heading: 0, accuracy: 5 });

const trace = [0, 1, 2, 10, 11].map((s, i) => line(s, 12.97 + i * 1e-4, i < 2 ? 1 : 15)).join("\n");

test("haversine", () => {
  const d = haversineM(12.97, 77.6, 12.971, 77.6);
  assert.ok(d > 110 && d < 112);
});

test("parse sorts and reports bad lines", () => {
  const { points, errors } = parseTrace([line(2, 1), "oops", line(1, 2), "", '{"lat":1}'].join("\n"));
  assert.deepEqual(points.map((p) => p.lat), [2, 1]);
  assert.equal(errors.length, 2);
  assert.match(errors[0], /^line 2/);
});

test("stats find distance, duration and gaps", () => {
  const s = stats(parseTrace(trace).points);
  assert.equal(s.points, 5);
  assert.equal(s.durationS, 11);
  assert.ok(s.distanceM > 40 && s.distanceM < 50);
  assert.deepEqual(s.gaps, [{ index: 3, seconds: 8 }]);
  assert.equal(s.maxSpeedMps, 15);
});

test("nearestIndex and placeEvents", () => {
  const { points } = parseTrace(trace);
  assert.equal(nearestIndex(points, Date.parse("2026-11-07T04:30:07Z")), 3);
  assert.equal(nearestIndex(points, Date.parse("2026-11-07T04:29:00Z")), 0);
  assert.equal(nearestIndex([], 0), -1);
  const evs = placeEvents(points, { events: [{ event: "off_route", ts: "2026-11-07T04:30:01.4Z" }, { event: "x" }] });
  assert.equal(evs[0].index, 1);
  assert.equal(evs[1].index, -1);
  assert.deepEqual(placeEvents(points, null), []);
});

test("speed bands and segments", () => {
  assert.equal(speedBand(null), "unknown");
  assert.equal(speedBand(2), "crawl");
  assert.equal(speedBand(20), "fast");
  const segs = segmentsBySpeed(parseTrace(trace).points);
  assert.deepEqual(segs.map((s) => s.band), ["crawl", "fast"]);
  assert.equal(segs[1].coords.length, 4);
});

test("IST formatting", () => {
  assert.equal(formatIst(Date.parse("2026-11-07T04:30:00Z")), "10:00:00 IST");
});
