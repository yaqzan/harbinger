"""The public server: web/ plus state/data.json and /api/health, on 127.0.0.1 only.

Read-only by design (no auth, no input surface): GET and HEAD, nothing else.
"""

from __future__ import annotations

import json
import mimetypes
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import OUTPUT_FILE, WEB_DIR, __version__

HOST, PORT = "127.0.0.1", 5006
STALE_HOURS = 40  # the daily Steam job rebuilds data.json; older than this means a job is failing


def health() -> dict:
    """Always answered with 200 while the server is up (the watchdog restarts on anything
    else); `stale` says whether the scheduled jobs are keeping data.json fresh."""
    out = {"ok": True, "version": __version__, "generated_at": None, "age_hours": None,
           "confirmed": None, "stale": True}
    try:
        data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    age = (datetime.now() - datetime.fromisoformat(data["generated_at"])).total_seconds() / 3600
    out.update(generated_at=data["generated_at"], age_hours=round(age, 1),
               confirmed=data["summary"]["confirmed_count"], stale=age >= STALE_HOURS)
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "harbinger"

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/api/health":
            h = health()
            return self._send(200, json.dumps(h).encode(), "application/json")
        if path == "/data.json":
            if not OUTPUT_FILE.exists():
                return self._send(404, b'{"error": "no data yet"}', "application/json")
            return self._send(200, OUTPUT_FILE.read_bytes(), "application/json; charset=utf-8")
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        if WEB_DIR.resolve() not in target.parents or not target.is_file():
            return self._send(404, b"Not found", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    do_HEAD = do_GET

    def log_message(self, fmt, *args):
        pass


def serve(host: str = HOST, port: int = PORT) -> None:
    print(f"harbinger serving http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
