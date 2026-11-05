"""Disk cache for synthesised speech.

Templated answers repeat constantly ("You are on the right road.", "300 metres
ahead take the flyover."), so caching their audio removes the TTS round-trip
(latency) and its cost. The key covers everything that changes the audio:
model, speaker, language, sample rate and exact text.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

DEFAULT_DIR = Path(__file__).parent / "cache"


@dataclass(frozen=True)
class CachedSpeech:
    wav: bytes
    hit: bool
    cost_inr: float  # 0 on a cache hit


class TtsCache:
    def __init__(self, synthesize: Callable[[str, str], tuple[bytes, float]],
                 model: str, speaker_for: Callable[[str], str], sample_rate: int,
                 directory: Path = DEFAULT_DIR):
        """`synthesize(text, lang)` returns (wav_bytes, cost_inr)."""
        self._synth = synthesize
        self._model = model
        self._speaker_for = speaker_for
        self._rate = sample_rate
        self.dir = Path(directory)

    def key(self, text: str, lang: str) -> str:
        raw = "\x1f".join([self._model, self._speaker_for(lang), lang, str(self._rate), text])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.dir / key[:2] / f"{key}.wav"

    def get(self, text: str, lang: str) -> CachedSpeech:
        path = self._path(self.key(text, lang))
        if path.is_file():
            return CachedSpeech(path.read_bytes(), hit=True, cost_inr=0.0)
        wav, cost = self._synth(text, lang)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: a crash mid-write must never leave a truncated clip.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(wav)
        os.replace(tmp, path)
        return CachedSpeech(wav, hit=False, cost_inr=cost)

    def warm(self, texts: list[str], lang: str) -> int:
        """Pre-synthesise fixed phrases (e.g. not_sure, alerts). Returns how many were new."""
        return sum(0 if self.get(t, lang).hit else 1 for t in texts)
