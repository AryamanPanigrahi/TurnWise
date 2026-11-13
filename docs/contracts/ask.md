# `POST /v1/ask` — facts for a driver question (DRAFT)

The voice layer has already turned speech into an `intent` + `slots`. The
backend asks the route engine and returns **facts only** — no wording. The voice
layer renders `answer_key` + `facts` via `voice/templates/<lang>.yaml`.

## Request
```json
{
  "trip_id": "trp_...",
  "intent": "which_branch",
  "slots": { "options": ["flyover", "service_road"] }
}
```

`intent` ∈ `which_branch`, `left_or_right`, `distance_to_next`, `am_i_wrong`,
`repeat`, `eta`, `unknown`.

## Response
```json
{
  "answer_key": "which_branch.flyover",
  "facts": {
    "on_route": "flyover",
    "distance_m": 350,
    "landmark": "Indian Oil petrol bunk",
    "confidence": 0.9
  }
}
```

### Answer keys and their facts

| answer_key | facts |
|---|---|
| `which_branch.<branch>` | `on_route`, `distance_m`, `landmark?` |
| `left_or_right.<left\|right\|straight>` | `distance_m`, `landmark?` |
| `distance_to_next` | `distance_m`, `maneuver` |
| `am_i_wrong.on_route` | — |
| `am_i_wrong.off_route` | `recovery_action`, `distance_m` |
| `eta` | `eta_s`, `remaining_m` |
| `not_sure` | — (engine lacks the fact; voice says "I'm not sure, follow the screen") |

Rule (CLAUDE.md #1): if the engine can't determine a fact, it returns
`not_sure`. It never guesses, and the voice layer never fills gaps.

`branch` values: `flyover`, `service_road`, `underpass`, `left_fork`, `right_fork`.
`maneuver` values: `turn_left`, `turn_right`, `keep_left`, `keep_right`,
`u_turn`, `roundabout`, `arrive`.
