"""Replay every recorded and synthetic drive in traces/ through the engine.

A drive without a `.route.json` is skipped (visibly: run `pytest -rs`), not failed,
so Ram can add recordings before the planned route for them has been saved.
"""

from pathlib import Path

import pytest

from engine.harness import load_case, run_case

TRACES = Path(__file__).resolve().parents[2] / "traces"
FILES = sorted(TRACES.glob("*.jsonl"))


@pytest.mark.parametrize("jsonl", FILES, ids=lambda p: p.stem)
def test_replay(jsonl):
    try:
        case = load_case(jsonl)
    except FileNotFoundError as missing:
        pytest.skip(f"missing {missing}")
    result = run_case(case)
    assert result.passed, "\n".join(result.problems)


def test_there_are_traces_to_replay():
    assert any((TRACES / f"{p.stem}.route.json").exists() for p in FILES), \
        "no trace with a route file: run `python -m engine.make_fixtures`"
