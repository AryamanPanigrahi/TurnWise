import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from voice.answer_log import AnswerRecord, JsonlAnswerLog
from voice.cost_guard import CostGuard, ist_day
from voice.tts_cache import TtsCache


def _cache(tmp, calls):
    def synth(text, lang):
        calls.append((text, lang))
        return f"WAV:{text}".encode(), 0.01
    return TtsCache(synth, "bulbul", lambda lang: "spk", 22050, Path(tmp))


def test_tts_cache_hits_after_first_call():
    with tempfile.TemporaryDirectory() as tmp:
        calls = []
        c = _cache(tmp, calls)
        first = c.get("ನಮಸ್ಕಾರ", "kn")
        second = c.get("ನಮಸ್ಕಾರ", "kn")
        assert not first.hit and first.cost_inr == 0.01
        assert second.hit and second.cost_inr == 0 and second.wav == first.wav
        assert len(calls) == 1
        c.get("ನಮಸ್ಕಾರ", "hi")  # different language -> different key
        assert len(calls) == 2


def test_tts_cache_warm_counts_new():
    with tempfile.TemporaryDirectory() as tmp:
        c = _cache(tmp, [])
        assert c.warm(["a", "b"], "en") == 2
        assert c.warm(["a", "b", "c"], "en") == 1


def test_ist_day_boundary():
    # 18:29 UTC = 23:59 IST same day; 18:31 UTC = 00:01 IST next day.
    assert str(ist_day(datetime(2026, 11, 5, 18, 29, tzinfo=timezone.utc))) == "2026-11-05"
    assert str(ist_day(datetime(2026, 11, 5, 18, 31, tzinfo=timezone.utc))) == "2026-11-06"


def test_cost_guard_alerts_once_per_driver_day():
    alerts = []
    g = CostGuard(5.0, lambda d, day, spent, cap: alerts.append((d, str(day), round(spent, 2))))
    t = datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc)
    g.add("drv1", 3.0, t)
    assert not alerts
    g.add("drv1", 2.5, t)
    g.add("drv1", 1.0, t)
    assert alerts == [("drv1", "2026-11-05", 5.5)]
    assert g.over_cap("drv1", t) and not g.over_cap("drv2", t)
    g.add("drv1", 6.0, datetime(2026, 11, 6, 6, 0, tzinfo=timezone.utc))  # new IST day
    assert len(alerts) == 2


def test_naive_timestamp_rejected():
    try:
        CostGuard(5).add("d", 1, datetime(2026, 1, 1))
    except ValueError:
        return
    raise AssertionError


def test_jsonl_log_keeps_unicode_and_no_audio():
    with tempfile.TemporaryDirectory() as tmp:
        log = JsonlAnswerLog(Path(tmp) / "answers.jsonl")
        rec = AnswerRecord(ts="2026-11-05T04:00:00Z", trip_id="t", driver_id="d", lang="kn",
                           transcript="ಎಷ್ಟು ದೂರ", intent="distance_to_next", intent_source="rules",
                           matched="ಎಷ್ಟು ದೂರ", answer_key="distance_to_next", facts={"distance_m": 300},
                           template_key="distance_to_next", fell_back=False, fallback_reason=None,
                           tts_cache_hit=True)
        log.write(rec)
        log.write(rec)
        lines = (Path(tmp) / "answers.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        obj = json.loads(lines[0])
        assert obj["transcript"] == "ಎಷ್ಟು ದೂರ"
        assert not any("audio" in k or "wav" in k for k in obj)
