"""Voice-layer configuration, read from environment variables (.env).

UNVERIFIED VALUES: endpoint paths, model names, speaker names and prices below
were written from memory without access to docs.sarvam.ai. Check each one
against the current Sarvam docs and pricing page before trusting cost numbers.
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
    stt_model: str = "saarika:v2.5"          # UNVERIFIED
    tts_model: str = "bulbul:v2"              # UNVERIFIED
    llm_model: str = "sarvam-m"               # UNVERIFIED
    tts_speakers: dict[str, str] = field(default_factory=lambda: {"default": "anushka"})  # UNVERIFIED
    tts_sample_rate: int = 22050

    # Latency budgets (CLAUDE.md product rule #3), seconds.
    templated_budget_s: float = 1.5
    llm_budget_s: float = 3.0
    http_timeout_s: float = 5.0

    # Prices in INR (UNVERIFIED placeholders — set real values via env).
    stt_inr_per_audio_hour: float = 30.0
    tts_inr_per_10k_chars: float = 15.0
    llm_inr_per_1k_tokens: float = 0.0

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
            speakers["default"] = env["SARVAM_TTS_SPEAKER"]
        return cls(
            api_key=env.get("SARVAM_API_KEY", ""),
            base_url=env.get("SARVAM_BASE_URL", d.base_url).rstrip("/"),
            stt_model=env.get("SARVAM_STT_MODEL", d.stt_model),
            tts_model=env.get("SARVAM_TTS_MODEL", d.tts_model),
            llm_model=env.get("SARVAM_LLM_MODEL", d.llm_model),
            tts_speakers=speakers,
            stt_inr_per_audio_hour=_f(env, "SARVAM_STT_INR_PER_AUDIO_HOUR", d.stt_inr_per_audio_hour),
            tts_inr_per_10k_chars=_f(env, "SARVAM_TTS_INR_PER_10K_CHARS", d.tts_inr_per_10k_chars),
            llm_inr_per_1k_tokens=_f(env, "SARVAM_LLM_INR_PER_1K_TOKENS", d.llm_inr_per_1k_tokens),
            cost_guard_inr_per_driver_day=_f(env, "COST_GUARD_INR_PER_DRIVER_DAY", d.cost_guard_inr_per_driver_day),
        )
