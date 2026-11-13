import io
import sys
import tempfile
from pathlib import Path

from voice import demo
from voice.answer import render_answer
from voice.fake_engine import FakeEngine


def test_fake_engine_responses_render_in_every_intent():
    eng = FakeEngine()
    for intent in ("which_branch", "left_or_right", "distance_to_next", "am_i_wrong", "eta"):
        resp = eng("t", intent, {})
        r = render_answer("kn", resp["answer_key"], resp["facts"])
        assert not r.fell_back, (intent, resp, r.reason)


def test_fake_engine_does_not_guess_branch_when_next_is_a_turn():
    eng = FakeEngine(step_m=700)  # past the flyover; next decision is a left turn
    assert eng("t", "which_branch", {})["answer_key"] == "not_sure"


def test_offline_demo_runs_scripted_session():
    with tempfile.TemporaryDirectory() as tmp:
        old_log, old_stdin, old_stdout = demo.LOG_PATH, sys.stdin, sys.stdout
        log_path = demo.LOG_PATH = Path(tmp) / "answers.jsonl"
        sys.stdin = io.StringIO("flyover or service road?\nhow long?\n")
        sys.stdout = out = io.StringIO()
        try:
            demo.main(["--lang", "en", "--offline"])
        finally:
            demo.LOG_PATH, sys.stdin, sys.stdout = old_log, old_stdin, old_stdout
        text = out.getvalue()
        assert "Take the flyover near Indian Oil petrol bunk" in text
        assert "minutes" in text
        assert len(log_path.read_text(encoding="utf-8").splitlines()) == 2
