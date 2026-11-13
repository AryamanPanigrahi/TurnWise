"""One command to run a field test from a laptop:

    python -m backend.fieldserver            # then open the printed https://... address on the phone

It reads `.env`, turns on the field kit (`/field`) and trace recording (`traces/local/`),
makes a self-signed HTTPS certificate (phone browsers refuse GPS on plain http), and serves
on the local network. Valhalla must be running (`docker start valhalla`).

For a drive, the laptop rides along: connect it to the PHONE'S HOTSPOT, start this, and open
the address on the phone. No internet tunnel, nothing leaves the two devices except map tiles.

Development only. It listens on the local network, protected by the API token and HTTPS, so
run it on a network you trust (your hotspot), not public Wi-Fi.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CERT_DIR = ROOT / ".certs"
OPENSSL_GUESSES = [r"C:\Program Files\Git\usr\bin\openssl.exe", r"C:\Program Files\Git\mingw64\bin\openssl.exe",
                   "/usr/bin/openssl", "/opt/homebrew/bin/openssl"]


def parse_env(text: str) -> dict[str, str]:
    """Minimal .env reader: KEY=VALUE lines, `#` comments, optional quotes. No variable expansion."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()      # trailing comment
        out[key.strip()] = value
    return out


def lan_ip() -> str:
    """This machine's address on the local network (no packets are sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def find_openssl() -> str | None:
    return shutil.which("openssl") or next((p for p in OPENSSL_GUESSES if Path(p).exists()), None)


def ensure_certificate(ip: str) -> tuple[Path, Path]:
    """A self-signed certificate valid for this machine's current address (remade when it changes)."""
    cert, key, marker = CERT_DIR / "cert.pem", CERT_DIR / "key.pem", CERT_DIR / "ip.txt"
    if cert.exists() and key.exists() and marker.exists() and marker.read_text().strip() == ip:
        return cert, key
    openssl = find_openssl()
    if openssl is None:
        sys.exit("openssl not found. Install Git for Windows (it includes openssl) or add openssl to PATH.")
    CERT_DIR.mkdir(exist_ok=True)
    subprocess.run(
        [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
         "-keyout", str(key), "-out", str(cert), "-subj", "/CN=TurnWise field test",
         "-addext", f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:localhost"],
        check=True, capture_output=True, env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    marker.write_text(ip)
    return cert, key


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the TurnWise field-test server over HTTPS.")
    ap.add_argument("--host", default="0.0.0.0", help="address to listen on (default: all, so the phone can reach it)")
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--db", action="store_true", help="also record trips in PostgreSQL (needs `docker compose up -d db`)")
    ap.add_argument("--no-record", action="store_true", help="do not write GPS traces to traces/local/")
    ap.add_argument("--http", action="store_true",
                    help="plain http instead of https: for the DEBUG Android app (a native app gets GPS without "
                         "https and cannot trust the self-signed certificate). Use only on your own hotspot.")
    a = ap.parse_args(argv)

    env_file = ROOT / ".env"
    if env_file.exists():
        for k, v in parse_env(env_file.read_text(encoding="utf-8")).items():
            os.environ.setdefault(k, v)
    token = os.environ.get("TURNWISE_API_TOKEN")
    if not token:
        sys.exit("TURNWISE_API_TOKEN is not set. Add it to .env (see .env.example).")
    os.environ["TURNWISE_FIELD_KIT"] = "1"
    if not a.db:
        os.environ.pop("DATABASE_URL", None)              # a drive test should not depend on Postgres
    if not a.no_record:
        os.environ.setdefault("TURNWISE_RECORD_DIR", str(ROOT / "traces" / "local"))

    ip = lan_ip()
    if a.http:
        cert = key = None
        print(f"""
TurnWise field test (plain http, for the debug Android app)
-----------------------------------------------------------
In the app, set the server to:   http://{ip}:{a.port}
and paste this API token:        {token}

The token travels unencrypted: use this only on your own phone hotspot, never public Wi-Fi.
Recording to: {os.environ.get('TURNWISE_RECORD_DIR', '(off)')}
Valhalla must be running  ->  docker start valhalla.   Stop with Ctrl+C.
""", flush=True)
    else:
        cert, key = ensure_certificate(ip)
        print(f"""
TurnWise field test
-------------------
On the phone (same Wi-Fi or the phone's own hotspot), open:

    https://{ip}:{a.port}/field

  1. The browser warns about the certificate (it is self-signed, made on this laptop).
     Choose Advanced -> Proceed. That is expected for this local test.
  2. Allow location when asked. Keep the screen on and the page in front.
  3. Paste this API token into the page:  {token}

Recording to: {os.environ.get('TURNWISE_RECORD_DIR', '(off)')}
Database:     {'on' if a.db else 'off (trips in memory only)'}
Valhalla:     must be running  ->  docker start valhalla
Windows may ask to allow Python through the firewall: allow it on Private networks.
Stop with Ctrl+C.
""", flush=True)

    import uvicorn
    tls = {} if a.http else {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    uvicorn.run("backend.app:app_from_env", factory=True, host=a.host, port=a.port, log_level="warning", **tls)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
