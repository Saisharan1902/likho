"""macOS integration: global push-to-talk hotkey, pasting into the focused app, frontmost app name.

Uses a raw Quartz event tap (not pynput) and only reads keycodes/modifier flags, which avoids the
background-thread keyboard-layout crashes pynput has on recent macOS.
"""
import queue
import threading
import time
import traceback

import AppKit
import Quartz

# Device-specific modifier bits (distinguish left/right keys)
_KEYS = {
    "right_option": (61, 0x40),
    "right_command": (54, 0x10),
    "right_control": (62, 0x2000),
    "right_shift": (60, 0x04),
    "fn": (63, Quartz.kCGEventFlagMaskSecondaryFn),
}
_ESC = 53
_V = 9


class HotkeyListener:
    """Calls on_down / on_up when the configured modifier key is pressed / released, on_cancel on Esc.

    The event-tap callback must return instantly (macOS disables slow taps and drops key events), so it
    only queues the handler; a separate dispatcher thread runs it (e.g. opening the microphone).
    """

    def __init__(self, get_hotkey, on_down, on_up, on_cancel):
        self.get_hotkey = get_hotkey
        self.on_down, self.on_up, self.on_cancel = on_down, on_up, on_cancel
        self._down = False
        self._tap = None
        self._pending = queue.Queue()
        self.ok = threading.Event()
        self.failed = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        threading.Thread(target=self._dispatch, daemon=True).start()

    def _dispatch(self):
        while True:
            self._call(self._pending.get())

    def _drain(self):
        """Run queued handlers on the calling thread (used by tests)."""
        while not self._pending.empty():
            self._call(self._pending.get_nowait())

    @staticmethod
    def _call(fn):
        try:
            fn()
        except Exception:
            traceback.print_exc()

    def _callback(self, proxy, etype, event, refcon):
        if etype in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
            Quartz.CGEventTapEnable(self._tap, True)
            return event
        keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        if etype == Quartz.kCGEventFlagsChanged:
            code, mask = _KEYS.get(self.get_hotkey(), _KEYS["right_option"])
            if keycode == code:
                pressed = bool(Quartz.CGEventGetFlags(event) & mask)
                if pressed and not self._down:
                    self._down = True
                    self._pending.put(self.on_down)
                elif not pressed and self._down:
                    self._down = False
                    self._pending.put(self.on_up)
        elif etype == Quartz.kCGEventKeyDown and keycode == _ESC:
            self._pending.put(self.on_cancel)
        return event

    def _run(self):
        mask = Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged) | Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
        self._tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                            Quartz.kCGEventTapOptionListenOnly, mask, self._callback, None)
        if self._tap is None:
            self.failed.set()
            return
        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)
        self.ok.set()
        Quartz.CFRunLoopRun()


def frontmost_app() -> str | None:
    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    return str(app.localizedName()) if app else None


def _clipboard_get():
    return AppKit.NSPasteboard.generalPasteboard().stringForType_(AppKit.NSPasteboardTypeString)


def _clipboard_set(text):
    pb = AppKit.NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, AppKit.NSPasteboardTypeString)


def copy_to_clipboard(text):
    _clipboard_set(text)


def paste_text(text, restore_clipboard=True):
    """Put text on the clipboard, send Cmd+V to the focused app, then restore the old clipboard."""
    previous = _clipboard_get() if restore_clipboard else None
    _clipboard_set(text)
    time.sleep(0.05)
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, _V, down)
        Quartz.CGEventSetFlags(ev, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
    if previous is not None:
        def restore():
            time.sleep(0.6)
            _clipboard_set(previous)
        threading.Thread(target=restore, daemon=True).start()


def permissions() -> dict:
    """Input Monitoring is needed to see the hotkey; Accessibility to send Cmd+V."""
    return {"input_monitoring": bool(Quartz.CGPreflightListenEventAccess()),
            "accessibility": bool(Quartz.CGPreflightPostEventAccess())}


def request_permissions():
    """Shows the macOS prompts / adds this app to the lists in System Settings → Privacy & Security."""
    Quartz.CGRequestListenEventAccess()
    Quartz.CGRequestPostEventAccess()


def make_overlay_window(widget):
    """Float the Qt widget above everything, on every Space and over full-screen apps, without taking focus."""
    import objc
    view = objc.objc_object(c_void_p=int(widget.winId()))
    win = view.window()
    win.setLevel_(AppKit.NSStatusWindowLevel)
    win.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                               | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
                               | AppKit.NSWindowCollectionBehaviorStationary)
    win.setHidesOnDeactivate_(False)
    win.setIgnoresMouseEvents_(True)  # clicks/hover go straight through to the app underneath


def activate_app():
    AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)


def hide_dock_icon():
    AppKit.NSApplication.sharedApplication().setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
