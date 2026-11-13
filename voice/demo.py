"""Laptop voice-loop demo (build phase 2).

Offline, no API key — type questions, read answers:
    python -m voice.demo --lang kn --offline

With Sarvam (needs SARVAM_API_KEY in .env):
    python -m voice.demo --lang hi                    # type questions, hear answers
    python -m voice.demo --lang kn --wav question.wav # transcribe a recorded clip
    python -m voice.demo --lang kn --mic              # push-to-talk (needs sounddevice)

Answers are saved to voice/out/answer.wav; every answer is logged to
voice/logs/answers.jsonl (no audio stored).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import wave
from pathlib import Path

from voice.answer_log import JsonlAnswerLog
from voice.config import VoiceConfig
from voice.cost_guard import CostGuard
from voice.fake_engine import FakeEngine
from voice.pipeline import VoicePipeline
from voice.templates import available_languages

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).parent / "out"
LOG_PATH = Path(__file__).parent / "logs" / "answers.jsonl"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader (KEY=VALUE lines) so we don't need python-dotenv."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def record_push_to_talk(rate: int = 16000) -> bytes:
    """Record while the user holds the floor: Enter to start, Enter to stop."""
    try:
        import sounddevice as sd  # optional; see docs/setup/voice-demo.md
    except ImportError:
        sys.exit("--mic needs the 'sounddevice' package (see docs/setup/voice-demo.md)")
    import queue

    q: "queue.Queue[bytes]" = queue.Queue()
    input("Press Enter and speak; press Enter again to stop... ")
    with sd.RawInputStream(samplerate=rate, channels=1, dtype="int16",
                           callback=lambda data, frames, t, status: q.put(bytes(data))):
        input("Recording... press Enter to stop. ")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        while not q.empty():
            w.writeframes(q.get())
    return buf.getvalue()


def build(lang: str, offline: bool, off_route: bool) -> VoicePipeline:
    cfg = VoiceConfig.from_env()
    guard = CostGuard(cfg.cost_guard_inr_per_driver_day,
                      on_exceeded=lambda d, day, spent, cap: print(
                          f"!! COST GUARD: driver {d} spent ₹{spent:.2f} on {day} (cap ₹{cap})"))
    stt = speech = chat = None
    if not offline:
        from voice.sarvam import SarvamClient
        from voice.tts_cache import TtsCache

        client = SarvamClient(cfg)

        def stt(wav, lang_):
            r = client.speech_to_text(wav, lang_)
            return r.transcript, r.cost_inr

        def synth(text, lang_):
            r = client.text_to_speech(text, lang_)
            return r.wav, r.cost_inr

        def chat(messages, timeout):
            r = client.chat(messages, timeout=timeout)
            return r.text, r.cost_inr

        speech = TtsCache(synth, cfg.tts_model, cfg.speaker_for, cfg.tts_sample_rate)
    return VoicePipeline(cfg=cfg, stt=stt, speech=speech, facts=FakeEngine(off_route=off_route),
                         llm_chat=chat, cost_guard=guard, log=JsonlAnswerLog(LOG_PATH))


def show(result) -> None:
    rec = result.record
    print(f"  intent : {rec.intent} ({rec.intent_source})  transcript: {rec.transcript!r}")
    print(f"  answer : {result.text}")
    print(f"  latency: {json.dumps(rec.latency_ms)}  cost ₹{rec.cost_inr.get('total', 0):.4f}"
          + ("  [OVER BUDGET]" if rec.over_budget else ""))
    if rec.error:
        print(f"  note   : {rec.error}")
    if result.wav:
        OUT_DIR.mkdir(exist_ok=True)
        out = OUT_DIR / "answer.wav"
        out.write_bytes(result.wav)
        print(f"  audio  : {out}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", default="kn", choices=available_languages())
    ap.add_argument("--offline", action="store_true", help="no Sarvam calls: text in, text out")
    ap.add_argument("--wav", type=Path, help="transcribe this WAV file once and exit")
    ap.add_argument("--mic", action="store_true", help="push-to-talk from the laptop microphone")
    ap.add_argument("--off-route", action="store_true", help="pretend the driver is off route")
    args = ap.parse_args(argv)

    load_dotenv()
    if (args.wav or args.mic) and args.offline:
        ap.error("--wav/--mic need Sarvam STT; drop --offline")
    pipeline = build(args.lang, args.offline, args.off_route)
    ids = {"trip_id": "demo-trip", "driver_id": "demo-driver", "lang": args.lang}

    if args.wav:
        show(pipeline.handle_audio(args.wav.read_bytes(), **ids))
        return
    print(f"TurnWise voice demo ({args.lang}). Ctrl+C to quit. "
          + ("Enter to talk." if args.mic else "Type a question."))
    try:
        while True:
            if args.mic:
                show(pipeline.handle_audio(record_push_to_talk(), **ids))
            else:
                text = input("> ").strip()
                if text:
                    show(pipeline.handle_text(text, **ids))
    except (KeyboardInterrupt, EOFError):
        print()


if __name__ == "__main__":
    main()
