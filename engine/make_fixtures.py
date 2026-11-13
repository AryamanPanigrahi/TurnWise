"""Write the synthetic fixture drives into traces/.

    python -m engine.make_fixtures

Deterministic (fixed seeds), so re-running changes nothing unless the generator
changes. Real recorded drives are never touched: only `synthetic_*` is written.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from engine.harness import write_route
from engine.synthetic import DEFAULT_START, Drive, drive, expected_events, path_from_legs, write_trace

START = (12.9756, 77.6066)  # MG Road, Bengaluru
SPEED = 10.0                # m/s, so 100 m = 10 s

STRAIGHT = path_from_legs(START, [(90, 2000)])
CURVY = path_from_legs(START, [(90, 400), (30, 400), (90, 400), (150, 400), (90, 400)])


def _ts(seconds: float) -> str:
    return (DEFAULT_START + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def build(out: Path) -> list[str]:
    names = []

    def emit(name, route, taken, seed, notes, expected=None):
        d: Drive = drive(taken, trip_id=name, speed_mps=SPEED, noise_m=4.0, seed=seed)
        exp = expected or expected_events(d, route, name=name, notes=notes)
        exp.setdefault("trace", f"{name}.jsonl")
        exp["notes"] = notes
        write_trace(out, name, d, exp)
        write_route(out / f"{name}.jsonl", route, source="synthetic")
        names.append(name)

    emit("synthetic_clean_straight_01", STRAIGHT, STRAIGHT, 1,
         "2 km due east, noisy GPS, no wrong turn.")
    emit("synthetic_clean_curvy_01", CURVY, CURVY, 2,
         "S-bends with 60 degree turns; heading changes a lot but the car stays on the route.")

    emit("synthetic_wrong_turn_right_01", STRAIGHT,
         path_from_legs(START, [(90, 1000), (180, 1000)]), 3,
         "Turned right (south) at 1 km instead of going straight.")
    emit("synthetic_wrong_turn_left_01", STRAIGHT,
         path_from_legs(START, [(90, 1000), (0, 1000)]), 4,
         "Turned left (north) at 1 km instead of going straight.")
    emit("synthetic_fork_01", STRAIGHT,
         path_from_legs(START, [(90, 1000), (135, 1000)]), 5,
         "Took the right branch of a shallow fork at 1 km.")

    # Reversing along the same road: distance stays ~0, so only the heading rule can catch it.
    reverse = path_from_legs(START, [(90, 500), (270, 500)])
    emit("synthetic_reverse_01", STRAIGHT, reverse, 6,
         "Drove east 500 m then back west along the same road; heading rule only.",
         expected={"clean": False, "events": [
             {"event": "off_route", "ts": _ts(50), "early_s": 0, "late_s": 7.5,
              "note": "reversed at 50 s; heading must stay wrong for 5 s"}]})

    uturn = path_from_legs(START, [(90, 1000), (180, 300), (0, 300), (90, 600)])
    d = drive(uturn, trip_id="x", speed_mps=SPEED, noise_m=4.0, seed=7)
    off_ts = expected_events(d, STRAIGHT, name="x")["events"][0]["ts"]
    emit("synthetic_uturn_recover_01", STRAIGHT, uturn, 7,
         "Wrong turn south for 300 m, U-turn, back to the road at 160 s, carried on east.",
         expected={"clean": False, "events": [
             {"event": "off_route", "ts": off_ts, "note": "more than 40 m from the route"},
             {"event": "back_on_route", "ts": _ts(160), "note": "back at the junction"}]})
    return names


if __name__ == "__main__":
    for n in build(Path("traces")):
        print("wrote", n)
