"""Draws the Likho app icon (1024×1024 PNG): sound bars flowing into a pen stroke, white on a black tile."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from likho.overlay import MARK  # noqa: E402

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

scale, cx, cy = 0.82, 465, 500  # centre of the mark's box
p.setPen(Qt.NoPen)
p.setBrush(QColor("white"))
for x, y, w, h, r in MARK:
    p.drawRoundedRect(QRectF((x - cx) * scale + S / 2, (y - cy) * scale + S / 2, w * scale, h * scale),
                      r * scale, r * scale)
p.end()
img.save(sys.argv[1])
