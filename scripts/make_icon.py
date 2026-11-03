"""Draws the Dictly app icon (1024×1024 PNG): waveform bars on a blue rounded square."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath  # noqa: E402

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
g = QLinearGradient(0, m, 0, S - m)
g.setColorAt(0, QColor("#3d8bf0"))
g.setColorAt(1, QColor("#1f5fc2"))
p.fillPath(body, g)

p.setPen(Qt.NoPen)
p.setBrush(QColor("white"))
heights = [180, 340, 470, 340, 180]
bw, gap = 72, 44
x0 = S / 2 - (len(heights) * bw + (len(heights) - 1) * gap) / 2
for i, h in enumerate(heights):
    p.drawRoundedRect(QRectF(x0 + i * (bw + gap), S / 2 - h / 2, bw, h), bw / 2, bw / 2)
p.end()
img.save(sys.argv[1])
