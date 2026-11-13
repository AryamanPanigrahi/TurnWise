from datetime import datetime, timezone

from tests.voice.fakes import FakeClock
from voice.answer_log import MemoryAnswerLog
from voice.config import VoiceConfig
from voice.cost_guard import CostGuard
from voice.pipeline import VoicePipeline
from voice.templates import load

NOW = datetime(2026, 11, 5, 4, 30, tzinfo=timezone.utc)


class FakeSpeech:
    def __init__(self, clock, delay=0.2, fail=False):
        self.clock, self.delay, self.fail, self.seen = clock, delay, fail, set()

    def get(self, text, lang):
        if self.fail:
            raise RuntimeError("tts down")
        hit = (text, lang) in self.seen
        self.seen.add((text, lang))
        if not hit:
            self.clock.advance(self.delay)
        return type("S", (), {"wav": b"WAV", "hit": hit, "cost_inr": 0 if hit else 0.01})()


def build(clock=None, facts=None, llm=None, stt=None, guard=None, speech=None):
    clock = clock or FakeClock()
    log = MemoryAnswerLog()
    calls = []

    def default_facts(trip, intent, slots):
        calls.append((intent, dict(slots)))
        table = {
            "which_branch": {"answer_key": "which_branch.flyover",
                             "facts": {"on_route": "flyover", "distance_m": 300 - 50 * len(calls)}},
            "eta": {"answer_key": "eta", "facts": {"eta_s": 600, "remaining_m": 4000}},
        }
        return table.get(intent, {"answer_key": "not_sure", "facts": {}})

    p = VoicePipeline(cfg=VoiceConfig(api_key="k"), stt=stt, speech=speech or FakeSpeech(clock),
                      facts=facts or default_facts, llm_chat=llm, cost_guard=guard, log=log,
                      clock=clock, now=lambda: NOW)
    return p, log, calls, clock


def test_templated_path_kannada_with_latency_and_cache():
    p, log, calls, _ = build()
    r = p.handle_text("ಫ್ಲೈಓವರ್ ಅಥವಾ ಸರ್ವಿಸ್ ರೋಡ್?", trip_id="t1", driver_id="d1", lang="kn")
    assert r.text == "250 ಮೀಟರ್ ಮುಂದೆ ಫ್ಲೈಓವರ್ ತಗೊಳ್ಳಿ." and r.wav == b"WAV"
    rec = log.records[0]
    assert rec.intent == "which_branch" and rec.intent_source == "rules"
    assert calls[0] == ("which_branch", {"options": ["flyover", "service_road"]})
    assert rec.latency_ms["tts"] == 200.0 and rec.latency_ms["total"] == 200.0
    assert rec.tts_cache_hit is False and rec.cost_inr == {"tts": 0.01, "total": 0.01}
    assert rec.ts == "2026-11-05T04:30:00.000Z" and not rec.over_budget


def test_audio_path_uses_stt_and_costs():
    clock = FakeClock()

    def stt(wav, lang):
        clock.advance(0.5)
        return "कितना समय लगेगा", 0.004

    p, log, _, _ = build(clock=clock, stt=stt)
    r = p.handle_audio(b"RIFF", trip_id="t", driver_id="d", lang="hi")
    assert r.text == "अभी 4 किलोमीटर बाकी है, लगभग 10 मिनट।"
    rec = log.records[0]
    assert rec.latency_ms["stt"] == 500.0 and rec.cost_inr["stt"] == 0.004
    assert abs(rec.cost_inr["total"] - 0.014) < 1e-9


def test_unknown_goes_to_llm_label():
    p, log, calls, _ = build(llm=lambda msgs, timeout: ("eta", 0.001))
    r = p.handle_text("are we nearly there", trip_id="t", driver_id="d", lang="en")
    assert r.text == "4 kilometres left, about 10 minutes."
    assert log.records[0].intent_source == "llm" and calls[0][0] == "eta"


def test_llm_unknown_or_missing_gives_please_repeat_without_calling_engine():
    for llm in (lambda m, t: ("unknown", 0.001), None):
        p, log, calls, _ = build(llm=llm)
        r = p.handle_text("what's for lunch", trip_id="t", driver_id="d", lang="en")
        assert r.text == load("en").answers["please_repeat"] and not calls


def test_engine_failure_says_not_sure():
    def broken(*a):
        raise ConnectionError("backend down")
    p, log, _, _ = build(facts=broken)
    r = p.handle_text("how long", trip_id="t", driver_id="d", lang="en")
    assert r.text == "I'm not sure, follow the screen."
    assert "backend down" in log.records[0].error


def test_repeat_reasks_last_intent_with_fresh_facts():
    p, log, calls, _ = build()
    first = p.handle_text("flyover?", trip_id="t", driver_id="d", lang="en")
    again = p.handle_text("repeat", trip_id="t", driver_id="d", lang="en")
    assert "250 metres" in first.text and "200 metres" in again.text
    assert [c[0] for c in calls] == ["which_branch", "which_branch"]
    assert log.records[1].intent == "repeat"
    # Repeat on another trip with no history:
    other = p.handle_text("repeat", trip_id="t2", driver_id="d", lang="en")
    assert other.text == "Please say that again."


def test_llm_skipped_when_driver_over_cost_cap():
    guard = CostGuard(5.0)
    guard.add("d", 6.0, NOW)
    seen = []
    p, log, _, _ = build(llm=lambda m, t: seen.append(1) or ("eta", 0.0), guard=guard)
    r = p.handle_text("are we nearly there", trip_id="t", driver_id="d", lang="en")
    assert not seen and r.text == "Please say that again."
    assert "cost cap" in log.records[0].error


def test_spend_is_charged_to_cost_guard():
    guard = CostGuard(5.0)
    p, _, _, _ = build(guard=guard)
    p.handle_text("how long", trip_id="t", driver_id="d", lang="en")
    assert abs(guard.spent("d", NOW) - 0.01) < 1e-9


def test_over_budget_flag_and_stt_or_tts_failure():
    clock = FakeClock()
    p, log, _, _ = build(clock=clock, speech=FakeSpeech(clock, delay=2.0))
    p.handle_text("how long", trip_id="t", driver_id="d", lang="en")
    assert log.records[0].over_budget

    def bad_stt(wav, lang):
        raise TimeoutError("stt slow")
    p, log, _, _ = build(stt=bad_stt)
    r = p.handle_audio(b"x", trip_id="t", driver_id="d", lang="en")
    assert r.text == "Please say that again." and "stt slow" in log.records[0].error

    p, log, _, _ = build(speech=FakeSpeech(FakeClock(), fail=True))
    r = p.handle_text("how long", trip_id="t", driver_id="d", lang="en")
    assert r.wav is None and r.text.startswith("4 kilometres") and "tts down" in log.records[0].error


def test_alert_is_templated_and_spoken():
    p, _, _, _ = build(llm=lambda m, t: (_ for _ in ()).throw(AssertionError("LLM must not be used")))
    rendered, wav = p.speak_alert("off_route", {"recovery": {"action": "u_turn", "distance_m": 300}},
                                  driver_id="d", lang="hi")
    assert rendered.text == "गलत रास्ता! 300 मीटर बाद यू-टर्न लीजिए।" and wav == b"WAV"
