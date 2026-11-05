"""Draws the Likho app icon (1024×1024 PNG): a white "d" on a black tile, a small blue waveform in its bowl."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen  # noqa: E402

app = QGuiApplication([])
S = 1024
img = QImage(S, S, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)

# macOS icon grid: ~824px rounded square centred in 1024
m = 100
body = QPainterPath()
body.addRoundedRect(QRectF(m, m, S - 2 * m, S - 2 * m), 185, 185)
g = QLinearGradient(0, m, S, S - m)
g.setColorAt(0, QColor("#111111"))
g.setColorAt(1, QColor("#2a2a2a"))
p.fillPath(body, g)

# the "d": a ring (bowl) and a stem on its right
p.setPen(QPen(QColor("white"), 92, Qt.SolidLine, Qt.RoundCap))
p.setBrush(Qt.NoBrush)
p.drawEllipse(QPointF(455, 600), 175, 175)
p.drawLine(QPointF(676, 250), QPointF(676, 775))

# waveform inside the bowl
p.setPen(Qt.NoPen)
p.setBrush(QColor("#58a6ff"))
for i, h in enumerate([70, 150, 90]):
    x = 405 + i * 50
    p.drawRoundedRect(QRectF(x - 15, 600 - h / 2, 30, h), 15, 15)
p.end()
img.save(sys.argv[1])
