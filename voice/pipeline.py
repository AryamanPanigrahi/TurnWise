"""The push-to-talk voice loop:

    audio -> STT -> intent (rules, then LLM label) -> facts (route engine)
          -> templated sentence -> TTS (cached) -> speaker

Every answer is logged with per-stage latency and cost. Dependencies are passed
in as plain callables so the loop runs offline in tests and on a laptop with a
fake engine before the backend exists.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol

from voice.answer import Rendered, render_alert, render_answer
from voice.answer_log import AnswerRecord, AnswerSink
from voice.config import VoiceConfig
from voice.cost_guard import CostGuard
from voice.intent_router import Intent, route
from voice.llm_fallback import ChatFn, classify

SttFn = Callable[[bytes, str], tuple[str, float]]                 # (wav, lang) -> (transcript, cost_inr)
FactsFn = Callable[[str, str, Mapping[str, Any]], Mapping[str, Any]]  # POST /v1/ask: (trip, intent, slots) -> {answer_key, facts}


class Speech(Protocol):
    def get(self, text: str, lang: str) -> Any: ...  # returns object with .wav, .hit, .cost_inr


@dataclass(frozen=True)
class VoiceResult:
    text: str
    wav: bytes | None
    record: AnswerRecord


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class VoicePipeline:
    def __init__(self, *, cfg: VoiceConfig, stt: SttFn | None, speech: Speech | None,
                 facts: FactsFn, llm_chat: ChatFn | None = None,
                 cost_guard: CostGuard | None = None, log: AnswerSink | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.cfg = cfg
        self.stt = stt
        self.speech = speech
        self.facts = facts
        self.llm_chat = llm_chat
        self.cost_guard = cost_guard
        self.log = log
        self.clock = clock
        self.now = now
        self._last_intent: dict[str, Intent] = {}  # per trip, for "repeat"

    # -- public ------------------------------------------------------------
    def handle_audio(self, wav: bytes, *, trip_id: str, driver_id: str, lang: str) -> VoiceResult:
        if self.stt is None:
            raise RuntimeError("no STT configured")
        return self._run(trip_id, driver_id, lang, wav=wav)

    def handle_text(self, text: str, *, trip_id: str, driver_id: str, lang: str) -> VoiceResult:
        """Skip STT — for laptop development and tests."""
        return self._run(trip_id, driver_id, lang, text=text)

    def speak_alert(self, event: str, data: Mapping[str, Any] | None, *, driver_id: str,
                    lang: str) -> tuple[Rendered, bytes | None]:
        """Wrong-way and back-on-route alerts: templates + TTS only, never the LLM."""
        rendered = render_alert(lang, event, data)
        wav = None
        if self.speech is not None:
            try:
                spoken = self.speech.get(rendered.text, lang)
                wav = spoken.wav
                self._charge(driver_id, spoken.cost_inr)
            except Exception:
                wav = None  # the app still shows the alert text and plays a local beep
        return rendered, wav

    # -- internals -----------------------------------------------------------
    def _charge(self, driver_id: str, inr: float) -> None:
        if self.cost_guard is not None and inr > 0:
            self.cost_guard.add(driver_id, inr, self.now())

    def _run(self, trip_id: str, driver_id: str, lang: str, *, wav: bytes | None = None,
             text: str | None = None) -> VoiceResult:
        start = self.clock()
        lat: dict[str, float] = {}
        cost: dict[str, float] = {}
        errors: list[str] = []

        def mark(stage: str, since: float) -> float:
            t = self.clock()
            lat[stage] = round((t - since) * 1000, 1)
            return t

        # 1. Speech to text
        t = start
        if wav is not None:
            try:
                text, cost["stt"] = self.stt(wav, lang)
            except Exception as e:
                errors.append(f"stt: {e}")
                text = ""
            t = mark("stt", t)
        text = text or ""

        # 2. Intent: rules first, then the LLM label (if allowed and in budget)
        intent = route(text, lang)
        source = "rules" if intent.name != "unknown" else "none"
        t = mark("intent_rules", t)
        if intent.name == "unknown" and text.strip() and self.llm_chat is not None:
            if self.cost_guard is not None and self.cost_guard.over_cap(driver_id, self.now()):
                errors.append("llm skipped: driver over daily cost cap")
            else:
                remaining = self.cfg.llm_budget_s - (self.clock() - start)
                intent, cost["llm"], err = classify(text, lang, self.llm_chat, remaining)
                if err:
                    errors.append(err)
                if intent.name != "unknown":
                    source = "llm"
                t = mark("intent_llm", t)

        # 3. "repeat" re-asks the last question so facts are fresh (distances change).
        asked = intent
        if intent.name == "repeat":
            asked = self._last_intent.get(trip_id, Intent("unknown"))

        # 4. Facts from the route engine, then a templated sentence
        answer_key, facts = "please_repeat", {}
        if asked.name != "unknown":
            try:
                resp = self.facts(trip_id, asked.name, asked.slots)
                answer_key = str(resp.get("answer_key", "not_sure"))
                facts = dict(resp.get("facts") or {})
                self._last_intent[trip_id] = asked
            except Exception as e:
                errors.append(f"facts: {e}")
                answer_key = "not_sure"
            t = mark("facts", t)
        rendered = render_answer(lang, answer_key, facts)
        t = mark("render", t)

        # 5. Text to speech (cached)
        out_wav, cache_hit = None, None
        if self.speech is not None:
            try:
                spoken = self.speech.get(rendered.text, lang)
                out_wav, cache_hit = spoken.wav, spoken.hit
                if spoken.cost_inr:
                    cost["tts"] = spoken.cost_inr
            except Exception as e:
                errors.append(f"tts: {e}")
            t = mark("tts", t)

        lat["total"] = round((self.clock() - start) * 1000, 1)
        cost = {k: round(v, 6) for k, v in cost.items() if v}
        total_cost = round(sum(cost.values()), 6)
        cost["total"] = total_cost
        self._charge(driver_id, total_cost)
        budget = self.cfg.llm_budget_s if source == "llm" else self.cfg.templated_budget_s

        record = AnswerRecord(
            ts=_utc_iso(self.now()), trip_id=trip_id, driver_id=driver_id, lang=lang,
            transcript=text, intent=intent.name, intent_source=source, matched=intent.matched,
            answer_key=answer_key, facts=facts, template_key=rendered.template_key,
            fell_back=rendered.fell_back, fallback_reason=rendered.reason,
            tts_cache_hit=cache_hit, latency_ms=lat, cost_inr=cost,
            over_budget=lat["total"] > budget * 1000, error="; ".join(errors) or None,
        )
        if self.log is not None:
            self.log.write(record)
        return VoiceResult(rendered.text, out_wav, record)
