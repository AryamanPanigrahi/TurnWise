"""Shared test doubles for the voice layer (no network)."""

import base64
import io
import json
import wave


def make_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


class FakeTransport:
    """Records requests; answers from a {path_suffix: (status, json_obj | bytes)} map."""

    def __init__(self, routes, raise_timeout_on=()):
        self.routes = routes
        self.raise_timeout_on = raise_timeout_on
        self.calls = []

    def post(self, url, body, headers, timeout):
        self.calls.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        for suffix in self.raise_timeout_on:
            if url.endswith(suffix):
                raise TimeoutError("fake timeout")
        for suffix, (status, payload) in self.routes.items():
            if url.endswith(suffix):
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                return status, raw
        return 404, b"{}"


def tts_route(wav: bytes | None = None):
    return (200, {"audios": [base64.b64encode(wav or make_wav(0.5)).decode()]})


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s
