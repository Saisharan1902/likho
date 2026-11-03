"""The floating pill at the bottom of the screen + the menu-bar icon.

States: idle (thin bar) → recording (live waveform) → transcribing (pulsing dots) → done (✓) / error (!).
set_state / set_level are safe to call from any thread.
"""
import math
from collections import deque

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

IDLE, RECORDING, LOCKED, TRANSCRIBING, DONE, ERROR = "idle", "recording", "locked", "transcribing", "done", "error"

# capsule (width, height) per state
SIZES = {IDLE: (44, 8), RECORDING: (132, 34), LOCKED: (150, 34), TRANSCRIBING: (84, 34), DONE: (44, 34),
         ERROR: (44, 34)}
WIN_W, WIN_H = 220, 60
BARS = 22

BG = QColor(17, 17, 17, 235)
BORDER = QColor(255, 255, 255, 46)
INK = QColor(245, 245, 245)
RED = QColor(235, 87, 87)
GREEN = QColor(80, 200, 120)


class _Bridge(QObject):
    state = Signal(str)


class Pill(QWidget):
    """Display only: it ignores the mouse entirely so it can never steal focus from the app you type in."""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(WIN_W, WIN_H)
        self.state = IDLE
        self._w, self._h = SIZES[IDLE]
        self._level = 0.0
        self._levels = deque([0.0] * BARS, maxlen=BARS)
        self._phase = 0.0

        self._bridge = _Bridge()
        self._bridge.state.connect(self._apply_state)  # queued onto the GUI thread
        self._revert = QTimer(self, singleShot=True, timeout=lambda: self._apply_state(IDLE))
        self._tick = QTimer(self, interval=16, timeout=self._animate)
        self._tick.start()
        self._place()

    # -- thread-safe API ---------------------------------------------------
    def set_state(self, state):
        self._bridge.state.emit(state)

    def set_level(self, level):
        self._level = max(self._level, level)  # read + reset by the animation tick

    # ---------------------------------------------------------------------
    def _place(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - WIN_W // 2, screen.bottom() - WIN_H - 6)

    def _apply_state(self, state):
        if state == RECORDING and self.state == LOCKED:
            return
        if state in (RECORDING, LOCKED) and self.state not in (RECORDING, LOCKED):
            self._levels.extend([0.0] * BARS)  # fresh waveform for a new recording only
        self.state = state
        self._revert.stop()
        self._animate()  # react on this frame, not the next tick
        if state in (DONE, ERROR):
            self._revert.start(900 if state == DONE else 1800)
        if not self._tick.isActive():
            self._tick.start()

    def _animate(self):
        tw, th = SIZES[self.state]
        self._w += (tw - self._w) * 0.4
        self._h += (th - self._h) * 0.4
        self._phase += 0.12
        if self.state in (RECORDING, LOCKED):
            self._levels.append(self._level)
            self._level = 0.0
        self.update()
        settled = abs(tw - self._w) < 0.5 and abs(th - self._h) < 0.5
        if self.state == IDLE and settled:
            self._tick.stop()  # no CPU use while idle

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self._w, self._h
        rect = QRectF((WIN_W - w) / 2, WIN_H - h - 4, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, h / 2, h / 2)
        p.setOpacity(0.6 if self.state == IDLE else 1.0)
        p.fillPath(path, BG)
        p.setPen(QPen(BORDER, 1))
        p.drawPath(path)
        p.setOpacity(1.0)
        cx, cy = rect.center().x(), rect.center().y()

        if self.state in (RECORDING, LOCKED) and h > 24:
            left = rect.left() + 14
            if self.state == LOCKED:  # red dot = hands-free
                p.setPen(Qt.NoPen)
                p.setBrush(RED)
                p.drawEllipse(QRectF(left, cy - 4, 8, 8))
                left += 14
            span = rect.right() - 14 - left
            step = span / BARS
            p.setPen(Qt.NoPen)
            p.setBrush(INK)
            for i, lv in enumerate(self._levels):
                bh = max(3.0, min(h - 12, 3 + lv * (h - 12)))
                p.drawRoundedRect(QRectF(left + i * step + step * 0.2, cy - bh / 2, step * 0.6, bh), 1.5, 1.5)
        elif self.state == TRANSCRIBING and h > 24:
            p.setPen(Qt.NoPen)
            p.setBrush(INK)
            for i in range(3):
                a = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(self._phase - i * 0.9))
                p.setOpacity(a)
                p.drawEllipse(QRectF(cx - 16 + i * 14, cy - 3.5, 7, 7))
            p.setOpacity(1.0)
        elif self.state in (DONE, ERROR) and h > 24:
            p.setPen(QPen(GREEN if self.state == DONE else RED, 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if self.state == DONE:
                p.drawPolyline([QRectF(cx - 7, cy, 0, 0).topLeft(), QRectF(cx - 2, cy + 5, 0, 0).topLeft(),
                                QRectF(cx + 7, cy - 5, 0, 0).topLeft()])
            else:
                p.drawLine(int(cx), int(cy - 7), int(cx), int(cy + 2))
                p.drawPoint(int(cx), int(cy + 7))
        p.end()


def _tray_icon() -> QIcon:
    pm = QPixmap(36, 36)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.black)
    for i, bh in enumerate((10, 20, 28, 20, 10)):  # little waveform glyph
        p.drawRoundedRect(QRectF(4 + i * 6, 18 - bh / 2, 4, bh), 2, 2)
    p.end()
    icon = QIcon(pm)
    icon.setIsMask(True)  # macOS tints it for light/dark menu bar
    return icon


def make_tray(on_open_dashboard, on_toggle_ai, ai_enabled, on_quit, on_open_browser=None):
    tray = QSystemTrayIcon(_tray_icon())
    menu = QMenu()
    status = QAction("Ready", menu, enabled=False)
    menu.addAction(status)
    menu.addSeparator()
    menu.addAction("Open Dashboard", on_open_dashboard)
    if on_open_browser:
        menu.addAction("Open Dashboard in Browser", on_open_browser)
    ai = QAction("AI Cleanup", menu, checkable=True, checked=ai_enabled)
    ai.toggled.connect(on_toggle_ai)
    menu.addAction(ai)
    menu.addSeparator()
    menu.addAction("Quit Dictly", on_quit)
    tray.setContextMenu(menu)
    tray.setToolTip("Dictly — local dictation")
    tray.status_action, tray.ai_action, tray.menu_ = status, ai, menu  # keep references alive
    tray.show()
    return tray
