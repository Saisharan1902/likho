"""Local dashboard: a tiny JSON API + the single-page UI in dashboard/index.html.

Security: binds to 127.0.0.1 only, rejects foreign Host headers (DNS rebinding) and requires an
X-Dictly header on every write, which a random website can't send cross-origin. Otherwise any page
you visit could quietly change your settings (e.g. point AI cleanup at its own server).
"""
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import llm
from .config import AUDIO_DIR, DEFAULTS, HOTKEYS
from .transcriber import MODELS

INDEX = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"
SECRET_KEYS = {"ai_api_key"}


class DashboardServer:
    def __init__(self, cfg, db, port=8765, status=lambda: {}, on_show=lambda: None):
        self.cfg, self.db, self.status, self.on_show = cfg, db, status, on_show
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"

    def start(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    # ------------------------------------------------------------------
    def public_settings(self):
        s = self.cfg.all()
        s["ai_api_key_set"] = bool(s.pop("ai_api_key"))
        return {"settings": s, "models": MODELS, "hotkeys": HOTKEYS, "providers": llm.PROVIDERS,
                "default_prompt": DEFAULTS["ai_prompt"]}

    def save_settings(self, body):
        changes = {}
        for k, v in body.items():
            if k not in DEFAULTS:
                continue
            if k in SECRET_KEYS and v == "" and not body.get("ai_api_key_clear"):
                continue  # blank key field = "keep the saved key"
            if type(v) is not type(DEFAULTS[k]):
                raise ValueError(f"{k} must be {type(DEFAULTS[k]).__name__}")
            changes[k] = v
        if "hotkey" in changes and changes["hotkey"] not in HOTKEYS:
            raise ValueError("unknown hotkey")
        if "ai_mode" in changes and changes["ai_mode"] not in ("smart", "always"):
            raise ValueError("ai_mode must be smart or always")
        if "ai_provider" in changes and changes["ai_provider"] not in llm.PROVIDERS:
            raise ValueError("unknown AI provider")
        if "paste_mode" in changes and changes["paste_mode"] not in ("paste", "copy"):
            raise ValueError("paste_mode must be paste or copy")
        self.cfg.update(changes)
        return self.public_settings()

    def test_ai(self, body):
        s = self.cfg.all()
        s.update({k: v for k, v in body.items() if k.startswith("ai_") and (v or k not in SECRET_KEYS)})
        sample = "so um can you send me the uh the report by friday no wait thursday and like cc priya"
        try:
            t = time.monotonic()
            out = llm.cleanup(sample, s)
            return {"ok": True, "input": sample, "output": out, "seconds": round(time.monotonic() - t, 2)}
        except Exception as e:  # report any failure (bad URL, wrong model, auth) to the UI
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def delete_all_audio(self):
        removed = 0
        for f in AUDIO_DIR.glob("*.wav"):
            f.unlink(missing_ok=True)
            removed += 1
        self.db.clear_audio()
        return {"ok": True, "removed": removed}

    def delete_entry(self, row_id):
        row = self.db.get(row_id)
        if row and row["audio_path"]:
            Path(row["audio_path"]).unlink(missing_ok=True)
        self.db.delete(row_id)

    # ------------------------------------------------------------------
    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body=b"", ctype="application/json"):
                if isinstance(body, (dict, list)):
                    body = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _guard(self, write=False):
                host = (self.headers.get("Host") or "").split(":")[0]
                if host not in ("127.0.0.1", "localhost"):
                    self._send(403, {"error": "forbidden host"})
                    return False
                if write and self.headers.get("X-Dictly") != "1":
                    self._send(403, {"error": "missing X-Dictly header"})
                    return False
                return True

            def _json_body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}")

            def do_GET(self):
                if not self._guard():
                    return
                url = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                if url.path == "/":
                    return self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
                if url.path == "/api/stats":
                    return self._send(200, server.db.stats(typing_wpm=server.cfg["typing_wpm"]))
                if url.path == "/api/history":
                    return self._send(200, server.db.history(q.get("q", ""), int(q.get("limit", 50)),
                                                             int(q.get("offset", 0))))
                if url.path == "/api/settings":
                    return self._send(200, server.public_settings())
                if url.path == "/api/status":
                    return self._send(200, server.status())
                m = re.fullmatch(r"/audio/(\d+)", url.path)
                if m:
                    row = server.db.get(int(m.group(1)))
                    # only serve files recorded by the app, from the audio folder
                    if row and row["audio_path"] and Path(row["audio_path"]).parent == AUDIO_DIR \
                            and Path(row["audio_path"]).exists():
                        return self._send(200, Path(row["audio_path"]).read_bytes(), "audio/wav")
                return self._send(404, {"error": "not found"})

            def do_POST(self):
                if not self._guard(write=True):
                    return
                try:
                    body = self._json_body()
                    if self.path == "/api/settings":
                        return self._send(200, server.save_settings(body))
                    if self.path == "/api/test-ai":
                        return self._send(200, server.test_ai(body))
                    if self.path == "/api/show":  # Dictly.app was clicked while already running
                        server.on_show()
                        return self._send(200, {"ok": True})
                except (ValueError, json.JSONDecodeError) as e:
                    return self._send(400, {"error": str(e)})
                return self._send(404, {"error": "not found"})

            def do_DELETE(self):
                if not self._guard(write=True):
                    return
                if self.path == "/api/recordings":
                    return self._send(200, server.delete_all_audio())
                m = re.fullmatch(r"/api/history/(\d+)", self.path)
                if not m:
                    return self._send(404, {"error": "not found"})
                server.delete_entry(int(m.group(1)))
                return self._send(200, {"ok": True})

        return Handler
