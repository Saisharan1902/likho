"""Section 7 — the full pipeline end-to-end: real speech (macOS `say`) → Whisper → replacements → AI → output → history."""
import json
import subprocess
import threading
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest

from likho import overlay
from likho.config import Config
from likho.db import DB
from likho.pipeline import Pipeline


@pytest.fixture(scope="module")
def speech(tmp_path_factory):
    path = tmp_path_factory.mktemp("say") / "s.wav"
    subprocess.run(["say", "-o", str(path), "--data-format=LEI16@16000",
                    "Please send the report to my email by Friday."], check=True)
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


@pytest.fixture
def pipe(tmp_data):
    cfg = Config()
    cfg.update({"model": "mlx-community/whisper-base.en-mlx"})  # small model keeps tests quick
    p = Pipeline(cfg, DB(), output=lambda text, mode: p.typed.append((text, mode)),
                 on_state=lambda s: p.states.append(s), on_status=lambda **kw: p.status.update(kw))
    p.typed, p.states, p.status = [], [], {}
    return p


def test_voice_is_not_saved_by_default(pipe, speech, tmp_data):
    row = pipe.handle(speech)
    assert row["audio_path"] is None and not list((tmp_data / "audio").glob("*.wav"))


def test_speech_is_typed_and_saved(pipe, speech, tmp_data):
    pipe.cfg.update({"replacements": [{"from": "my email", "to": "ada@example.com"}], "save_audio": True})
    row = pipe.handle(speech, app_name="Mail")

    text, mode = pipe.typed[0]
    assert "ada@example.com" in text and "report" in text.lower() and mode == "paste"
    assert pipe.states == [overlay.TRANSCRIBING, overlay.DONE]
    assert row["app_name"] == "Mail" and row["final_text"] == text and "my email" in row["raw_text"].lower()
    assert row["word_count"] == len(text.split()) and row["duration_sec"] > 1 and row["ai_used"] == 0
    assert row["total_sec"] >= row["transcribe_sec"] > 0 and row["ai_sec"] is None
    assert (tmp_data / "audio" / f"{row['id']}.wav").exists()


def test_copy_mode_and_no_audio(pipe, speech, tmp_data):
    pipe.cfg.update({"paste_mode": "copy", "save_audio": False})
    row = pipe.handle(speech)
    assert pipe.typed[0][1] == "copy"
    assert row["audio_path"] is None and not list((tmp_data / "audio").glob("*.wav"))


def test_too_short_is_ignored(pipe):
    assert pipe.handle(np.zeros(1600, dtype=np.float32)) is None  # 0.1s accidental tap
    assert pipe.typed == [] and pipe.states == [overlay.IDLE] and pipe.db.history()["total"] == 0


def test_silence_types_nothing(pipe):
    assert pipe.handle(np.zeros(16000 * 2, dtype=np.float32)) is None
    assert pipe.typed == [] and pipe.states[-1] == overlay.IDLE


@pytest.fixture
def fake_ai():
    calls = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            out = json.dumps({"choices": [{"message": {"content": "CLEANED TEXT"}}]}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(out)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1", calls
    srv.shutdown()


def test_ai_cleanup_used_when_enabled(pipe, speech, fake_ai):
    url, calls = fake_ai
    pipe.cfg.update({"ai_enabled": True, "ai_mode": "always", "ai_provider": "custom", "ai_base_url": url})
    row = pipe.handle(speech, app_name="Slack")
    assert pipe.typed[0][0] == "CLEANED TEXT" and row["ai_used"] == 1
    assert "report" in row["raw_text"].lower()
    assert "Slack" in calls[0]["messages"][1]["content"]  # app context is passed to the AI


def test_ai_failure_falls_back_to_raw_text(pipe, speech):
    pipe.cfg.update({"ai_enabled": True, "ai_mode": "always", "ai_base_url": "http://127.0.0.1:9/v1"})  # nothing listening
    row = pipe.handle(speech)
    assert "report" in pipe.typed[0][0].lower() and row["ai_used"] == 0
    assert "AI cleanup failed" in pipe.status["error"]
    assert pipe.states[-1] == overlay.DONE


def test_smart_mode_skips_ai_for_clean_dictation(pipe, speech, fake_ai):
    url, calls = fake_ai
    pipe.cfg.update({"ai_enabled": True, "ai_mode": "smart", "ai_provider": "custom", "ai_base_url": url})
    row = pipe.handle(speech)  # "Please send the report to my email by Friday." — nothing to fix
    assert calls == [] and row["ai_used"] == 0 and row["ai_sec"] is None


def test_blocked_paste_warns_and_keeps_text(tmp_data, speech):
    """Accessibility off: macOS drops the ⌘V, so the user must be told and the text kept on the clipboard."""
    cfg = Config()
    cfg.update({"model": "mlx-community/whisper-base.en-mlx"})
    states, status = [], {}
    p = Pipeline(cfg, DB(), output=lambda text, mode: False,
                 on_state=states.append, on_status=lambda **kw: status.update(kw))
    row = p.handle(speech)
    assert row is not None and states[-1] == overlay.ERROR
    assert "Accessibility" in status["error"] and "⌘V" in status["error"]
