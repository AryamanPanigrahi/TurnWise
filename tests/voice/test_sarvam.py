import json

from tests.voice.fakes import FakeTransport, make_wav, tts_route
from voice.config import VoiceConfig
from voice.sarvam import SarvamClient, SarvamError

CFG = VoiceConfig(api_key="test-key", stt_inr_per_audio_hour=36.0, tts_inr_per_10k_chars=20.0)


def _raises(fn, exc=SarvamError):
    try:
        fn()
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


def test_requires_api_key():
    _raises(lambda: SarvamClient(VoiceConfig(api_key="")))


def test_stt_sends_language_and_key_and_computes_cost():
    t = FakeTransport({"/speech-to-text": (200, {"transcript": "ಎಷ್ಟು ದೂರ", "language_code": "kn-IN"})})
    r = SarvamClient(CFG, t).speech_to_text(make_wav(2.0), "kn")
    assert r.transcript == "ಎಷ್ಟು ದೂರ"
    assert abs(r.audio_s - 2.0) < 1e-6
    assert abs(r.cost_inr - 2.0 / 3600 * 36.0) < 1e-9
    call = t.calls[0]
    assert call["headers"]["api-subscription-key"] == "test-key"
    assert call["headers"]["Content-Type"].startswith("multipart/form-data")
    assert b"kn-IN" in call["body"] and b"saarika" in call["body"]


def test_tts_decodes_audio_and_costs_by_chars():
    wav = make_wav(0.3)
    t = FakeTransport({"/text-to-speech": tts_route(wav)})
    r = SarvamClient(CFG, t).text_to_speech("नमस्ते", "hi")
    assert r.wav == wav
    assert abs(r.cost_inr - len("नमस्ते") / 10_000 * 20.0) < 1e-9
    sent = json.loads(t.calls[0]["body"])
    assert sent["target_language_code"] == "hi-IN" and sent["text"] == "नमस्ते"


def test_chat_parses_openai_style_response():
    t = FakeTransport({"/v1/chat/completions": (200, {
        "choices": [{"message": {"content": "eta"}}], "usage": {"total_tokens": 42}})})
    r = SarvamClient(CFG, t).chat([{"role": "user", "content": "x"}])
    assert r.text == "eta" and r.tokens == 42
    assert json.loads(t.calls[0]["body"])["temperature"] == 0


def test_http_errors_and_bad_input():
    c = SarvamClient(CFG, FakeTransport({"/text-to-speech": (500, {"error": "boom"})}))
    _raises(lambda: c.text_to_speech("hi", "hi"))
    c = SarvamClient(CFG, FakeTransport({"/text-to-speech": (200, {"audios": []})}))
    _raises(lambda: c.text_to_speech("hi", "hi"))
    _raises(lambda: c.text_to_speech("hi", "xx"))


def test_timeout_propagates():
    c = SarvamClient(CFG, FakeTransport({}, raise_timeout_on=("/v1/chat/completions",)))
    _raises(lambda: c.chat([]), TimeoutError)


def test_config_from_env():
    cfg = VoiceConfig.from_env({"SARVAM_API_KEY": "k", "SARVAM_BASE_URL": "http://x/",
                                "COST_GUARD_INR_PER_DRIVER_DAY": "3.5", "SARVAM_TTS_SPEAKER": "meera"})
    assert cfg.api_key == "k" and cfg.base_url == "http://x"
    assert cfg.cost_guard_inr_per_driver_day == 3.5
    assert cfg.speaker_for("kn") == "meera"
