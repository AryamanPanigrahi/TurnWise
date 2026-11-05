"""Voice-layer configuration, read from environment variables (.env).

Model names, speaker IDs, request fields and prices were checked against
docs.sarvam.ai on 2026-11-05 (pay-as-you-go list prices, excluding GST). Prices
and models change; every value can be overridden from `.env`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

# Our language code -> Sarvam BCP-47 code.
SARVAM_LANG = {
    "kn": "kn-IN",
    "hi": "hi-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "ml": "ml-IN",
    "mr": "mr-IN",
    "bn": "bn-IN",
    "gu": "gu-IN",
    "en": "en-IN",
}


def _f(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    return float(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class VoiceConfig:
    api_key: str = ""
    base_url: str = "https://api.sarvam.ai"
    # saarika:* is deprecated; /speech-to-text accepts saaras:v3 and saaras:v4.
    stt_model: str = "saaras:v4"
    # bulbul:v2 is legacy; v4-flash is recommended and a third the price of v3.
    tts_model: str = "bulbul:v4-flash"
    # sarvam-m is deprecated (no longer served). sarvam-105b is the v1 chat model.
    llm_model: str = "sarvam-105b"
    # bulbul:v4-flash speaker IDs are per language ("<name>_<lang>_<style>").
    # "default" is the API's own default voice, used for languages not listed.
    tts_speakers: dict[str, str] = field(default_factory=lambda: {
        "kn": "chaitra_kn_conversation",
        "hi": "ritu_hi_conversation",
        "en": "simran_en_customer",
        "default": "shubh_enhi_ads",
    })
    tts_sample_rate: int = 22050

    # Latency budgets (CLAUDE.md product rule #3), seconds.
    templated_budget_s: float = 1.5
    llm_budget_s: float = 3.0
    http_timeout_s: float = 5.0

    # Prices in INR, pay-as-you-go, excl. GST (docs.sarvam.ai pricing, 2026-11-05).
    stt_inr_per_audio_hour: float = 29.40          # ₹0.49/min, all STT models
    tts_inr_per_10k_chars: float = 10.0            # bulbul:v4-flash (v3 is ₹30)
    llm_inr_per_1m_input_tokens: float = 15.0      # sarvam-105b
    llm_inr_per_1m_output_tokens: float = 60.0     # sarvam-105b

    # Cost guard (CLAUDE.md conventions): alert above this per driver per IST day.
    cost_guard_inr_per_driver_day: float = 5.0

    def speaker_for(self, lang: str) -> str:
        return self.tts_speakers.get(lang, self.tts_speakers["default"])

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "VoiceConfig":
        env = os.environ if env is None else env
        d = cls()
        speakers = dict(d.tts_speakers)
        if env.get("SARVAM_TTS_SPEAKER"):
            # One voice for every language (only sensible for multilingual voices).
            speakers = {"default": env["SARVAM_TTS_SPEAKER"]}
        for lang in SARVAM_LANG:
            v = env.get(f"SARVAM_TTS_SPEAKER_{lang.upper()}")
            if v:
                speakers[lang] = v
        return cls(
            api_key=env.get("SARVAM_API_KEY", ""),
            base_url=env.get("SARVAM_BASE_URL", d.base_url).rstrip("/"),
            stt_model=env.get("SARVAM_STT_MODEL", d.stt_model),
            tts_model=env.get("SARVAM_TTS_MODEL", d.tts_model),
            llm_model=env.get("SARVAM_LLM_MODEL", d.llm_model),
            tts_speakers=speakers,
            stt_inr_per_audio_hour=_f(env, "SARVAM_STT_INR_PER_AUDIO_HOUR", d.stt_inr_per_audio_hour),
            tts_inr_per_10k_chars=_f(env, "SARVAM_TTS_INR_PER_10K_CHARS", d.tts_inr_per_10k_chars),
            llm_inr_per_1m_input_tokens=_f(env, "SARVAM_LLM_INR_PER_1M_INPUT_TOKENS", d.llm_inr_per_1m_input_tokens),
            llm_inr_per_1m_output_tokens=_f(env, "SARVAM_LLM_INR_PER_1M_OUTPUT_TOKENS", d.llm_inr_per_1m_output_tokens),
            cost_guard_inr_per_driver_day=_f(env, "COST_GUARD_INR_PER_DRIVER_DAY", d.cost_guard_inr_per_driver_day),
        )
