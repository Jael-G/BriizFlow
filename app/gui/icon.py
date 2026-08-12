"""Runtime-generated application icons (no binary assets required).

The app logo is rendered from ``app/assets/icon.svg`` through
``QSvgRenderer``, so the logo can be redesigned by editing that one SVG — no
code changes. If the SVG is missing or invalid, it falls back to the legacy
QPainter-drawn microphone so the app never shows a blank icon.

Note: Qt's SVG renderer does not support ``<filter>`` elements (drop shadows,
blurs), so those parts of the SVG are silently skipped. Gradients and shapes
render normally.
"""
import os
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
_SVG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', 'icon.svg')

def make_app_icon(size=64):
    """App logo from ``app/assets/icon.svg`` at ``size`` logical pixels.

    Renders at 2x DPR for crisp hi-dpi output. Falls back to the legacy
    QPainter-drawn microphone if the SVG can't be loaded.
    """
    renderer = QSvgRenderer(_SVG_PATH)
    if not renderer.isValid():
        return _legacy_icon(size)
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QIcon(pm)


def tray_icon():
    return make_app_icon(32)

from PySide6.QtCore import QPointF
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPen
ACCENT_A = QColor(104, 142, 255)
ACCENT_B = QColor(72, 94, 235)

def _legacy_icon(size=64):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0, ACCENT_A)
    grad.setColorAt(1, ACCENT_B)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(grad))
    radius = size * 0.26
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
    stroke = max(2, size * 0.07)
    body_w = size * 0.34
    body_h = size * 0.4
    top = size * 0.16
    cx = size / 2
    pen = QPen(QColor('white'), stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(cx - body_w / 2, top, body_w, body_h), size * 0.14, size * 0.14)
    painter.drawArc(QRectF(cx - body_w / 2 - stroke, top - stroke, body_w + 2 * stroke, body_h * 2 + 2 * stroke), 480, 1920)
    painter.drawLine(QPointF(cx, top + body_h + stroke * 2), QPointF(cx, top + body_h + size * 0.22))
    painter.drawLine(QPointF(cx - body_w * 0.8, top + body_h + size * 0.26), QPointF(cx + body_w * 0.8, top + body_h + size * 0.26))
    painter.end()
    return QIcon(pm)

