"""Section 5 manual check: see the floating pill + menu-bar icon.

    .venv/bin/python scripts/try_overlay.py         # demo: cycles through every state
    .venv/bin/python scripts/try_overlay.py live    # hold Right Option and talk: waveform follows your voice

The pill ignores the mouse (it's display-only). Quit from the menu-bar icon (waveform glyph) or Ctrl+C.
"""
import math
import random
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dictly import macos, overlay  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
signal.signal(signal.SIGINT, lambda *_: app.quit())
QTimer(app, interval=200, timeout=lambda: None).start()  # lets Python see Ctrl+C while Qt runs
macos.hide_dock_icon()

pill = overlay.Pill()
pill.show()
macos.make_overlay_window(pill)
tray = overlay.make_tray(lambda: print("Open Dashboard clicked"),
                         lambda on: print("AI cleanup:", on), False, app.quit)

if len(sys.argv) > 1 and sys.argv[1] == "live":
    from dictly.audio import SAMPLE_RATE, Recorder
    from dictly.ptt import PushToTalk

    t = {}

    def on_level(level):
        t.setdefault("first_audio", time.monotonic())
        pill.set_level(level)

    rec = Recorder(on_level=on_level, warm=True)

    def start():
        t.clear()
        t["down"] = time.monotonic()
        pill.set_state(overlay.RECORDING)
        rec.start()
        print(f"● key down — mic opened in {time.monotonic() - t['down']:.2f}s")

    def finish():
        pill.set_state(overlay.TRANSCRIBING)
        held = time.monotonic() - t["down"]
        audio = rec.stop()
        first = t.get("first_audio", t["down"]) - t["down"]
        print(f"✓ held {held:.2f}s → captured {len(audio) / SAMPLE_RATE:.2f}s of audio "
              f"(first sound arrived after {first:.2f}s)")
        # real transcription comes in Section 7; pretend it takes 1.2s
        threading.Timer(1.2, lambda: pill.set_state(overlay.DONE)).start()

    def cancel():
        rec.cancel()
        print("✕ cancelled")
        pill.set_state(overlay.ERROR)

    def lock():
        print("🔒 hands-free — tap again to finish")
        pill.set_state(overlay.LOCKED)

    ptt = PushToTalk(start, finish, cancel, on_lock=lock)
    listener = macos.HotkeyListener(lambda: "right_option", ptt.key_down, ptt.key_up, ptt.cancel)
    listener.start()
    print("Live mode: hold Right Option and talk (double-tap = hands-free, Esc cancels). Ctrl+C to quit.")
else:
    steps = [(overlay.IDLE, 1500), (overlay.RECORDING, 3500), (overlay.TRANSCRIBING, 2000),
             (overlay.DONE, 1500), (overlay.LOCKED, 3000), (overlay.ERROR, 2500)]
    t0 = time.time()

    def fake_voice():
        if pill.state in (overlay.RECORDING, overlay.LOCKED):
            pill.set_level(abs(math.sin((time.time() - t0) * 3)) * random.uniform(0.3, 1.0))

    QTimer(app, interval=30, timeout=fake_voice).start()

    def run(i=0):
        state, ms = steps[i % len(steps)]
        print("state:", state)
        pill.set_state(state)
        QTimer.singleShot(ms, lambda: run(i + 1))

    run()
    print("Demo: cycles through every state automatically (this is NOT recording). Ctrl+C to quit.")

sys.exit(app.exec())
