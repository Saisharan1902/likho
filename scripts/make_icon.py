"""Draws the Likho app icon (1024×1024 PNG): sound bars that settle into a written line and a blue cursor
(speak → write), on a black tile."""
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


def bar(cx, h, w, color):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(cx - w / 2, S / 2 - h / 2, w, h), w / 2, w / 2)


# voice: four sound bars
for x, h in zip((250, 320, 390, 460), (120, 260, 340, 190)):
    bar(x, h, 48, "white")
# …settling into a written line
p.setPen(QPen(QColor("white"), 48, Qt.SolidLine, Qt.RoundCap))
p.drawLine(QPointF(530, S / 2), QPointF(700, S / 2))
# …and the text cursor
bar(772, 230, 30, "#58a6ff")
p.end()
img.save(sys.argv[1])
