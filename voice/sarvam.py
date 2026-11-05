"""Thin Sarvam API clients: speech-to-text, text-to-speech, chat (LLM).

Design:
- HTTP goes through a small `Transport` interface. The default uses only the
  standard library (urllib), so there is no new dependency; tests inject a fake.
- Clients are synchronous and only called during push-to-talk (CLAUDE.md #4:
  never stream audio continuously).
- Every call returns what it cost, so the pipeline can log spend per answer.

TODO(ram): STT here is the batch REST endpoint (send the clip after the driver
releases push-to-talk). The streaming WebSocket endpoint can cut latency by
transcribing while the driver is still speaking — evaluate in week 3.
"""

from __future__ import annotations

import base64
import io
import json
import uuid
import wave
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import error as urlerror
from urllib import request as urlrequest

from voice.config import SARVAM_LANG, VoiceConfig


class SarvamError(RuntimeError):
    pass


class Transport(Protocol):
    def post(self, url: str, body: bytes, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
        """POST and return (status_code, response_body). Raise TimeoutError on timeout."""


class UrllibTransport:
    def post(self, url: str, body: bytes, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
        req = urlrequest.Request(url, data=body, headers=headers, method="POST")
        try:
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urlerror.HTTPError as e:
            return e.code, e.read()
        except (TimeoutError, urlerror.URLError) as e:
            if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
                raise TimeoutError(str(e)) from e
            raise SarvamError(f"network error: {e}") from e


def wav_duration_s(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getnframes() / float(w.getframerate())


def _multipart(fields: dict[str, str], file_field: str, filename: str, data: bytes,
               content_type: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    out.write(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode()
    )
    out.write(data)
    out.write(f"\r\n--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


@dataclass(frozen=True)
class SttResult:
    transcript: str
    language_code: str | None
    audio_s: float
    cost_inr: float


@dataclass(frozen=True)
class TtsResult:
    wav: bytes
    chars: int
    cost_inr: float


@dataclass(frozen=True)
class ChatResult:
    text: str
    tokens: int
    cost_inr: float


class SarvamClient:
    def __init__(self, config: VoiceConfig, transport: Transport | None = None):
        if not config.api_key:
            raise SarvamError("SARVAM_API_KEY is not set (see .env.example)")
        self.cfg = config
        self.transport = transport or UrllibTransport()

    # -- helpers -----------------------------------------------------------
    def _post(self, path: str, body: bytes, content_type: str, timeout: float | None) -> Any:
        headers = {"api-subscription-key": self.cfg.api_key, "Content-Type": content_type}
        status, raw = self.transport.post(
            f"{self.cfg.base_url}{path}", body, headers, timeout or self.cfg.http_timeout_s
        )
        if status >= 400:
            raise SarvamError(f"{path} -> HTTP {status}: {raw[:300]!r}")
        try:
            return json.loads(raw)
        except ValueError as e:
            raise SarvamError(f"{path} returned non-JSON body") from e

    @staticmethod
    def _lang(lang: str) -> str:
        try:
            return SARVAM_LANG[lang]
        except KeyError:
            raise SarvamError(f"unsupported language '{lang}'") from None

    # -- API ---------------------------------------------------------------
    def speech_to_text(self, wav: bytes, lang: str, timeout: float | None = None) -> SttResult:
        audio_s = wav_duration_s(wav)
        body, ctype = _multipart(
            {"model": self.cfg.stt_model, "language_code": self._lang(lang)},
            "file", "clip.wav", wav, "audio/wav",
        )
        data = self._post("/speech-to-text", body, ctype, timeout)
        cost = audio_s / 3600.0 * self.cfg.stt_inr_per_audio_hour
        return SttResult(data.get("transcript", "") or "", data.get("language_code"), audio_s, cost)

    def text_to_speech(self, text: str, lang: str, timeout: float | None = None) -> TtsResult:
        payload = {
            "text": text,
            "target_language_code": self._lang(lang),
            "speaker": self.cfg.speaker_for(lang),
            "model": self.cfg.tts_model,
            "speech_sample_rate": self.cfg.tts_sample_rate,
        }
        data = self._post("/text-to-speech", json.dumps(payload).encode(), "application/json", timeout)
        audios = data.get("audios") or []
        if not audios:
            raise SarvamError("text-to-speech returned no audio")
        wav = base64.b64decode(audios[0])
        cost = len(text) / 10_000.0 * self.cfg.tts_inr_per_10k_chars
        return TtsResult(wav, len(text), cost)

    def chat(self, messages: list[dict[str, str]], timeout: float | None = None,
             max_tokens: int = 20) -> ChatResult:
        payload = {"model": self.cfg.llm_model, "messages": messages,
                   "temperature": 0, "max_tokens": max_tokens}
        data = self._post("/v1/chat/completions", json.dumps(payload).encode(), "application/json", timeout)
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise SarvamError("chat returned unexpected shape") from e
        tokens = int((data.get("usage") or {}).get("total_tokens", 0))
        return ChatResult(text, tokens, tokens / 1000.0 * self.cfg.llm_inr_per_1k_tokens)
