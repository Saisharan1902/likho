"""Section 4 manual check: real hotkey + paste.

    .venv/bin/python scripts/try_hotkey.py

Then click into Notes / TextEdit / any text box and:
  - hold Right Option ~1s and release   → pastes a line ("hold")
  - double-tap Right Option, then tap    → pastes a line ("hands-free")
  - single quick tap                    → ignored, nothing pasted
  - double-tap, then press Esc          → cancelled, nothing pasted
Ctrl+C here to quit.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dictly import macos  # noqa: E402
from dictly.ptt import PushToTalk  # noqa: E402

perms = macos.permissions()
print("Permissions:", perms)
if not all(perms.values()):
    macos.request_permissions()
    print("\n⚠️  Grant your terminal app (Terminal / iTerm / VS Code) both:\n"
          "   System Settings → Privacy & Security → Input Monitoring\n"
          "   System Settings → Privacy & Security → Accessibility\n"
          "   then QUIT and reopen the terminal and run this again.")

started = {}


def start():
    started["t"], started["app"] = time.monotonic(), macos.frontmost_app()
    print(f"● recording…  (focused app: {started['app']})")


def finish():
    secs = time.monotonic() - started["t"]
    mode = "hands-free" if ptt_mode["locked"] else "hold"
    text = f"Hello from Dictly 👋 ({mode}, {secs:.1f}s) "
    print(f"✓ finished after {secs:.1f}s → pasting {text!r}")
    macos.paste_text(text)


def cancel():
    print("✕ cancelled")


ptt_mode = {"locked": False}


def lock():
    ptt_mode["locked"] = True
    print("🔒 hands-free mode — tap again to finish, Esc to cancel")


def start_fresh():
    ptt_mode["locked"] = False
    start()


ptt = PushToTalk(start_fresh, finish, cancel, on_lock=lock)
listener = macos.HotkeyListener(lambda: "right_option", ptt.key_down, ptt.key_up, ptt.cancel)
listener.start()
time.sleep(0.5)
if listener.failed.is_set():
    sys.exit("✗ Could not listen to the keyboard — Input Monitoring permission is missing.")
print("\nListening. Hold Right Option… (Ctrl+C to quit)")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
