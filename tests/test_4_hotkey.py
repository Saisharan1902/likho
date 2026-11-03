"""Section 4 — hotkey detection, push-to-talk logic, clipboard.

These feed synthetic key events straight into the listener's callback, so they need no permissions.
Real key presses + pasting are checked by scripts/try_hotkey.py.
"""
import Quartz
import pytest

from dictly import macos
from dictly.ptt import PushToTalk


def _flags_event(keycode, flags):
    ev = Quartz.CGEventCreate(None)
    Quartz.CGEventSetType(ev, Quartz.kCGEventFlagsChanged)
    Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGKeyboardEventKeycode, keycode)
    Quartz.CGEventSetFlags(ev, flags)
    return ev


def _key_event(keycode):
    return Quartz.CGEventCreateKeyboardEvent(None, keycode, True)


@pytest.fixture
def listener():
    events = []
    hotkey = {"name": "right_option"}
    hl = macos.HotkeyListener(lambda: hotkey["name"], lambda: events.append("down"),
                              lambda: events.append("up"), lambda: events.append("cancel"))
    hl.events, hl.hotkey = events, hotkey
    return hl


def send(hl, ev):
    out = hl._callback(None, Quartz.CGEventGetType(ev), ev, None)
    hl._drain()
    return out


def test_callback_only_queues_work(listener):
    slow = []
    listener.on_down = lambda: slow.append("ran")
    listener._callback(None, Quartz.kCGEventFlagsChanged, _flags_event(61, ALT | 0x40), None)
    assert slow == []  # nothing ran inside the event tap
    listener._drain()
    assert slow == ["ran"]


ALT = Quartz.kCGEventFlagMaskAlternate


def test_right_option_press_release(listener):
    send(listener, _flags_event(61, ALT | 0x40))  # right option down
    send(listener, _flags_event(61, 0))           # released
    assert listener.events == ["down", "up"]


def test_left_option_is_ignored(listener):
    send(listener, _flags_event(58, ALT | 0x20))
    send(listener, _flags_event(58, 0))
    assert listener.events == []


def test_right_option_released_while_left_still_held(listener):
    send(listener, _flags_event(61, ALT | 0x40))
    send(listener, _flags_event(61, ALT | 0x20))  # left option still down, right released
    assert listener.events == ["down", "up"]


def test_hotkey_change_applies_live(listener):
    listener.hotkey["name"] = "fn"
    send(listener, _flags_event(61, ALT | 0x40))
    send(listener, _flags_event(63, Quartz.kCGEventFlagMaskSecondaryFn))
    send(listener, _flags_event(63, 0))
    assert listener.events == ["down", "up"]


def test_escape_cancels_and_events_pass_through(listener):
    ev = _key_event(53)
    assert send(listener, ev) is ev  # we only listen, never swallow keys
    assert listener.events == ["cancel"]


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def ptt():
    log, clock, timers = [], Clock(), []
    p = PushToTalk(lambda: log.append("start"), lambda: log.append("finish"),
                   lambda: log.append("cancel"), on_lock=lambda: log.append("lock"), clock=clock,
                   schedule=lambda secs, fn: timers.append(fn))  # fire timers manually
    p.log, p.clock_, p.timers = log, clock, timers
    return p


def tap(p, at):
    p.clock_.t = at
    p.key_down()
    p.clock_.t = at + 0.1
    p.key_up()


def test_hold_to_talk(ptt):
    ptt.key_down()
    ptt.clock_.t = 2.0
    ptt.key_up()
    assert ptt.log == ["start", "finish"] and ptt.state == "idle"


def test_single_tap_is_discarded(ptt):
    tap(ptt, 0)
    assert ptt.state == "tapped"
    ptt.timers[-1]()  # double-tap window passes with no second tap
    assert ptt.log == ["start", "cancel"] and ptt.state == "idle"


def test_double_tap_locks_hands_free_then_tap_finishes(ptt):
    tap(ptt, 0)
    tap(ptt, 0.2)
    assert ptt.log == ["start", "lock"] and ptt.state == "locked"
    ptt.timers[0]()  # the first tap's timer firing late must not cancel hands-free
    assert ptt.state == "locked"
    tap(ptt, 10)
    assert ptt.log == ["start", "lock", "finish"] and ptt.state == "idle"


def test_short_but_real_hold_still_counts(ptt):
    ptt.key_down()
    ptt.clock_.t = 0.4  # "Stop." — short word, but longer than a tap
    ptt.key_up()
    assert ptt.log == ["start", "finish"]


def test_stale_timer_from_earlier_tap_is_ignored(ptt):
    tap(ptt, 0)
    ptt.timers[0]()                     # first single tap expires → cancelled
    tap(ptt, 5)                         # new tap...
    ptt.timers[0]()                     # ...an old timer firing again changes nothing
    assert ptt.state == "tapped"
    ptt.timers[1]()
    assert ptt.log == ["start", "cancel", "start", "cancel"]


def test_cancel(ptt):
    ptt.cancel()  # nothing recording → no-op
    ptt.key_down()
    ptt.cancel()
    ptt.clock_.t = 5
    ptt.key_up()
    assert ptt.log == ["start", "cancel"] and ptt.state == "idle"


def test_clipboard_roundtrip():
    before = macos._clipboard_get()
    try:
        macos.copy_to_clipboard("dictly clipboard test ✓")
        assert macos._clipboard_get() == "dictly clipboard test ✓"
    finally:
        if before is not None:
            macos.copy_to_clipboard(before)


def test_frontmost_app_returns_a_name():
    assert isinstance(macos.frontmost_app(), str)
