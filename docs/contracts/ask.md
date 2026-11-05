# POST /v1/ask  (DRAFT)

Request:  `{ "trip_id": "string", "intent": "which_branch", "slots": { } }`
Response: `{ "answer_key": "string", "facts": { } }`

Intents: which_branch, left_or_right, distance_to_next, am_i_wrong, repeat, eta.
If a fact is unavailable, `answer_key` is `not_sure` — never a guess.
