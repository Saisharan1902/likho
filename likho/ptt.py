"""Push-to-talk state machine: turns raw key down/up events into start / finish / cancel.

- Hold the key and talk, release to finish.
- Double-tap locks into hands-free mode; tap once more to finish.
- A single short tap does nothing (discarded) — no accidental hands-free.
- Esc cancels whatever is being recorded.
"""
import threading
import time

TAP_SECONDS = 0.25  # a press shorter than this is a "tap", not a hold
DOUBLE_TAP_WINDOW = 0.35  # second tap must start within this long after the first one ends


def _schedule(seconds, fn):
    t = threading.Timer(seconds, fn)
    t.daemon = True
    t.start()


class PushToTalk:
    IDLE, HOLDING, TAPPED, LOCKED = "idle", "holding", "tapped", "locked"

    def __init__(self, on_start, on_finish, on_cancel, on_lock=lambda: None, clock=time.monotonic,
                 schedule=_schedule):
        self.on_start, self.on_finish, self.on_cancel, self.on_lock = on_start, on_finish, on_cancel, on_lock
        self.clock, self.schedule = clock, schedule
        self.state = self.IDLE
        self._pressed_at = 0.0
        self._tap_id = 0
        self._lock = threading.Lock()

    def key_down(self):
        with self._lock:
            if self.state == self.IDLE:
                self.state, self._pressed_at = self.HOLDING, self.clock()
                action = self.on_start  # start recording right away so nothing is lost
            elif self.state == self.TAPPED:
                self.state = self.LOCKED  # second tap → hands-free
                action = self.on_lock
            elif self.state == self.LOCKED:
                self.state = self.IDLE
                action = self.on_finish
            else:
                return
        action()

    def key_up(self):
        with self._lock:
            if self.state != self.HOLDING:
                return  # releases of the 2nd tap / finishing tap don't matter
            if self.clock() - self._pressed_at < TAP_SECONDS:
                self.state = self.TAPPED  # maybe the first half of a double-tap; keep recording for now
                self._tap_id += 1
                tap_id = self._tap_id
                self.schedule(DOUBLE_TAP_WINDOW, lambda: self._tap_expired(tap_id))
                return
            self.state = self.IDLE
        self.on_finish()

    def _tap_expired(self, tap_id):
        with self._lock:
            if self.state != self.TAPPED or tap_id != self._tap_id:
                return
            self.state = self.IDLE  # it was just a single tap → throw it away
        self.on_cancel()

    def cancel(self):
        with self._lock:
            if self.state == self.IDLE:
                return
            self.state = self.IDLE
        self.on_cancel()
