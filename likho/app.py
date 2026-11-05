"""Likho: hold a key, talk, and the text appears wherever your cursor is.

Threads:
  main (Qt)      pill animation, menu-bar icon
  event tap      sees the hotkey (macos.HotkeyListener) → queues to its dispatcher thread
  dispatcher     start/stop the microphone
  worker         loads Whisper + runs the pipeline, one recording at a time
  http           dashboard
"""
import os
import queue
import signal
import sys
import threading
import time
import traceback
import webbrowser

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from . import llm, macos, overlay
from .audio import Recorder
from .config import Config
from .db import DB
from .pipeline import Pipeline, log
from .ptt import PushToTalk
from .server import DashboardServer
from .transcriber import warm_up
from .window import DashboardWindow  # imports QtWebEngine, which must happen before QApplication exists

IDLE_REWARM_SECONDS = 60  # idle longer than this → wake the speech model when you start talking


class LikhoApp(QObject):
    status_changed = Signal(str)
    show_requested = Signal()  # from the dashboard server's thread → opens the window on the GUI thread

    def __init__(self, qapp):
        super().__init__()
        self.qapp = qapp
        self.cfg, self.db = Config(), DB()
        self.status = {"message": "Starting…", "error": None}

        self.pill = overlay.Pill()
        self.pill.show()
        macos.make_overlay_window(self.pill)
        self.tray = overlay.make_tray(self.open_dashboard, self._toggle_ai, self.cfg["ai_enabled"], qapp.quit,
                                      on_open_browser=lambda: webbrowser.open(self.server.url))
        self.window = None  # dashboard window, created on first open (the web view is heavy)
        self.status_changed.connect(self.tray.status_action.setText)

        self.recorder = Recorder(on_level=self.pill.set_level, warm=self.cfg["warm_mic"])
        self.pipeline = Pipeline(self.cfg, self.db, on_state=self.pill.set_state, on_status=self.set_status)
        self.ptt = PushToTalk(self._start, self._finish, self._cancel,
                              on_lock=self._lock)
        self.listener = macos.HotkeyListener(lambda: self.cfg["hotkey"], self.ptt.key_down, self.ptt.key_up,
                                             self.ptt.cancel)
        self._app_name = None
        self._last_used = 0.0
        self._pressed = 0.0  # time.monotonic() of the last transcription (or warm-up)

        self.jobs = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()
        self.show_requested.connect(self.open_dashboard)
        self.server = DashboardServer(self.cfg, self.db, port=int(os.environ.get("LIKHO_PORT", 8765)),
                                      status=lambda: dict(self.status), on_show=self.show_requested.emit).start()
        self.cfg.on_change(self._settings_changed)

    # -- lifecycle ---------------------------------------------------------
    def run(self):
        perms = macos.permissions()
        if not all(perms.values()):
            macos.request_permissions()
            missing = " and ".join(k.replace("_", " ").title() for k, ok in perms.items() if not ok)
            self.set_status(error=f"Grant {missing} in System Settings → Privacy & Security, then restart Likho")
        self.listener.start()
        QTimer.singleShot(1500, self._check_listener)
        self._load_model()
        llm.prewarm(self.cfg.all())
        if os.environ.pop("LIKHO_SHOW_DASHBOARD", None):  # opened by clicking Likho (not at login)
            QTimer.singleShot(0, self.open_dashboard)
        print(f"Likho is running. Dashboard: {self.server.url}")

    def _check_listener(self):
        if self.listener.failed.is_set():
            self.set_status(error="Can't see the hotkey: allow Input Monitoring for this app, then restart Likho")
            self.pill.set_state(overlay.ERROR)

    def _load_model(self):
        def job():
            model = self.cfg["model"]
            self.set_status(message=f"Loading {model.split('/')[-1]} (first time downloads it)…")
            warm_up(model)
            self._last_used = time.monotonic()
            self.set_status(message=f"Ready · hold {self.cfg['hotkey'].replace('_', ' ')} to talk")
        self.jobs.put(job)

    def _worker(self):
        while True:
            job = self.jobs.get()
            try:
                job()
            except Exception as e:
                traceback.print_exc()
                self.set_status(error=f"{type(e).__name__}: {e}")
                self.pill.set_state(overlay.ERROR)

    def set_status(self, message=None, **kw):
        if message is not None:
            self.status["message"] = message
        if "error" in kw:
            self.status["error"] = kw["error"]
        self.status_changed.emit(self.status["error"] or self.status["message"])

    # -- push-to-talk callbacks (dispatcher thread) ---------------------------
    def _start(self):
        llm.prewarm(self.cfg.all())  # local AI model loads while you talk
        if time.monotonic() - self._last_used > IDLE_REWARM_SECONDS:
            # After a break macOS lets the speech model go cold (first dictation 4-6 s instead of <1 s).
            # Wake it up now, while you're still talking; the real job queues right behind it.
            self.jobs.put(self._rewarm)
        self._app_name = macos.frontmost_app()
        self._pressed = time.monotonic()
        log(f"key down in {self._app_name!r}")
        self.pill.set_state(overlay.RECORDING)
        try:
            self.recorder.start()
        except Exception as e:
            self.set_status(error=f"Microphone error: {e}")
            self.pill.set_state(overlay.ERROR)
            self.ptt.state = self.ptt.IDLE

    def _lock(self):
        log("hands-free on (double-tap): tap again to finish")
        self.pill.set_state(overlay.LOCKED)

    def _finish(self):
        released = time.monotonic()
        log(f"finished after {released - self._pressed:.1f}s")
        self.pill.set_state(overlay.TRANSCRIBING)  # react instantly; the mic keeps going for the post-roll
        audio, app_name = self.recorder.stop(), self._app_name
        self.jobs.put(lambda: self._handle(audio, app_name, released))

    def _handle(self, audio, app_name, released):
        self.pipeline.handle(audio, app_name, released_at=released)
        self._last_used = time.monotonic()

    def _rewarm(self):
        try:
            warm_up(self.cfg["model"])
        except Exception:
            traceback.print_exc()
        self._last_used = time.monotonic()

    def _cancel(self):
        log("cancelled (Esc, or a single short tap)")
        self.recorder.cancel()
        self.pill.set_state(overlay.IDLE)

    # -- UI ----------------------------------------------------------------
    def open_dashboard(self):
        if self.window is None:
            self.window = DashboardWindow(self.server.url)
        self.window.show_and_focus()
        print("Dashboard window shown", flush=True)

    def _toggle_ai(self, on):
        self.cfg.update({"ai_enabled": on})

    def _settings_changed(self, changes):
        if "model" in changes:
            self._load_model()
        if "warm_mic" in changes:
            self.recorder.set_warm(changes["warm_mic"])
        if "ai_enabled" in changes:
            self.tray.ai_action.setChecked(changes["ai_enabled"])
        if any(k.startswith("ai_") for k in changes):
            llm.prewarm(self.cfg.all())
        if "hotkey" in changes and not self.status["error"]:
            self.set_status(message=f"Ready · hold {changes['hotkey'].replace('_', ' ')} to talk")


def main():
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    signal.signal(signal.SIGINT, lambda *_: qapp.quit())
    QTimer(qapp, interval=250, timeout=lambda: None).start()  # lets Ctrl+C through while Qt runs
    macos.hide_dock_icon()
    try:
        app = LikhoApp(qapp)
    except OSError as e:
        if e.errno == 48:  # address in use → Likho is already running: opening it again shows the dashboard
            print("Likho is already running (the dashboard port is taken) — opening the dashboard.")
            webbrowser.open(f"http://127.0.0.1:{os.environ.get('LIKHO_PORT', 8765)}")
            sys.exit(0)
        raise
    app.run()
    if os.environ.get("LIKHO_LAUNCHER"):
        # Started by Likho.app's launcher: if it's gone (e.g. force-quit), don't linger as an orphan.
        QTimer(qapp, interval=2000, timeout=lambda: os.getppid() == 1 and qapp.quit()).start()
    sys.exit(qapp.exec())
