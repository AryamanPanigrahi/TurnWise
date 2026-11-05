# POST /v1/gps  (DRAFT — change only with Ram's agreement)

Request: a batch of points.

```json
{ "points": [
  { "trip_id": "string", "ts": "ISO-8601 UTC", "lat": 12.9716, "lon": 77.5946,
    "speed": 8.3, "heading": 270, "accuracy": 5.0 }
] }
```
Units: speed m/s, heading degrees (0 = north), accuracy metres.
