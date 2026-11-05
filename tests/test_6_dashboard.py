"""Section 6 — dashboard API. Starts the real server on a free port against a temp data folder."""
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest

from likho.audio import save_wav
from likho.config import Config
from likho.db import DB


@pytest.fixture
def srv(tmp_data, monkeypatch):
    import likho.server as server
    monkeypatch.setattr(server, "AUDIO_DIR", tmp_data / "audio")
    cfg, db = Config(), DB()
    s = server.DashboardServer(cfg, db, port=0, status=lambda: {"message": "Ready"}).start()
    yield s
    s.stop()


def call(srv, path, method="GET", body=None, headers=None):
    h = {"Content-Type": "application/json", "X-Likho": "1", **(headers or {})}
    req = urllib.request.Request(srv.url + path, method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers["Content-Type"] == "application/json" else raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_page_and_status(srv):
    code, html = call(srv, "/")
    assert code == 200 and b"Likho Dashboard" in html
    assert call(srv, "/api/status") == (200, {"message": "Ready"})


def test_stats_and_history(srv):
    srv.db.add(raw_text="hello there world", final_text="Hello there, world.", duration_sec=3,
               transcribe_sec=0.3, word_count=3, app_name="Notes", model="m")
    code, stats = call(srv, "/api/stats")
    assert code == 200 and stats["words"] == 3 and len(stats["daily"]) == 30
    code, hist = call(srv, "/api/history?q=there")
    assert hist["total"] == 1 and hist["items"][0]["final_text"] == "Hello there, world."
    assert call(srv, "/api/history?q=nope")[1]["total"] == 0


def test_delete_removes_audio_file(srv, tmp_data):
    rid = srv.db.add(raw_text="x", final_text="x", duration_sec=1, transcribe_sec=0.1, word_count=1)
    wav = tmp_data / "audio" / f"{rid}.wav"
    save_wav(wav, np.zeros(1600, dtype=np.float32))
    srv.db.set_audio(rid, str(wav))

    code, body = call(srv, f"/audio/{rid}")
    assert code == 200 and body[:4] == b"RIFF"
    assert call(srv, f"/api/history/{rid}", "DELETE")[0] == 200
    assert not wav.exists() and srv.db.get(rid) is None


def test_delete_all_recordings_keeps_text(srv, tmp_data):
    for i in range(3):
        rid = srv.db.add(raw_text=f"t{i}", final_text=f"t{i}", duration_sec=1, transcribe_sec=0.1, word_count=1)
        wav = tmp_data / "audio" / f"{rid}.wav"
        save_wav(wav, np.zeros(160, dtype=np.float32))
        srv.db.set_audio(rid, str(wav))
    code, body = call(srv, "/api/recordings", "DELETE")
    assert code == 200 and body["removed"] == 3
    assert not list((tmp_data / "audio").glob("*.wav"))
    items = srv.db.history()["items"]
    assert len(items) == 3 and all(r["audio_path"] is None for r in items)


def test_show_asks_app_to_open_window(srv):
    shown = []
    srv.on_show = lambda: shown.append(True)
    assert call(srv, "/api/show", "POST", {})[0] == 200 and shown == [True]


def test_audio_outside_audio_dir_is_not_served(srv, tmp_data):
    secret = tmp_data / "secret.wav"
    secret.write_bytes(b"RIFF-secret")
    rid = srv.db.add(raw_text="x", final_text="x", duration_sec=1, transcribe_sec=0.1, word_count=1,
                     audio_path=str(secret))
    assert call(srv, f"/audio/{rid}")[0] == 404


def test_settings_roundtrip_hides_api_key(srv):
    code, body = call(srv, "/api/settings", "POST", {"hotkey": "fn", "ai_api_key": "sk-secret", "bogus": 1})
    assert code == 200
    assert body["settings"]["hotkey"] == "fn"
    assert "ai_api_key" not in body["settings"] and body["settings"]["ai_api_key_set"] is True
    assert srv.cfg["ai_api_key"] == "sk-secret"
    # empty key field keeps the saved key
    call(srv, "/api/settings", "POST", {"ai_api_key": ""})
    assert srv.cfg["ai_api_key"] == "sk-secret"


@pytest.mark.parametrize("bad", [{"hotkey": "space"}, {"save_audio": "yes"}, {"paste_mode": "shout"}])
def test_settings_validation(srv, bad):
    code, body = call(srv, "/api/settings", "POST", bad)
    assert code == 400 and body["error"]


def test_writes_need_header_and_local_host(srv):
    # a random website can't add custom headers cross-origin → blocked
    req = urllib.request.Request(srv.url + "/api/settings", method="POST", data=b'{"hotkey":"fn"}',
                                 headers={"Content-Type": "text/plain"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403
    # DNS-rebinding style request with a foreign Host header → blocked
    assert call(srv, "/api/stats", headers={"Host": "evil.example"})[0] == 403
    assert srv.cfg["hotkey"] == "right_option"


def test_ai_connection_check(srv):
    """Spin up a fake OpenAI-compatible server and point the 'Test connection' button at it."""
    seen = {}

    class Fake(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            seen["path"] = self.path
            seen["auth"] = self.headers.get("Authorization")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"choices": [{"message": {"content": "We should meet on Wednesday at 3."}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

    fake = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    try:
        code, r = call(srv, "/api/test-ai", "POST", {"ai_provider": "custom", "ai_base_url": f"http://127.0.0.1:{fake.server_port}/v1",
                                                     "ai_model": "tiny", "ai_api_key": "k"})
        assert code == 200 and r["ok"] and r["output"] == "We should meet on Wednesday at 3."
        assert seen["path"] == "/v1/chat/completions" and seen["auth"] == "Bearer k"
        assert seen["body"]["model"] == "tiny"
    finally:
        fake.shutdown()

    # unreachable endpoint → friendly error, not a crash
    code, r = call(srv, "/api/test-ai", "POST", {"ai_base_url": "http://127.0.0.1:9/v1"})
    assert code == 200 and r["ok"] is False and r["error"]
